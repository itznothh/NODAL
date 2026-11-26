"""Region registry tests use an isolated Mongo-shaped in-memory fixture."""
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bson import ObjectId

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import create_app
from backend.geography import filter_complaints_to_region, point_in_geometry, region_overview_metrics
from backend.regions import BENGALURU_PILOT_TEMPLATE, validate_boundary, validate_region_document


class FakeCollection:
    def __init__(self):
        self.rows = []
        self.indexes = []

    def create_index(self, *_args, **_kwargs):
        self.indexes.append((_args, _kwargs))
        return "isolated-test-index"

    def find(self, query=None):
        query = query or {}
        return [dict(row) for row in self.rows if all(row.get(key) == value for key, value in query.items())]

    def find_one(self, query=None):
        query = query or {}
        return next((dict(row) for row in self.rows if all(row.get(key) == value for key, value in query.items())), None)

    def insert_one(self, document):
        row = dict(document)
        row.setdefault("_id", ObjectId())
        self.rows.append(row)
        return type("InsertResult", (), {"inserted_id": row["_id"]})()


class FakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def polygon():
    # Test-only geometry, not a real or proposed administrative boundary.
    return {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}


def rectangle(west, south, east, north):
    return [[west, south], [east, south], [east, north], [west, north], [west, south]]


def region(region_id="in", name="Test", region_type="country", parent_region_id=None,
           status="draft", boundary=None, version="v1"):
    now = datetime.now(timezone.utc)
    row = {
        "region_id": region_id, "name": name, "region_type": region_type,
        "parent_region_id": parent_region_id, "boundary": boundary,
        "boundary_version": version,
        "source": {"organization": "Test Fixture", "title": "Synthetic unit geometry", "url": "https://example.test/source"},
        "provenance": {"dataset_id": "unit-test-only", "acquired_at": now.isoformat(), "checksum_sha256": "a" * 64, "notes": "Not geographic source data."},
        "license": {"name": "Test-only", "url": "https://example.test/license", "redistribution_status": "pending"},
        "approval_status": status, "created_at": now, "updated_at": now,
    }
    if status in {"approved", "superseded"}:
        row["license"]["redistribution_status"] = "cleared"
        row["approved_by"] = ObjectId()
        row["approved_at"] = now
    return row


class RegionBoundaryValidationTests(unittest.TestCase):
    def test_polygon_and_multipolygon_structure_is_accepted(self):
        self.assertEqual(validate_boundary(polygon()), [])
        multi = {"type": "MultiPolygon", "coordinates": [polygon()["coordinates"], polygon()["coordinates"]]}
        self.assertEqual(validate_boundary(multi), [])

    def test_invalid_and_empty_geojson_is_rejected(self):
        invalid_geometries = [
            None,
            {"type": [], "coordinates": []},
            {"type": "Point", "coordinates": [0, 0]},
            {"type": "Polygon", "coordinates": []},
            {"type": "MultiPolygon", "coordinates": [[]]},
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1]]]},
            {"type": "Polygon", "coordinates": [[[0, 0], [200, 0], [1, 1], [0, 0]]]},
            {"type": "Polygon", "coordinates": [[[0, False], [1, 0], [1, 1], [0, False]]]},
            {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [2, 0], [0, 0]]]},
            {"type": "Polygon", "coordinates": polygon()["coordinates"], "crs": {"type": "name"}},
        ]
        for geometry in invalid_geometries:
            with self.subTest(geometry=geometry):
                self.assertTrue(validate_boundary(geometry))

    def test_coordinate_order_is_longitude_then_latitude(self):
        invalid_latitude = {"type": "Polygon", "coordinates": [[[0, 0], [1, 95], [2, 1], [0, 0]]]}
        self.assertTrue(validate_boundary(invalid_latitude))

    def test_empty_boundary_allowed_only_for_nonapproved_pilot_template(self):
        self.assertEqual(BENGALURU_PILOT_TEMPLATE["region_id"], "in-ka-greater-bengaluru")
        self.assertEqual(BENGALURU_PILOT_TEMPLATE["name"], "Greater Bengaluru Area")
        self.assertEqual(BENGALURU_PILOT_TEMPLATE["region_type"], "city")
        self.assertIsNone(BENGALURU_PILOT_TEMPLATE["boundary"])
        self.assertEqual(BENGALURU_PILOT_TEMPLATE["approval_status"], "draft")
        self.assertEqual(BENGALURU_PILOT_TEMPLATE["license"]["redistribution_status"], "pending")
        self.assertTrue(validate_region_document(region("in-ka-bengaluru", "Bengaluru", "city", "in-ka",
                                                        status="approved", boundary=None)))


class GeographicFilteringTests(unittest.TestCase):
    def test_polygon_hole_boundary_and_multipolygon(self):
        polygon_geometry = {"type": "Polygon", "coordinates": [
            rectangle(0, 0, 10, 10), rectangle(4, 4, 6, 6)]}
        self.assertTrue(point_in_geometry((2, 2), polygon_geometry))
        self.assertFalse(point_in_geometry((5, 5), polygon_geometry))
        # Outer and hole ring boundaries are included by the edge policy.
        self.assertTrue(point_in_geometry((0, 5), polygon_geometry))
        self.assertTrue(point_in_geometry((4, 5), polygon_geometry))
        multi = {"type": "MultiPolygon", "coordinates": [
            [rectangle(20, 20, 21, 21)], [rectangle(30, 30, 31, 31)]]}
        self.assertTrue(point_in_geometry((30.5, 30.5), multi))
        self.assertFalse(point_in_geometry((25, 25), multi))

    def test_filter_excludes_invalid_and_unlocated_points(self):
        geometry = {"type": "Polygon", "coordinates": [rectangle(0, 0, 10, 10)]}
        rows = [
            {"location": {"type": "Point", "coordinates": [1, 1]}},
            {"location": {"type": "Point", "coordinates": [float("nan"), 1]}},
            {"location": {"type": "Point", "coordinates": [1, 1, 2]}},
            {"location": None},
            {"location": {"type": "Point", "coordinates": [11, 1]}},
        ]
        self.assertEqual(filter_complaints_to_region(rows, geometry), [rows[0]])

    def test_empty_region_metrics_suppress_sparse_values(self):
        metrics, suppressed = region_overview_metrics([])
        self.assertEqual(set(suppressed), set(metrics))
        self.assertTrue(all(value is None for value in metrics.values()))
        few_rows = [{"status": "submitted", "priority": "low"} for _ in range(3)]
        metrics, suppressed = region_overview_metrics(few_rows)
        self.assertEqual(set(suppressed), set(metrics))
        self.assertTrue(all(value is None for value in metrics.values()))


class RegionDocumentValidationTests(unittest.TestCase):
    def test_parent_type_and_approval_are_required_for_approved_region(self):
        row = region("in-ka-bengaluru", "Bengaluru", "city", "in-ka", "approved", polygon())
        parent = region("in-ka", "Karnataka", "state", "in", "approved", polygon())
        self.assertEqual(validate_region_document(row, parent=parent), [])
        wrong_type = region("in-ka", "Not a state", "country", None, "approved", polygon())
        self.assertTrue(validate_region_document(row, parent=wrong_type))
        parent["approval_status"] = "draft"
        self.assertTrue(validate_region_document(row, parent=parent))
        self.assertTrue(validate_region_document(row))

    def test_region_version_pair_must_be_unique(self):
        row = region()
        self.assertIn("region_id and boundary_version must be unique.", validate_region_document(row, [row]))
        self.assertEqual(validate_region_document(row, [region(version="v0")]), [])

    def test_approved_region_requires_boundary_provenance_and_redistribution_clearance(self):
        row = region("in", "Test", "country", status="approved", boundary=polygon())
        self.assertEqual(validate_region_document(row), [])
        row["license"]["redistribution_status"] = "pending"
        self.assertTrue(any("redistribution clearance" in error for error in validate_region_document(row)))

    def test_malformed_untrusted_values_are_rejected_without_type_errors(self):
        row = region()
        row["region_type"] = []
        row["approval_status"] = []
        self.assertTrue(validate_region_document(row))


class RegionReadApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.database = FakeDatabase()
        environment = {
            "NODAL_ENV": "development", "NODAL_AUDIT_MODE": "true",
            "NODAL_DB_NAME": "nodal_phase8_audit", "NODAL_SECRET_KEY": "region-test-secret-32-characters-long",
            "MONGO_URI": "mongodb://127.0.0.1:27017", "NODAL_EVIDENCE_DIR": self.tempdir.name,
        }
        self.env = patch.dict(os.environ, environment)
        self.env.start()
        self.app = create_app(database=self.database, test_config={"TESTING": True})
        self.client = self.app.test_client()
        now_approved = region("in", "Test country", "country", None, "approved", polygon())
        now_state = region("in-ka", "Test state", "state", "in", "approved", polygon())
        now_city = region("in-ka-example", "Test city", "city", "in-ka", "approved", polygon())
        draft = region("in-ka-draft", "Draft city", "city", "in-ka", "draft", polygon())
        malformed = region("in-ka-malformed", "Malformed", "city", "in-ka", "approved", polygon())
        malformed["approval_status"] = []
        self.database["regions"].rows.extend([now_approved, now_state, now_city, draft, malformed])

    def tearDown(self):
        self.env.stop()
        self.tempdir.cleanup()

    def test_public_reads_expose_approved_hierarchy_only(self):
        response = self.client.get("/public/regions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["region_id"] for row in response.get_json()}, {"in", "in-ka", "in-ka-example"})
        self.assertNotIn("boundary", response.get_json()[0])
        self.assertNotIn("in-ka-malformed", {row["region_id"] for row in response.get_json()})
        city = self.client.get("/public/regions/in-ka-example")
        self.assertEqual(city.status_code, 200)
        self.assertEqual(city.get_json()["boundary"]["type"], "Polygon")
        self.assertEqual(self.client.get("/public/regions/in-ka-draft").status_code, 404)

    def test_admin_registry_read_requires_admin_role_and_includes_drafts(self):
        self.assertEqual(self.client.get("/admin/regions").status_code, 401)
        citizen_id = ObjectId()
        self.database["users"].insert_one({"_id": citizen_id, "role": "citizen", "status": "active"})
        with self.client.session_transaction() as session:
            session["user_id"] = str(citizen_id)
        self.assertEqual(self.client.get("/admin/regions").status_code, 403)

        admin_id = ObjectId()
        self.database["users"].insert_one({"_id": admin_id, "role": "admin", "status": "active"})
        with self.client.session_transaction() as session:
            session["user_id"] = str(admin_id)
        response = self.client.get("/admin/regions")
        self.assertEqual(response.status_code, 200)
        self.assertIn("in-ka-draft", {row["region_id"] for row in response.get_json()})
        self.assertIn("boundary", response.get_json()[0])

    def test_registry_reads_do_not_create_region_indexes(self):
        self.client.get("/public/regions")
        # App startup indexes only existing collections; registry indexes are
        # intentionally left for an explicitly approved isolated migration.
        self.assertEqual(self.database["regions"].indexes, [])


class RegionGeographicApiTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.database = FakeDatabase()
        environment = {
            "NODAL_ENV": "development", "NODAL_AUDIT_MODE": "true",
            "NODAL_DB_NAME": "nodal_phase8_audit", "NODAL_SECRET_KEY": "region-geo-test-secret-32-characters",
            "MONGO_URI": "mongodb://127.0.0.1:27017", "NODAL_EVIDENCE_DIR": self.tempdir.name,
        }
        self.env = patch.dict(os.environ, environment)
        self.env.start()
        self.app = create_app(database=self.database, test_config={"TESTING": True})
        self.client = self.app.test_client()

        self.geometry = {"type": "Polygon", "coordinates": [
            rectangle(0, 0, 10, 10), rectangle(4, 4, 6, 6)]}
        self.database["regions"].rows.extend([
            region("test-country", "Test country", "country", None, "approved",
                   {"type": "Polygon", "coordinates": [rectangle(-20, -20, 20, 20)]}),
            region("test-state", "Test state", "state", "test-country", "approved",
                   {"type": "Polygon", "coordinates": [rectangle(-10, -10, 15, 15)]}),
            region("test-city", "Synthetic test region", "city", "test-state", "approved", self.geometry),
        ])

    def tearDown(self):
        self.env.stop()
        self.tempdir.cleanup()

    def test_region_overview_filters_before_aggregation_and_suppresses_small_metrics(self):
        for index in range(5):
            self.database["complaints"].insert_one({
                "status": "assigned", "category": "pothole", "priority": "low",
                "location": {"type": "Point", "coordinates": [2 + index * 0.00001, 2]},
                "created_by": ObjectId(), "images": [{"storage_key": "private-key"}],
            })
        self.database["complaints"].insert_one({
            "status": "submitted", "category": "garbage", "priority": "high",
            "location": {"type": "Point", "coordinates": [0, 5]},
        })  # boundary edge is included
        self.database["complaints"].insert_one({
            "status": "assigned", "location": {"type": "Point", "coordinates": [5, 5]},
        })  # inside the hole: excluded
        self.database["complaints"].insert_one({
            "status": "assigned", "location": {"type": "Point", "coordinates": [20, 20]},
        })  # outside: excluded
        self.database["complaints"].insert_one({
            "status": "assigned", "location": {"type": "Point", "coordinates": [float("nan"), 2]},
        })  # invalid: excluded

        response = self.client.get("/public/regions/test-city/overview")
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(body["scope"]["type"], "region")
        self.assertEqual(body["scope"]["region"]["region_id"], "test-city")
        self.assertEqual(body["scope"]["region"]["boundary_version"], "v1")
        self.assertEqual(body["metrics"]["total_complaints"], 6)
        self.assertEqual(body["metrics"]["open_complaints"], 6)
        self.assertEqual(body["metrics"]["high_priority_open"], None)
        self.assertIn("high_priority_open", body["privacy_suppression"]["suppressed_metrics"])
        self.assertIn("valid coordinates inside the approved boundary", body["data_quality_notice"])
        self.assertFalse(body["privacy_suppression"]["formal_anonymity_guarantee"])
        self.assertNotIn("created_by", str(body))
        self.assertNotIn("private-key", str(body))

    def test_region_hotspots_are_suppressed_and_return_no_private_fields(self):
        for index in range(5):
            self.database["complaints"].insert_one({
                "status": "in_progress", "category": "drainage", "priority": "high",
                "location": {"type": "Point", "coordinates": [2 + index * 0.00001, 2]},
                "created_by": ObjectId(), "assigned_official_id": ObjectId(),
                "images": [{"storage_key": "private-evidence"}],
            })
        response = self.client.get("/public/regions/test-city/hotspots")
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual(len(body["hotspots"]), 1)
        self.assertGreaterEqual(body["hotspots"][0]["count"], 5)
        self.assertNotIn("private-evidence", str(body))
        self.assertNotIn("assigned_official_id", str(body))
        self.assertTrue(body["privacy_suppression"]["hotspot_centers_coarsened"])

    def test_region_resolution_errors_are_consistent(self):
        unknown = self.client.get("/public/regions/no-such-region/overview")
        self.assertEqual((unknown.status_code, unknown.get_json()["error"]["code"]), (404, "region_not_found"))
        invalid = self.client.get("/public/regions/Not_A_Slug/overview")
        self.assertEqual((invalid.status_code, invalid.get_json()["error"]["code"]), (400, "invalid_region_id"))
        draft = self.client.get("/public/regions/in-ka-greater-bengaluru/overview")
        self.assertEqual((draft.status_code, draft.get_json()["error"]["code"]), (409, "region_not_approved"))

        missing_boundary = region("missing-boundary", "Missing", "city", "test-state", "approved", None)
        retired = region("retired-region", "Retired", "city", "test-state", "superseded", self.geometry)
        invalid = region("invalid-region", "Invalid", "city", "test-state", "approved",
                         {"type": "Polygon", "coordinates": []})
        self.database["regions"].rows.extend([missing_boundary, retired, invalid])
        for region_id, expected_status, expected_code in [
            ("missing-boundary", 409, "boundary_missing"),
            ("retired-region", 410, "boundary_version_retired"),
            ("invalid-region", 422, "invalid_region"),
        ]:
            response = self.client.get(f"/public/regions/{region_id}/hotspots")
            self.assertEqual((response.status_code, response.get_json()["error"]["code"]),
                             (expected_status, expected_code))


if __name__ == "__main__":
    unittest.main()
