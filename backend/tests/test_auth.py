"""Auth/access tests use an isolated in-memory Mongo-shaped fake; no live DB writes."""
import os
import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from tempfile import TemporaryDirectory

from bson import ObjectId
from PIL import Image
from pymongo.errors import DuplicateKeyError

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import app as default_app
from backend.app import _hotspot_data, _valid_coordinates, _valid_geojson_point, create_app
from backend.auth import roles_required
from backend.bootstrap_admin import create_first_admin
from werkzeug.security import check_password_hash


class Cursor(list):
    def sort(self, key, direction=1):
        def value(row):
            item = row.get(key)
            if isinstance(item, datetime):
                return (0, item.timestamp())
            return (1, str(item or "").casefold())
        return Cursor(sorted(self, key=value, reverse=direction < 0))

    def limit(self, amount):
        return Cursor(self[:amount])


class Collection:
    def __init__(self):
        self.rows = []
        self.indexes = []

    def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))
        return "test_index"

    @staticmethod
    def matches(row, query):
        for key, value in query.items():
            if key == "$or":
                if not any(Collection.matches(row, alternative) for alternative in value):
                    return False
            elif isinstance(value, dict) and "$nin" in value:
                if row.get(key) in value["$nin"]:
                    return False
            elif row.get(key) != value:
                return False
        return True

    def find_one(self, query=None, *args, **kwargs):
        query = query or {}
        return next((dict(row) for row in self.rows if self.matches(row, query)), None)

    def insert_one(self, document):
        row = dict(document)
        row.setdefault("_id", ObjectId())
        if any(old["_id"] == row["_id"] for old in self.rows):
            raise DuplicateKeyError("duplicate _id")
        if "email" in row and any(old.get("email") == row["email"] for old in self.rows):
            raise DuplicateKeyError("duplicate email")
        self.rows.append(row)
        return SimpleNamespace(inserted_id=row["_id"])

    def update_one(self, query, update):
        row = next((row for row in self.rows if self.matches(row, query)), None)
        if row is None:
            return SimpleNamespace(matched_count=0, modified_count=0)
        for key, value in update.get("$set", {}).items():
            row[key] = value
        for key in update.get("$unset", {}):
            row.pop(key, None)
        for key, value in update.get("$push", {}).items():
            row.setdefault(key, []).append(value)
        return SimpleNamespace(matched_count=1, modified_count=1)

    def delete_one(self, query):
        row = next((row for row in self.rows if self.matches(row, query)), None)
        if row:
            self.rows.remove(row)
        return SimpleNamespace(deleted_count=1 if row else 0)

    def find(self, query=None):
        query = query or {}
        return Cursor([dict(row) for row in self.rows if self.matches(row, query)])


class Database:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, Collection())


class DatabaseConfigurationTests(unittest.TestCase):
    def make_client(self):
        client = MagicMock()
        client.__getitem__.return_value = Database()
        return client

    def test_missing_database_name_preserves_nodal_default(self):
        mongo_client = self.make_client()
        with patch.dict(os.environ, {"MONGO_URI": "mongodb://127.0.0.1:27017",
                                     "USERPROFILE": str(ROOT.parent)}, clear=True):
            with patch("backend.app.MongoClient", return_value=mongo_client) as mongo_factory:
                app = create_app()
        mongo_factory.assert_called_once_with("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=5000,
                                              connect=False)
        mongo_client.__getitem__.assert_called_once_with("nodal")
        self.assertIs(app.extensions["nodal_db"], mongo_client.__getitem__.return_value)

    def test_explicit_audit_mode_selects_only_audit_database(self):
        for database_name in ("nodal_phase7_audit", "nodal_phase8_audit"):
            with self.subTest(database_name=database_name):
                mongo_client = self.make_client()
                environment = {"MONGO_URI": "mongodb://127.0.0.1:27017", "NODAL_AUDIT_MODE": "true",
                               "NODAL_DB_NAME": database_name, "USERPROFILE": str(ROOT.parent)}
                with patch.dict(os.environ, environment, clear=True):
                    with patch("backend.app.MongoClient", return_value=mongo_client):
                        app = create_app()
                mongo_client.__getitem__.assert_called_once_with(database_name)
                self.assertIs(app.extensions["nodal_db"], mongo_client.__getitem__.return_value)

    def test_invalid_audit_configuration_fails_before_mongo_client_creation(self):
        invalid_environments = (
            {"NODAL_AUDIT_MODE": "true"},
            {"NODAL_AUDIT_MODE": "true", "NODAL_DB_NAME": "nodal"},
            {"NODAL_AUDIT_MODE": "sometimes", "NODAL_DB_NAME": "nodal_phase7_audit"},
        )
        for environment in invalid_environments:
            with self.subTest(environment=environment):
                with patch.dict(os.environ, {"MONGO_URI": "mongodb://127.0.0.1:27017",
                                             "USERPROFILE": str(ROOT.parent), **environment}, clear=True):
                    with patch("backend.app.MongoClient") as mongo_factory:
                        with self.assertRaises(RuntimeError):
                            create_app()
                mongo_factory.assert_not_called()


class CorsConfigurationTests(unittest.TestCase):
    def make_app(self, **settings):
        environment = {
            "NODAL_ENV": "development",
            "NODAL_SECRET_KEY": "cors-test-secret-with-32-plus-characters",
            "MONGO_URI": "mongodb://127.0.0.1:27017",
            "NODAL_AUDIT_MODE": "true",
            "NODAL_DB_NAME": "nodal_phase7_audit",
            "NODAL_CORS_ORIGINS": "http://localhost:5173,http://127.0.0.1:5173",
            "USERPROFILE": str(ROOT.parent),
            **settings,
        }
        with patch.dict(os.environ, environment, clear=True):
            return create_app(database=Database(), test_config={"TESTING": True})

    def test_audit_frontend_origin_is_allowed_with_credentials_and_untrusted_origin_is_rejected(self):
        client = self.make_app().test_client()

        for path, expected_status in (("/auth/csrf", 200), ("/auth/me", 401),
                                      ("/public/overview", 200), ("/hotspots", 200)):
            with self.subTest(path=path):
                allowed = client.get(path, headers={"Origin": "http://127.0.0.1:5174"})
                self.assertEqual(allowed.status_code, expected_status)
                self.assertEqual(allowed.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:5174")
                self.assertEqual(allowed.headers.get("Access-Control-Allow-Credentials"), "true")

        existing = client.get("/auth/csrf", headers={"Origin": "http://127.0.0.1:5173"})
        self.assertEqual(existing.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:5173")
        self.assertEqual(existing.headers.get("Access-Control-Allow-Credentials"), "true")

        untrusted = client.get("/auth/csrf", headers={"Origin": "https://untrusted.example"})
        self.assertNotIn("Access-Control-Allow-Origin", untrusted.headers)

    def test_development_origin_is_not_implicitly_added_in_production(self):
        app = self.make_app(NODAL_ENV="production", NODAL_AUDIT_MODE="false",
                            NODAL_DB_NAME="nodal", NODAL_CORS_ORIGINS="https://nodal.example.test")
        response = app.test_client().get("/auth/csrf", headers={"Origin": "http://127.0.0.1:5174"})
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        mongo_client = default_app.extensions.get("nodal_mongo_client")
        if mongo_client is not None:
            mongo_client.close()

    def setUp(self):
        self.database = Database()
        self.app = create_app(database=self.database, test_config={"TESTING": True, "SECRET_KEY": "unit-test-secret"})
        self.client = self.app.test_client()

    def csrf(self):
        response = self.client.get("/auth/csrf")
        self.assertEqual(response.status_code, 200)
        return response.get_json()["csrf_token"]

    def post(self, path, payload, token=None):
        return self.client.post(path, json=payload, headers={"X-CSRF-Token": token or self.csrf()})

    def register(self, email="citizen@example.test", **extra):
        payload = {"full_name": "A Citizen", "email": email, "password": "a-long-test-password", **extra}
        response = self.post("/auth/register", payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def login(self, email, password):
        return self.post("/auth/login", {"email": email, "password": password})

    def test_registration_always_creates_hashed_citizen_and_csrf_protects_mutations(self):
        token = self.csrf()
        denied = self.client.post("/auth/register", json={"full_name": "A", "email": "a@b.co", "password": "a-long-test-password"})
        self.assertEqual(denied.status_code, 403)
        response = self.post("/auth/register", {"full_name": "Citizen Name", "email": "citizen@example.test",
                                                "password": "a-long-test-password", "role": "admin"}, token)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["user"]["role"], "citizen")
        stored = self.database["users"].find_one({"email": "citizen@example.test"})
        self.assertNotEqual(stored["password_hash"], "a-long-test-password")
        self.assertTrue(check_password_hash(stored["password_hash"], "a-long-test-password"))
        self.assertNotIn("password_hash", response.get_json()["user"])

    def test_login_logout_and_http_only_session_cookie(self):
        self.register()
        failed = self.login("citizen@example.test", "wrong-password")
        self.assertEqual(failed.status_code, 401)
        logged_in = self.login("citizen@example.test", "a-long-test-password")
        self.assertEqual(logged_in.status_code, 200)
        self.assertEqual(logged_in.get_json()["user"]["role"], "citizen")
        cookie = logged_in.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertEqual(self.client.get("/auth/me").status_code, 200)
        self.assertEqual(self.post("/auth/logout", {}, logged_in.get_json()["csrf_token"]).status_code, 200)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_profile_update_is_authenticated_for_every_role_and_cannot_change_access(self):
        citizen = self.register()
        create_first_admin(self.database, "profile-admin@example.test", "admin-profile-password")
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "profile-official@example.test",
                                            "full_name": "Verified Official", "role": "official", "status": "active",
                                            "department": "Road Infrastructure", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        admin_id = self.database["users"].find_one({"email": "profile-admin@example.test"})["_id"]
        for role, oid in (("citizen", citizen["user"]["id"]), ("official", str(official_id)), ("admin", str(admin_id))):
            client = self.app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = oid
                session["csrf_token"] = f"{role}-profile-token"
            response = client.patch("/auth/profile", json={"full_name": f"Updated {role}", "role": "admin",
                                                            "department": "Spoofed"},
                                    headers={"X-CSRF-Token": f"{role}-profile-token"})
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()["user"]["role"], role)
            stored = self.database["users"].find_one({"_id": ObjectId(oid)})
            self.assertEqual(stored["full_name"], f"Updated {role}")
            self.assertEqual(stored.get("department"), "Road Infrastructure" if role == "official" else None)
        anonymous = self.app.test_client()
        token = anonymous.get("/auth/csrf").get_json()["csrf_token"]
        denied = anonymous.patch("/auth/profile", json={"full_name": "No Account"}, headers={"X-CSRF-Token": token})
        self.assertEqual(denied.status_code, 401)

    def test_backend_guards_existing_complaint_routes(self):
        self.assertEqual(self.client.get("/complaints").status_code, 401)
        self.register()
        self.assertEqual(self.client.get("/complaints").status_code, 200)
        denied = self.client.patch("/complaints/" + str(ObjectId()), json={"status": "resolved"}, headers={"X-CSRF-Token": self.csrf()})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.delete("/complaints/" + str(ObjectId()), headers={"X-CSRF-Token": self.csrf()}).status_code, 403)

    def test_citizen_can_create_and_only_read_own_reports_while_admin_sees_legacy_sample(self):
        citizen = self.register()
        payload = {"description": "A deep pothole by the bus stop", "category": "pothole",
                   "lat": 12.97, "lng": 77.59, "priority": "high"}
        with patch("backend.app.find_duplicates", return_value=[{
            "id": str(ObjectId()), "description": "Another resident's report", "similarity": 0.86,
        }]):
            created = self.post("/complaints", payload, citizen["csrf_token"])
        self.assertEqual(created.status_code, 201, created.get_json())
        row = created.get_json()
        self.assertEqual(row["status"], "submitted")
        self.assertNotEqual(row["priority"], "high")  # client cannot choose priority
        self.assertNotEqual(row.get("data_quality"), "demo_sample_unverified")
        self.assertNotIn("created_by", row)
        self.assertNotIn("assigned_official_id", row)
        self.assertTrue(all("actor_id" not in event for event in row["status_history"]))
        self.assertEqual(row["possible_duplicates"], [{"similarity": 0.86}])
        complaint_id = row["_id"]
        detail_response = self.client.get(f"/complaints/{complaint_id}")
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.get_json()
        self.assertNotIn("created_by", detail)
        self.assertTrue(all("actor_id" not in event for event in detail["status_history"]))
        citizen_rows = self.client.get("/complaints").get_json()
        self.assertTrue(all("created_by" not in item for item in citizen_rows))
        self.assertTrue(all("assigned_official_id" not in item for item in citizen_rows))

        other_client = self.app.test_client()
        csrf = other_client.get("/auth/csrf").get_json()["csrf_token"]
        other_client.post("/auth/register", json={"full_name": "Other Citizen", "email": "other@example.test",
                                                   "password": "another-long-password"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(other_client.get(f"/complaints/{complaint_id}").status_code, 404)
        self.assertEqual(other_client.get("/complaints").get_json(), [])

        legacy_id = self.database["complaints"].insert_one({"description": "Legacy generated sample", "category": "garbage",
                                                "priority": "low", "status": "open",
                                                "location": {"type": "Point", "coordinates": [77.6, 12.9]}}).inserted_id
        self.assertEqual(self.client.get(f"/complaints/{legacy_id}").status_code, 404)
        self.assertTrue(all(item["_id"] != str(legacy_id) for item in self.client.get("/complaints").get_json()))
        create_first_admin(self.database, "admin@example.test", "a-different-long-password")
        admin_login = self.login("admin@example.test", "a-different-long-password")
        admin_rows = self.client.get("/complaints").get_json()
        legacy = next(item for item in admin_rows if item["description"] == "Legacy generated sample")
        self.assertEqual(legacy["data_quality"], "demo_sample_unverified")
        self.assertNotIn("created_by", legacy)

    def test_official_request_stays_pending_until_admin_independently_verifies(self):
        @roles_required("official")
        def official_only():
            return {"ok": True}, 200
        self.app.add_url_rule("/test/official-only-pending", view_func=official_only, methods=["GET"])

        citizen = self.register()
        applicant = self.database["users"].find_one({"email": "citizen@example.test"})
        request_payload = {"employee_id": "E-123", "department": "Road infrastructure",
                           "designation": "Engineer", "verification_information": "Contact details for independent check"}
        request_response = self.post("/auth/official-access-requests", request_payload, citizen["csrf_token"])
        self.assertEqual(request_response.status_code, 201)
        request_id = request_response.get_json()["request"]["id"]
        self.assertEqual(request_response.get_json()["request"]["status"], "pending")
        self.assertEqual(self.database["users"].find_one({"_id": applicant["_id"]})["role"], "citizen")
        self.assertEqual(self.client.get("/admin/official-access-requests").status_code, 403)
        self.assertEqual(self.client.get("/test/official-only-pending").status_code, 403)

        create_first_admin(self.database, "admin@example.test", "a-different-long-password")
        admin_login = self.login("admin@example.test", "a-different-long-password")
        self.assertEqual(admin_login.status_code, 200)
        missing_verification = self.post(f"/admin/official-access-requests/{request_id}/decision",
                                         {"decision": "approve"}, admin_login.get_json()["csrf_token"])
        self.assertEqual(missing_verification.status_code, 400)
        self.assertEqual(self.database["users"].find_one({"_id": applicant["_id"]})["role"], "citizen")
        missing_rejection_reason = self.post(f"/admin/official-access-requests/{request_id}/decision",
                                             {"decision": "reject", "notes": "  "},
                                             admin_login.get_json()["csrf_token"])
        self.assertEqual(missing_rejection_reason.status_code, 400)
        self.assertEqual(self.database["official_access_requests"].find_one({"_id": ObjectId(request_id)})["status"], "pending")
        approved = self.post(f"/admin/official-access-requests/{request_id}/decision",
                             {"decision": "approve", "independently_verified": True,
                              "verification_method": "department_contact",
                              "verification_notes": "Confirmed directly with department contact.",
                              "department": "Road infrastructure"}, admin_login.get_json()["csrf_token"])
        self.assertEqual(approved.status_code, 200, approved.get_json())
        official = self.database["users"].find_one({"_id": applicant["_id"]})
        self.assertEqual(official["role"], "official")
        self.assertEqual(official["department"], "Road Infrastructure")
        self.assertEqual(official["department_id"], "road-infrastructure")
        self.assertEqual(self.database["official_access_requests"].find_one({"_id": ObjectId(request_id)})["status"], "approved")
        assigned_id = ObjectId()
        self.database["complaints"].insert_one({"_id": assigned_id, "created_by": ObjectId(),
                                                  "assigned_official_id": applicant["_id"], "description": "Assigned work"})
        self.database["complaints"].insert_one({"created_by": ObjectId(), "assigned_official_id": ObjectId(),
                                                  "description": "Other official work"})
        official_client = self.app.test_client()
        token = official_client.get("/auth/csrf").get_json()["csrf_token"]
        official_login = official_client.post("/auth/login", json={"email": "citizen@example.test",
                                                                    "password": "a-long-test-password"},
                                              headers={"X-CSRF-Token": token})
        self.assertEqual(official_login.status_code, 200)
        visible = official_client.get("/complaints").get_json()
        self.assertEqual([item["description"] for item in visible], ["Assigned work"])
        self.assertEqual(official_client.get(f"/complaints/{assigned_id}").status_code, 200)

    def test_first_admin_bootstrap_is_one_time_and_public_registration_cannot_create_admin(self):
        self.register(role="admin")
        self.assertIsNone(self.database["users"].find_one({"role": "admin"}))
        create_first_admin(self.database, "first-admin@example.test", "secure-admin-password")
        with self.assertRaisesRegex(RuntimeError, "bootstrap has already run"):
            create_first_admin(self.database, "second-admin@example.test", "another-secure-password")
        self.assertEqual(len([row for row in self.database["users"].rows if row["role"] == "admin"]), 1)

    def test_production_requires_environment_secret(self):
        with patch.dict(os.environ, {"NODAL_ENV": "production"}, clear=False):
            os.environ.pop("NODAL_SECRET_KEY", None)
            with self.assertRaisesRegex(RuntimeError, "NODAL_SECRET_KEY"):
                create_app(database=Database())

    def test_role_decorator_checks_database_role_not_client_payload(self):
        @roles_required("official")
        def official_only():
            return {"ok": True}, 200
        self.app.add_url_rule("/test/official-only", view_func=official_only, methods=["GET"])
        self.register(role="official")
        self.assertEqual(self.client.get("/test/official-only").status_code, 403)

    def test_unverified_official_is_denied_from_every_official_enabled_api_route(self):
        @roles_required("official")
        def official_only():
            return {"ok": True}, 200

        self.app.add_url_rule("/test/official-only", view_func=official_only, methods=["GET"])
        citizen = self.register()
        report_id = ObjectId()
        self.database["complaints"].insert_one({"_id": report_id,
            "created_by": ObjectId(citizen["user"]["id"]), "description": "Isolated auth fixture",
            "status": "in_progress", "status_history": [], "assignment_history": [], "images": []})
        missing_fields_id = ObjectId()
        self.database["users"].insert_one({"_id": missing_fields_id, "email": "unverified@example.test",
                                             "role": "official", "status": "active",
                                             "department": "Stormwater Drainage"})
        pending_id = ObjectId()
        self.database["users"].insert_one({"_id": pending_id, "email": "pending@example.test",
                                             "role": "official", "status": "active",
                                             "department": "Stormwater Drainage"})
        self.database["official_access_requests"].insert_one({"user_id": pending_id, "status": "pending"})
        rejected_id = ObjectId()
        self.database["users"].insert_one({"_id": rejected_id, "email": "rejected@example.test",
                                             "role": "official", "status": "active",
                                             "department": "Stormwater Drainage"})
        self.database["official_access_requests"].insert_one({"user_id": rejected_id, "status": "rejected"})

        protected_routes = (
            ("GET", "/complaints"),
            ("GET", f"/complaints/{report_id}"),
            ("GET", f"/complaints/{report_id}/evidence/nonexistent"),
            ("POST", f"/complaints/{report_id}/transition"),
            ("PATCH", "/auth/profile"),
            ("GET", "/test/official-only"),
        )
        for official_id in (missing_fields_id, pending_id, rejected_id):
            client = self.app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = str(official_id)
                session["csrf_token"] = "official-test-token"
            for method, path in protected_routes:
                if method == "GET":
                    response = client.get(path)
                elif method == "POST":
                    response = client.post(path, json={"status": "in_progress"},
                                           headers={"X-CSRF-Token": "official-test-token"})
                else:
                    response = client.patch(path, json={"full_name": "Unverified"},
                                            headers={"X-CSRF-Token": "official-test-token"})
                self.assertEqual(response.status_code, 403, (official_id, method, path, response.get_json()))

        # This is the original audit reproducer: an active official with no
        # approval fields must not receive the complaint list.
        unverified = self.app.test_client()
        with unverified.session_transaction() as session:
            session["user_id"] = str(missing_fields_id)
        self.assertEqual(unverified.get("/complaints").status_code, 403)

        # Pending access requests do not promote the citizen account.
        self.assertEqual(self.database["users"].find_one({"_id": ObjectId(citizen["user"]["id"])})["role"], "citizen")

    def test_official_verification_gate_preserves_verified_official_citizen_and_admin_access(self):
        @roles_required("official")
        def official_only():
            return {"ok": True}, 200

        self.app.add_url_rule("/test/official-only", view_func=official_only, methods=["GET"])
        now = datetime.now(timezone.utc)
        inactive_id = ObjectId()
        self.database["users"].insert_one({"_id": inactive_id, "email": "inactive@example.test",
                                             "role": "official", "status": "inactive",
                                             "official_verified_at": now, "official_verified_by": ObjectId()})
        inactive = self.app.test_client()
        with inactive.session_transaction() as session:
            session["user_id"] = str(inactive_id)
        self.assertEqual(inactive.get("/complaints").status_code, 401)
        self.assertEqual(inactive.get("/test/official-only").status_code, 401)

        verified_id = ObjectId()
        self.database["users"].insert_one({"_id": verified_id, "email": "verified@example.test",
                                             "role": "official", "status": "active",
                                             "department": "Stormwater Drainage",
                                             "official_verified_at": now, "official_verified_by": ObjectId()})
        verified = self.app.test_client()
        with verified.session_transaction() as session:
            session["user_id"] = str(verified_id)
            session["csrf_token"] = "verified-token"
        self.assertEqual(verified.get("/complaints").status_code, 200)
        self.assertEqual(verified.get("/test/official-only").status_code, 200)
        self.assertEqual(verified.post("/complaints/" + str(ObjectId()) + "/assign", json={"department": "Other"},
                                       headers={"X-CSRF-Token": "verified-token"}).status_code, 403)

        self.register()
        self.assertEqual(self.client.get("/complaints").status_code, 200)
        self.assertEqual(self.client.get("/test/official-only").status_code, 403)
        create_first_admin(self.database, "admin@example.test", "a-different-long-password")
        self.assertEqual(self.login("admin@example.test", "a-different-long-password").status_code, 200)
        self.assertEqual(self.client.get("/complaints").status_code, 200)
        self.assertEqual(self.client.get("/admin/departments").status_code, 200)


class ComplaintLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.database = Database()
        self.app = create_app(database=self.database, test_config={"TESTING": True, "SECRET_KEY": "unit-test-secret"})
        self.client = self.app.test_client()

    def csrf(self):
        return self.client.get("/auth/csrf").get_json()["csrf_token"]

    def post(self, path, payload, token=None):
        return self.client.post(path, json=payload, headers={"X-CSRF-Token": token or self.csrf()})

    def register(self, email="citizen@example.test", **extra):
        response = self.post("/auth/register", {"full_name": "A Citizen", "email": email,
                                                 "password": "a-long-test-password", **extra})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def login(self, email, password):
        return self.post("/auth/login", {"email": email, "password": password})

    def admin(self):
        create_first_admin(self.database, "admin@example.test", "a-different-long-password")
        return self.login("admin@example.test", "a-different-long-password").get_json()

    def create_report(self, client=None):
        client = client or self.client
        token = client.get("/auth/csrf").get_json()["csrf_token"]
        with patch("backend.app.find_duplicates", return_value=[]):
            response = client.post("/complaints", json={"description": "A blocked road drain near the park",
                                                         "category": "drainage", "lat": 12.9, "lng": 77.6},
                                   headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_citizen_owns_tracking_and_cannot_change_or_delete_report(self):
        citizen = self.register()
        report = self.create_report()
        token = citizen["csrf_token"]
        for status in ("triaged", "assigned", "in_progress", "resolved", "disputed"):
            response = self.client.post(f"/complaints/{report['_id']}/transition", json={"status": status},
                                        headers={"X-CSRF-Token": token})
            self.assertEqual(response.status_code, 409, (status, response.get_json()))
        other = self.app.test_client()
        other.get("/auth/csrf")
        self.assertEqual(other.get(f"/complaints/{report['_id']}").status_code, 401)
        detail = self.client.get(f"/complaints/{report['_id']}").get_json()
        self.assertEqual(detail["status"], "submitted")
        self.assertEqual(detail["status_history"][0]["actor_role"], "citizen")

    def test_priority_and_department_filters_remain_scoped_to_authenticated_user(self):
        citizen = self.register()
        owner_id = ObjectId(citizen["user"]["id"])
        other_owner = ObjectId()
        rows = [
            {"_id": ObjectId(), "created_by": owner_id, "description": "Mine high", "status": "submitted",
             "priority": "high", "department": "Road Infrastructure"},
            {"_id": ObjectId(), "created_by": owner_id, "description": "Mine low", "status": "submitted",
             "priority": "low", "department": "Road Infrastructure"},
            {"_id": ObjectId(), "created_by": other_owner, "description": "Other high", "status": "submitted",
             "priority": "high", "department": "Road Infrastructure"},
        ]
        for row in rows:
            self.database["complaints"].insert_one(row)
        response = self.client.get("/complaints?priority=high&department=Road Infrastructure")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["description"] for row in response.get_json()], ["Mine high"])
        self.assertEqual(self.client.get("/complaints?priority=urgent").status_code, 400)

    def test_assignment_requires_admin_verified_official_and_matching_department(self):
        self.register()
        report = self.create_report()
        admin = self.admin()
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "off@example.test", "role": "official",
                                            "status": "active", "department": "Road Infrastructure", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        path = f"/complaints/{report['_id']}/assign"
        response = self.client.post(path, json={"department": "Road Infrastructure", "official_id": str(official_id),
                                               "reason": "Phase 5 test assignment."}, headers=headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        assigned = response.get_json()
        self.assertEqual(assigned["status"], "assigned")
        self.assertEqual(assigned["department"], "Road Infrastructure")
        self.assertEqual(assigned["assigned_official_id"], str(official_id))
        self.assertEqual(assigned["status_history"][-1]["action"], "assigned")
        self.assertEqual(self.client.post(path, json={"department": "Water Supply", "official_id": str(official_id)},
                                          headers=headers).status_code, 400)

    def test_assignment_and_verified_official_directory_permissions(self):
        citizen = self.register()
        report = self.create_report()
        assignment_path = f"/complaints/{report['_id']}/assign"
        citizen_headers = {"X-CSRF-Token": citizen["csrf_token"]}
        self.assertEqual(self.client.post(assignment_path, json={"department": "Road Infrastructure"}, headers=citizen_headers).status_code, 403)
        self.assertEqual(self.client.get("/admin/officials").status_code, 403)
        admin = self.admin()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        unverified_id = ObjectId()
        verified_id = ObjectId()
        self.database["users"].insert_one({"_id": unverified_id, "email": "unverified@example.test", "role": "official",
                                            "status": "active", "department": "Road Infrastructure"})
        self.database["users"].insert_one({"_id": verified_id, "email": "verified@example.test", "full_name": "Verified Official",
                                            "role": "official", "status": "active", "department": "Road Infrastructure",
                                            "official_verified_at": datetime.now(timezone.utc), "official_verified_by": ObjectId()})
        denied = self.client.post(assignment_path, json={"department": "Road Infrastructure", "official_id": str(unverified_id)}, headers=headers)
        self.assertEqual(denied.status_code, 400)
        listed = self.client.get("/admin/officials").get_json()
        self.assertEqual([item["id"] for item in listed], [str(verified_id)])

    def test_legacy_demo_records_remain_readable_unmodified_and_read_only(self):
        admin = self.admin()
        legacy_id = ObjectId()
        original = {"_id": legacy_id, "description": "Old sample pothole", "category": "pothole",
                    "priority": "low", "status": "open", "location": {"coordinates": [77.6, 12.9]},
                    "legacy_marker": "retain exactly"}
        self.database["complaints"].insert_one(original)
        row = self.client.get(f"/complaints/{legacy_id}")
        self.assertEqual(row.status_code, 200)
        self.assertEqual(row.get_json()["data_quality"], "demo_sample_unverified")
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        self.assertEqual(self.client.post(f"/complaints/{legacy_id}/assign", json={"department": "Road Infrastructure"}, headers=headers).status_code, 409)
        self.assertEqual(self.client.post(f"/complaints/{legacy_id}/transition", json={"status": "triaged"}, headers=headers).status_code, 409)
        self.assertEqual(self.database["complaints"].find_one({"_id": legacy_id}), original)

    def test_verified_official_department_scope_and_resolution_evidence(self):
        self.register()
        report = self.create_report()
        admin = self.admin()
        official_id = ObjectId()
        outsider_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "off@example.test", "role": "official",
                                            "status": "active", "department": "Road Infrastructure", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        self.database["users"].insert_one({"_id": outsider_id, "email": "other@example.test", "role": "official",
                                            "status": "active", "department": "Water Supply", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        self.client.post(f"/complaints/{report['_id']}/assign", json={"department": "Road Infrastructure", "official_id": str(official_id), "reason": "Lifecycle test route."},
                         headers={"X-CSRF-Token": admin["csrf_token"]})
        def login_as(email):
            client = self.app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = email
            # Session IDs are Mongo IDs, so set the matching valid ID below.
            return client
        def official_client(oid):
            client = self.app.test_client()
            with client.session_transaction() as session:
                session["user_id"] = str(oid)
                session["csrf_token"] = "test-token"
            return client
        off = official_client(official_id)
        headers = {"X-CSRF-Token": "test-token"}
        self.assertEqual(off.get(f"/complaints/{report['_id']}").status_code, 200)
        outsider = official_client(outsider_id)
        self.assertEqual(outsider.get(f"/complaints/{report['_id']}").status_code, 404)
        self.assertEqual(outsider.post(f"/complaints/{report['_id']}/transition", json={"status": "in_progress"},
                                       headers=headers).status_code, 404)
        no_evidence = off.post(f"/complaints/{report['_id']}/transition", json={"status": "in_progress"}, headers=headers)
        self.assertEqual(no_evidence.status_code, 200)
        missing_resolution = off.post(f"/complaints/{report['_id']}/transition", json={"status": "resolution_submitted", "notes": "Fixed"}, headers=headers)
        self.assertEqual(missing_resolution.status_code, 400)
        resolved = off.post(f"/complaints/{report['_id']}/transition", json={"status": "resolution_submitted",
                                                                             "notes": "Drain cleared",
                                                                             "evidence": ["https://evidence.example/photo"]},
                            headers=headers)
        self.assertEqual(resolved.status_code, 200, resolved.get_json())
        official_view = resolved.get_json()
        self.assertNotIn("created_by", official_view)
        self.assertNotIn("assigned_official_id", official_view)
        self.assertTrue(official_view["assigned_to_viewer"])
        self.assertNotIn("actor_id", official_view["status_history"][-1])
        self.assertEqual(official_view["status_history"][-1]["actor_role"], "official")
        self.assertTrue(official_view["status_history"][-1]["created_at"])
        private_assignment_keys = {"official_id", "previous_official_id", "administrator_id"}
        self.assertTrue(all(not (private_assignment_keys & set(entry)) for entry in official_view["assignment_history"]))
        admin_client = self.client
        finalized = admin_client.post(f"/complaints/{report['_id']}/transition", json={"status": "resolved",
                                                                                       "notes": "Reviewed evidence",
                                                                                       "evidence": ["inspection ref"]},
                                      headers={"X-CSRF-Token": admin["csrf_token"]})
        self.assertEqual(finalized.status_code, 200, finalized.get_json())
        self.assertEqual(finalized.get_json()["status"], "resolved")
        self.assertIn("actor_id", finalized.get_json()["status_history"][-1])

    def test_admin_transitions_citizen_dispute_and_reopen_are_controlled(self):
        citizen = self.register()
        report = self.create_report()
        admin = self.admin()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        path = f"/complaints/{report['_id']}/transition"
        for target in ("triaged",):
            response = self.client.post(path, json={"status": target}, headers=headers)
            self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.client.post(path, json={"status": "assigned"}, headers=headers).status_code, 409)
        self.assertEqual(self.client.post(path, json={"status": "resolved", "notes": "done", "evidence": ["ref"]}, headers=headers).status_code, 409)
        # Admin must progress through assignment and official work before resolving.
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "off@example.test", "role": "official",
                                            "status": "active", "department": "Road Infrastructure", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        self.client.post(f"/complaints/{report['_id']}/assign", json={"department": "Road Infrastructure", "official_id": str(official_id), "reason": "Lifecycle fixture assignment."}, headers=headers)
        off = self.app.test_client()
        with off.session_transaction() as session:
            session["user_id"] = str(official_id)
            session["csrf_token"] = "off-token"
        off.post(path, json={"status": "in_progress"}, headers={"X-CSRF-Token": "off-token"})
        off.post(path, json={"status": "resolution_submitted", "notes": "Done", "evidence": ["photo ref"]},
                 headers={"X-CSRF-Token": "off-token"})
        done = self.client.post(path, json={"status": "resolved", "notes": "Checked", "evidence": ["review ref"]}, headers=headers)
        self.assertEqual(done.status_code, 200, done.get_json())
        self.assertEqual(done.get_json()["status_history"][-1]["action"], "resolution_approved")
        # Citizen account remains owner after admin changes session to perform the final dispute.
        citizen_client = self.app.test_client()
        with citizen_client.session_transaction() as session:
            session["user_id"] = citizen["user"]["id"]
            session["csrf_token"] = "citizen-token"
        disputed = citizen_client.post(path, json={"status": "reopening_requested", "notes": "Still blocked"},
                                      headers={"X-CSRF-Token": "citizen-token"})
        self.assertEqual(disputed.status_code, 200, disputed.get_json())
        disputed_view = disputed.get_json()
        self.assertEqual(disputed_view["status_history"][-1]["action"], "resolution_disputed")
        self.assertNotIn("created_by", disputed_view)
        self.assertTrue(all("actor_id" not in event for event in disputed_view["status_history"]))
        self.assertTrue(all(not ({"official_id", "previous_official_id", "administrator_id"} & set(item))
                            for item in disputed_view["assignment_history"]))
        reopened = self.client.post(path, json={"status": "in_progress"}, headers=headers)
        self.assertEqual(reopened.status_code, 200, reopened.get_json())
        history = reopened.get_json()["status_history"]
        self.assertTrue(all("actor_id" in row and "actor_role" in row and "action" in row and "created_at" in row for row in history))

    def test_transition_policy_matrix_includes_all_permitted_and_forbidden_edges(self):
        from backend.app import _transition_error
        allowed = {
            "admin": {"submitted": {"triaged"}, "open": {"triaged"},
                      "resolution_submitted": {"resolved", "in_progress"},
                      "resolved": {"in_progress"}, "reopening_requested": {"in_progress", "resolved"},
                      "disputed": {"in_progress", "resolved"}},
            "official": {"assigned": {"in_progress"}, "in_progress": {"resolution_submitted"}},
            "citizen": {"resolved": {"reopening_requested", "disputed"}},
        }
        statuses = {"submitted", "open", "triaged", "assigned", "in_progress", "resolution_submitted",
                    "resolved", "reopening_requested", "disputed"}
        targets = statuses | {"closed", "deleted"}
        for role in ("citizen", "official", "admin"):
            for current in statuses:
                for target in targets:
                    expected = target in allowed.get(role, {}).get(current, set())
                    self.assertEqual(_transition_error(role, current, target) is None, expected,
                                     (role, current, target))

    def test_official_department_scope_allows_department_work_without_personal_assignment(self):
        citizen = self.register()
        report = self.create_report()
        admin = self.admin()
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "off@example.test", "role": "official",
                                            "status": "active", "department": "Road Infrastructure", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        self.client.post(f"/complaints/{report['_id']}/assign", json={"department": "Road Infrastructure", "reason": "Department scope test route."},
                         headers={"X-CSRF-Token": admin["csrf_token"]})
        official = self.app.test_client()
        with official.session_transaction() as session:
            session["user_id"] = str(official_id)
            session["csrf_token"] = "department-token"
        self.assertEqual(official.get(f"/complaints/{report['_id']}").status_code, 200)
        self.assertEqual(official.get("/complaints").get_json()[0]["_id"], report["_id"])
        changed = official.post(f"/complaints/{report['_id']}/transition", json={"status": "in_progress"},
                                headers={"X-CSRF-Token": "department-token"})
        self.assertEqual(changed.status_code, 200, changed.get_json())

    def test_resolution_dispute_requirements_and_non_deletion(self):
        citizen = self.register()
        report = self.create_report()
        admin = self.admin()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        path = f"/complaints/{report['_id']}/transition"
        self.client.post(path, json={"status": "triaged"}, headers=headers)
        self.client.post(path, json={"status": "assigned"}, headers=headers)
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "off@example.test", "role": "official",
                                            "status": "active", "department": "Road Infrastructure", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        self.client.post(f"/complaints/{report['_id']}/assign", json={"department": "Road Infrastructure", "official_id": str(official_id), "reason": "Workflow test route."}, headers=headers)
        off = self.app.test_client()
        with off.session_transaction() as session:
            session["user_id"] = str(official_id); session["csrf_token"] = "off-token"
        off.post(path, json={"status": "in_progress"}, headers={"X-CSRF-Token": "off-token"})
        off.post(path, json={"status": "resolution_submitted", "notes": "Cleared", "evidence": ["photo ref"]},
                 headers={"X-CSRF-Token": "off-token"})
        missing_evidence = self.client.post(path, json={"status": "resolved", "notes": "Reviewed"}, headers=headers)
        self.assertEqual(missing_evidence.status_code, 400)
        self.client.post(path, json={"status": "resolved", "notes": "Reviewed", "evidence": ["review ref"]}, headers=headers)
        citizen_client = self.app.test_client()
        with citizen_client.session_transaction() as session:
            session["user_id"] = citizen["user"]["id"]; session["csrf_token"] = "citizen-token"
        missing_note = citizen_client.post(path, json={"status": "disputed"}, headers={"X-CSRF-Token": "citizen-token"})
        self.assertEqual(missing_note.status_code, 400)
        dispute = citizen_client.post(path, json={"status": "disputed", "notes": "Still broken"},
                                      headers={"X-CSRF-Token": "citizen-token"})
        self.assertEqual(dispute.status_code, 200, dispute.get_json())
        delete = self.client.delete(f"/complaints/{report['_id']}", headers=headers)
        self.assertEqual(delete.status_code, 405)
        self.assertIsNotNone(self.database["complaints"].find_one({"_id": ObjectId(report["_id"])}))


class ComplaintEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.database = Database()
        self.app = create_app(database=self.database, test_config={"TESTING": True, "SECRET_KEY": "evidence-test-secret",
                                                                   "EVIDENCE_DIR": Path(self.tempdir.name)})
        self.client = self.app.test_client()
        token = self.client.get("/auth/csrf").get_json()["csrf_token"]
        registered = self.client.post("/auth/register", json={"full_name": "Image Citizen", "email": "image@example.test",
                                                                "password": "long-enough-password"},
                                      headers={"X-CSRF-Token": token})
        self.assertEqual(registered.status_code, 201, registered.get_json())
        self.citizen = registered.get_json()

    def tearDown(self):
        self.tempdir.cleanup()

    @staticmethod
    def png_bytes():
        buffer = io.BytesIO()
        Image.new("RGB", (8, 6), (127, 93, 55)).save(buffer, format="PNG")
        return buffer.getvalue()

    def form_data(self, image_bytes, filename="street-photo.png"):
        return {"description": "A cracked footpath beside the library", "category": "damaged_infrastructure",
                "lat": "12.9", "lng": "77.6", "image": (io.BytesIO(image_bytes), filename)}

    def post_image(self, image_bytes, filename="street-photo.png"):
        form = self.form_data(image_bytes, filename)
        stream = form["image"][0]
        try:
            return self.client.post("/complaints", data=form,
                                    headers={"X-CSRF-Token": self.citizen["csrf_token"]})
        finally:
            stream.close()

    def test_invalid_image_is_rejected_without_creating_record_or_file(self):
        response = self.post_image(b"not an image")
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertEqual(self.database["complaints"].rows, [])
        self.assertEqual(list(Path(self.tempdir.name).glob("*")), [])

    def test_report_requires_description_and_location_and_rejects_invalid_category(self):
        token = self.citizen["csrf_token"]
        for payload in (
            {"category": "pothole", "lat": 12.9, "lng": 77.6},
            {"description": "A damaged sidewalk", "category": "damaged_infrastructure"},
        ):
            response = self.client.post("/complaints", json=payload, headers={"X-CSRF-Token": token})
            self.assertEqual(response.status_code, 400)
        invalid = self.client.post("/complaints", json={"description": "A damaged sidewalk", "lat": 12.9,
                                                         "lng": 77.6, "category": "definitely-not-a-category"},
                                   headers={"X-CSRF-Token": token})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.database["complaints"].rows, [])

    def test_unsupported_image_format_is_rejected(self):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 6)).save(buffer, format="GIF")
        response = self.post_image(buffer.getvalue(), "animated.gif")
        self.assertEqual(response.status_code, 415, response.get_json())
        self.assertEqual(self.database["complaints"].rows, [])

    def test_oversized_image_is_rejected_without_storage(self):
        from backend.evidence import MAX_EVIDENCE_BYTES
        response = self.post_image(b"x" * (MAX_EVIDENCE_BYTES + 1))
        self.assertEqual(response.status_code, 413, response.get_json())
        self.assertEqual(self.database["complaints"].rows, [])
        self.assertEqual(list(Path(self.tempdir.name).glob("*")), [])

    def test_image_is_stored_with_generated_metadata_and_complaint_starts_submitted(self):
        response = self.post_image(self.png_bytes(), "../../private name.png")
        self.assertEqual(response.status_code, 201, response.get_json())
        result = response.get_json()
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["category"], "damaged_infrastructure")
        self.assertNotIn("created_by", result)
        self.assertTrue(all("actor_id" not in event for event in result["status_history"]))
        self.assertEqual(len(result["images"]), 1)
        self.assertNotIn("storage_key", result["images"][0])
        self.assertEqual(result["images"][0]["byte_size"], len(self.png_bytes()))
        self.assertTrue(result["images"][0]["sha256"])
        self.assertNotIn("storage_key", result["images"][0])
        saved = self.database["complaints"].find_one({"_id": ObjectId(result["_id"])})["images"][0]
        path = Path(self.tempdir.name) / saved["storage_key"]
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), self.png_bytes())
        self.assertNotIn("private name", path.name)
        self.assertNotIn("storage_key", result["images"][0])

    def test_evidence_download_checks_owner_and_allows_admin_or_assigned_department(self):
        created = self.post_image(self.png_bytes()).get_json()
        evidence = created["images"][0]
        path = evidence["url"]
        other = self.app.test_client()
        csrf = other.get("/auth/csrf").get_json()["csrf_token"]
        other.post("/auth/register", json={"full_name": "Other Citizen", "email": "other-image@example.test",
                                           "password": "another-long-password"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(other.get(path).status_code, 404)
        create_first_admin(self.database, "admin-image@example.test", "admin-long-password")
        admin = self.app.test_client()
        csrf = admin.get("/auth/csrf").get_json()["csrf_token"]
        login = admin.post("/auth/login", json={"email": "admin-image@example.test", "password": "admin-long-password"},
                           headers={"X-CSRF-Token": csrf}).get_json()
        admin_download = admin.get(path)
        self.assertEqual(admin_download.status_code, 200)
        admin_download.close()
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "roads@example.test", "role": "official",
                                            "status": "active", "department": "Road Infrastructure", "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        assigned = admin.post(f"/complaints/{created['_id']}/assign", json={"department": "Road Infrastructure", "official_id": str(official_id), "reason": "Evidence access test route."},
                              headers={"X-CSRF-Token": login["csrf_token"]})
        self.assertEqual(assigned.status_code, 200, assigned.get_json())
        official = self.app.test_client()
        with official.session_transaction() as session:
            session["user_id"] = str(official_id)
            session["csrf_token"] = "official-image-token"
        official_download = official.get(path)
        self.assertEqual(official_download.status_code, 200)
        official_download.close()


class DepartmentRoutingTests(unittest.TestCase):
    def setUp(self):
        self.database = Database()
        self.app = create_app(database=self.database, test_config={"TESTING": True, "SECRET_KEY": "routing-test-secret"})
        self.client = self.app.test_client()

    def post(self, path, payload, token=None):
        token = token or self.client.get("/auth/csrf").get_json()["csrf_token"]
        return self.client.post(path, json=payload, headers={"X-CSRF-Token": token})

    def admin(self):
        create_first_admin(self.database, "routing-admin@example.test", "routing-admin-password")
        response = self.post("/auth/login", {"email": "routing-admin@example.test", "password": "routing-admin-password"})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def citizen(self, email="routing-citizen@example.test"):
        response = self.post("/auth/register", {"full_name": "Routing Test Citizen", "email": email,
                                                "password": "routing-citizen-password"})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def report(self, category):
        token = self.client.get("/auth/csrf").get_json()["csrf_token"]
        with patch("backend.app.find_duplicates", return_value=[]):
            return self.client.post("/complaints", json={"description": f"Phase 5 test report for {category}",
                                                           "category": category, "lat": 12.9, "lng": 77.6},
                                    headers={"X-CSRF-Token": token})

    def test_registry_create_edit_activate_deactivate_and_duplicate_protection(self):
        citizen = self.citizen()
        self.assertEqual(self.client.get("/admin/departments").status_code, 403)
        self.assertEqual(self.post("/admin/departments", {"department_id": "unique-dept", "name": "Unique Dept"},
                                   citizen["csrf_token"]).status_code, 403)
        admin = self.admin()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        rows = self.client.get("/admin/departments").get_json()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row["prototype"] for row in rows))
        created = self.client.post("/admin/departments", json={"department_id": "special-routing",
            "name": "Special Routing", "description": "Test registry row", "categories": ["unclassified"]}, headers=headers)
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertEqual(self.client.post("/admin/departments", json={"department_id": "special-routing",
            "name": "Second Name"}, headers=headers).status_code, 409)
        self.assertEqual(self.client.post("/admin/departments", json={"department_id": "other-id",
            "name": "Special Routing"}, headers=headers).status_code, 409)
        updated = self.client.patch("/admin/departments/special-routing", json={"name": "Special Services",
            "description": "Updated test registry row", "active": False}, headers=headers)
        self.assertEqual(updated.status_code, 200, updated.get_json())
        self.assertFalse(updated.get_json()["active"])
        self.assertEqual(self.client.patch("/admin/departments/special-routing",
            json={"department_id": "renamed-id"}, headers=headers).status_code, 400)
        reactivated = self.client.patch("/admin/departments/special-routing", json={"active": True}, headers=headers)
        self.assertEqual(reactivated.status_code, 200)
        collision = self.client.post("/admin/departments", json={"department_id": "extra-waste",
            "name": "Extra Waste", "categories": ["garbage"]}, headers=headers)
        self.assertEqual(collision.status_code, 409)

    def test_category_mapping_suggestions_unmapped_review_and_no_implicit_assignment(self):
        citizen = self.citizen()
        mapped = self.report("drainage")
        self.assertEqual(mapped.status_code, 201, mapped.get_json())
        report = mapped.get_json()
        self.assertEqual(report["suggested_department_id"], "stormwater-drainage")
        self.assertEqual(report["suggested_department_name"], "Stormwater Drainage")
        self.assertIsNone(report.get("department"))
        self.assertEqual(report["status"], "submitted")
        self.assertTrue(report["awaiting_department_review"])
        self.assertFalse(report["routing_review_required"])
        self.assertEqual(report["assignment_history"], [])
        unmapped = self.report("unclassified").get_json()
        self.assertIsNone(unmapped["suggested_department_id"])
        self.assertTrue(unmapped["routing_review_required"])
        admin = self.admin()
        rows = self.client.get("/admin/complaints/unmapped").get_json()
        self.assertEqual([row["_id"] for row in rows], [unmapped["_id"]])
        self.assertEqual(self.client.get("/admin/complaints/unmapped").status_code, 200)
        self.assertEqual(self.client.get(f"/complaints/{report['_id']}").get_json()["status"], "submitted")

    def test_admin_assignment_reassignment_inactive_department_and_append_only_history(self):
        citizen = self.citizen()
        report = self.report("drainage").get_json()
        token = citizen["csrf_token"]
        path = f"/complaints/{report['_id']}/assign"
        self.assertEqual(self.post(path, {"department_id": "stormwater-drainage"}, token).status_code, 403)
        admin = self.admin()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        first = self.client.post(path, json={"department_id": "stormwater-drainage"}, headers=headers)
        self.assertEqual(first.status_code, 200, first.get_json())
        assigned = first.get_json()
        self.assertEqual(assigned["status"], "assigned")
        self.assertEqual(assigned["department_id"], "stormwater-drainage")
        self.assertEqual(len(assigned["assignment_history"]), 1)
        entry = assigned["assignment_history"][0]
        self.assertEqual(entry["previous_department"], None)
        self.assertEqual(entry["administrator_id"], admin["user"]["id"])
        self.assertTrue(entry["timestamp"])
        self.assertEqual(entry["suggested_department_id"], "stormwater-drainage")
        self.assertEqual(assigned["status_history"][-1]["action"], "assigned")
        missing_reason = self.client.post(path, json={"department_id": "road-infrastructure"}, headers=headers)
        self.assertEqual(missing_reason.status_code, 400)
        reassigned = self.client.post(path, json={"department_id": "road-infrastructure",
            "reason": "Reviewed category and selected the road team."}, headers=headers)
        self.assertEqual(reassigned.status_code, 200, reassigned.get_json())
        history = reassigned.get_json()["assignment_history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]["previous_department"], "Stormwater Drainage")
        self.assertEqual(history[1]["department"], "Road Infrastructure")
        self.assertEqual(history[1]["reason"], "Reviewed category and selected the road team.")
        inactive = self.client.patch("/admin/departments/water-supply", json={"active": False}, headers=headers)
        self.assertEqual(inactive.status_code, 200)
        denied = self.client.post(path, json={"department_id": "water-supply", "reason": "test"}, headers=headers)
        self.assertEqual(denied.status_code, 400)
        preserved = self.database["complaints"].find_one({"_id": ObjectId(report["_id"])})
        self.assertEqual(preserved["department_id"], "road-infrastructure")
        self.assertEqual(len(preserved["assignment_history"]), 2)

    def test_unmapped_category_requires_reason_and_legacy_records_remain_untouched(self):
        self.citizen()
        report = self.report("unclassified").get_json()
        admin = self.admin()
        headers = {"X-CSRF-Token": admin["csrf_token"]}
        path = f"/complaints/{report['_id']}/assign"
        self.assertEqual(self.client.post(path, json={"department_id": "general-infrastructure"}, headers=headers).status_code, 400)
        routed = self.client.post(path, json={"department_id": "general-infrastructure", "reason": "Manual review of unmapped category."}, headers=headers)
        self.assertEqual(routed.status_code, 200, routed.get_json())
        self.assertTrue(routed.get_json()["routing_review_required"])
        legacy_id = ObjectId()
        legacy = {"_id": legacy_id, "description": "Legacy demonstration sample", "category": "pothole",
                  "status": "open", "legacy_marker": "unchanged"}
        self.database["complaints"].insert_one(legacy)
        self.assertEqual(self.client.post(f"/complaints/{legacy_id}/assign", json={"department_id": "road-infrastructure"},
                                          headers=headers).status_code, 409)
        self.assertEqual(self.database["complaints"].find_one({"_id": legacy_id}), legacy)

    def test_department_id_scope_and_existing_individual_official_assignment_are_preserved(self):
        citizen = self.citizen()
        report = self.report("pothole").get_json()
        admin = self.admin()
        admin_headers = {"X-CSRF-Token": admin["csrf_token"]}
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "dept-official@example.test",
            "role": "official", "status": "active", "department": "Road Infrastructure",
            "department_id": "road-infrastructure", "official_verified_at": datetime.now(timezone.utc),
            "official_verified_by": ObjectId()})
        path = f"/complaints/{report['_id']}/assign"
        assigned = self.client.post(path, json={"department_id": "road-infrastructure", "official_id": str(official_id)},
                                    headers=admin_headers)
        self.assertEqual(assigned.status_code, 200, assigned.get_json())
        admin_view = assigned.get_json()
        self.assertEqual(admin_view["created_by"], citizen["user"]["id"])
        self.assertEqual(admin_view["assignment_history"][-1]["administrator_id"], admin["user"]["id"])
        self.assertEqual(admin_view["status_history"][-1]["actor_id"], admin["user"]["id"])
        citizen_client = self.app.test_client()
        with citizen_client.session_transaction() as session:
            session["user_id"] = citizen["user"]["id"]
            session["csrf_token"] = "citizen-routing-token"
        citizen_view_response = citizen_client.get(path.replace("/assign", ""))
        self.assertEqual(citizen_view_response.status_code, 200, citizen_view_response.get_json())
        citizen_view = citizen_view_response.get_json()
        self.assertNotIn("created_by", citizen_view)
        self.assertNotIn("assigned_official_id", citizen_view)
        self.assertTrue(all("actor_id" not in event for event in citizen_view["status_history"]))
        self.assertTrue(all(not ({"official_id", "previous_official_id", "administrator_id"} & set(entry))
                            for entry in citizen_view["assignment_history"]))
        official = self.app.test_client()
        with official.session_transaction() as session:
            session["user_id"] = str(official_id)
            session["csrf_token"] = "department-id-token"
        visible = official.get(f"/complaints/{report['_id']}")
        self.assertEqual(visible.status_code, 200)
        official_view = visible.get_json()
        self.assertTrue(official_view["assigned_to_viewer"])
        self.assertNotIn("created_by", official_view)
        self.assertNotIn("assigned_official_id", official_view)
        self.assertTrue(all("actor_id" not in event for event in official_view["status_history"]))
        self.assertTrue(all(not ({"official_id", "previous_official_id", "administrator_id"} & set(entry))
                            for entry in official_view["assignment_history"]))
        unrelated_id = ObjectId()
        self.database["complaints"].insert_one({"_id": unrelated_id, "created_by": ObjectId(), "category": "garbage",
            "department": "Solid Waste Management", "department_id": "solid-waste-management", "status": "assigned"})
        self.assertEqual(official.get(f"/complaints/{unrelated_id}").status_code, 404)


class AdminPortalApiTests(unittest.TestCase):
    def setUp(self):
        self.database = Database()
        self.app = create_app(database=self.database, test_config={"TESTING": True, "SECRET_KEY": "admin-test-secret"})
        self.client = self.app.test_client()

    def post(self, path, payload, token=None):
        token = token or self.client.get("/auth/csrf").get_json()["csrf_token"]
        return self.client.post(path, json=payload, headers={"X-CSRF-Token": token})

    def test_official_access_rejection_requires_and_records_reason(self):
        applicant = self.post("/auth/register", {"full_name": "Pending Applicant", "email": "pending-applicant@example.test",
                                                  "password": "pending-applicant-password"})
        self.assertEqual(applicant.status_code, 201)
        request_response = self.post("/auth/official-access-requests", {
            "employee_id": "TEST-ONLY", "department": "Road Infrastructure", "designation": "Test Applicant",
            "verification_information": "Test-only request; no real person or verification."},
            applicant.get_json()["csrf_token"])
        self.assertEqual(request_response.status_code, 201)
        request_id = request_response.get_json()["request"]["id"]
        create_first_admin(self.database, "reject-admin@example.test", "reject-admin-password")
        admin_login = self.post("/auth/login", {"email": "reject-admin@example.test", "password": "reject-admin-password"})
        self.assertEqual(admin_login.status_code, 200)
        path = f"/admin/official-access-requests/{request_id}/decision"
        missing = self.post(path, {"decision": "reject"}, admin_login.get_json()["csrf_token"])
        self.assertEqual(missing.status_code, 400)
        rejected = self.post(path, {"decision": "reject", "notes": "Could not verify the submitted affiliation."},
                             admin_login.get_json()["csrf_token"])
        self.assertEqual(rejected.status_code, 200, rejected.get_json())
        row = self.database["official_access_requests"].find_one({"_id": ObjectId(request_id)})
        self.assertEqual(row["status"], "rejected")
        self.assertEqual(row["decision_notes"], "Could not verify the submitted affiliation.")
        self.assertEqual(self.database["users"].find_one({"email": "pending-applicant@example.test"})["role"], "citizen")

    def test_admin_overview_is_private_and_reports_status_and_department_workload(self):
        self.database["departments"].insert_one({"department_id": "road-infrastructure",
                                                 "name": "Road Infrastructure", "active": True})
        self.database["departments"].insert_one({"department_id": "water-supply",
                                                 "name": "Water Supply", "active": True})
        complaint_rows = [
            {"status": "submitted", "department_id": "road-infrastructure", "department": "Road Infrastructure"},
            {"status": "assigned", "department_id": "road-infrastructure", "department": "Road Infrastructure"},
            {"status": "in_progress", "department_id": "water-supply", "department": "Water Supply"},
            {"status": "resolution_submitted", "department_id": "road-infrastructure", "department": "Road Infrastructure"},
            {"status": "resolved"},
            {"status": "open", "data_quality": "demo_sample_unverified"},
        ]
        for row in complaint_rows:
            self.database["complaints"].insert_one({"_id": ObjectId(), **row})
        for status in ("pending", "pending", "approved"):
            self.database["official_access_requests"].insert_one({"status": status})

        citizen = self.post("/auth/register", {"full_name": "Portal Citizen", "email": "portal-citizen@example.test",
                                                "password": "portal-citizen-password"})
        self.assertEqual(citizen.status_code, 201)
        self.assertEqual(self.client.get("/admin/overview").status_code, 403)

        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "portal-official@example.test",
                                            "role": "official", "status": "active",
                                            "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        official_client = self.app.test_client()
        with official_client.session_transaction() as session:
            session["user_id"] = str(official_id)
            session["csrf_token"] = "official-token"
        self.assertEqual(official_client.get("/admin/overview").status_code, 403)

        create_first_admin(self.database, "portal-admin@example.test", "portal-admin-password")
        login = self.post("/auth/login", {"email": "portal-admin@example.test", "password": "portal-admin-password"})
        self.assertEqual(login.status_code, 200)
        response = self.client.get("/admin/overview")
        self.assertEqual(response.status_code, 200, response.get_json())
        overview = response.get_json()
        self.assertEqual(overview["total_complaints"], 6)
        self.assertEqual(overview["status_counts"], {"submitted": 1, "assigned": 1, "in_progress": 1,
                                                      "resolution_submitted": 1, "resolved": 1})
        self.assertEqual(overview["pending_official_requests"], 2)
        self.assertEqual(overview["resolutions_awaiting_review"], 1)
        workload = {row["department"]: row for row in overview["department_workload"]}
        self.assertEqual(workload["Road Infrastructure"]["total"], 3)
        self.assertEqual(workload["Road Infrastructure"]["resolution_submitted"], 1)
        self.assertEqual(workload["Water Supply"]["in_progress"], 1)
        self.assertEqual(workload["Unassigned"]["total"], 2)
        self.assertIn("demonstration/sample", overview["data_notice"])

    def test_admin_rejection_of_submitted_resolution_requires_reason_and_is_recorded(self):
        citizen = self.post("/auth/register", {"full_name": "Lifecycle Citizen", "email": "lifecycle-citizen@example.test",
                                                "password": "lifecycle-citizen-password"})
        self.assertEqual(citizen.status_code, 201)
        report = self.client.post("/complaints", json={"description": "A drainage issue for admin review",
                                                        "category": "drainage", "lat": 12.9, "lng": 77.6},
                                  headers={"X-CSRF-Token": citizen.get_json()["csrf_token"]})
        self.assertEqual(report.status_code, 201, report.get_json())
        create_first_admin(self.database, "review-admin@example.test", "review-admin-password")
        admin_login = self.post("/auth/login", {"email": "review-admin@example.test", "password": "review-admin-password"})
        self.assertEqual(admin_login.status_code, 200)
        official_id = ObjectId()
        self.database["users"].insert_one({"_id": official_id, "email": "review-official@example.test",
                                            "role": "official", "status": "active",
                                            "department": "Stormwater Drainage", "department_id": "stormwater-drainage",
                                            "official_verified_at": datetime.now(timezone.utc),
                                            "official_verified_by": ObjectId()})
        admin_headers = {"X-CSRF-Token": admin_login.get_json()["csrf_token"]}
        assign = self.client.post(f"/complaints/{report.get_json()['_id']}/assign",
                                  json={"department_id": "stormwater-drainage", "official_id": str(official_id),
                                        "reason": "Test-only assignment."}, headers=admin_headers)
        self.assertEqual(assign.status_code, 200, assign.get_json())
        official_client = self.app.test_client()
        with official_client.session_transaction() as session:
            session["user_id"] = str(official_id)
            session["csrf_token"] = "review-official-token"
        path = f"/complaints/{report.get_json()['_id']}/transition"
        self.assertEqual(official_client.post(path, json={"status": "in_progress"},
                                               headers={"X-CSRF-Token": "review-official-token"}).status_code, 200)
        submitted = official_client.post(path, json={"status": "resolution_submitted", "notes": "Work completed",
                                                      "evidence": ["evidence-reference"]},
                                         headers={"X-CSRF-Token": "review-official-token"})
        self.assertEqual(submitted.status_code, 200)
        missing_reason = self.client.post(path, json={"status": "in_progress"}, headers=admin_headers)
        self.assertEqual(missing_reason.status_code, 400)
        self.assertIn("reason is required", missing_reason.get_json()["error"])
        self.assertEqual(self.database["complaints"].find_one({"_id": ObjectId(report.get_json()["_id"])})["status"],
                         "resolution_submitted")
        rejected = self.client.post(path, json={"status": "in_progress", "notes": "Evidence is insufficient; please resubmit."},
                                    headers=admin_headers)
        self.assertEqual(rejected.status_code, 200, rejected.get_json())
        event = rejected.get_json()["status_history"][-1]
        self.assertEqual(rejected.get_json()["status"], "in_progress")
        self.assertEqual(event["action"], "resolution_rejected")
        self.assertEqual(event["actor_role"], "admin")
        self.assertEqual(event["note"], "Evidence is insufficient; please resubmit.")


class GeographicCoordinateSafetyTests(unittest.TestCase):
    def test_stored_geojson_point_validation(self):
        self.assertEqual(_valid_geojson_point({"type": "Point", "coordinates": [77.6, 12.9]}),
                         (77.6, 12.9))
        # Historical location documents without an explicit type remain
        # eligible when the coordinate pair itself is valid.
        self.assertEqual(_valid_geojson_point({"coordinates": [77.6, 12.9]}), (77.6, 12.9))
        invalid_locations = [
            None, [], "location", {}, {"type": "Point"},
            {"type": "Point", "coordinates": None},
            {"type": "Point", "coordinates": "77.6,12.9"},
            {"type": "Point", "coordinates": {"lng": 77.6, "lat": 12.9}},
            {"type": "Point", "coordinates": [77.6]},
            {"type": "Point", "coordinates": [77.6, 12.9, 4]},
            {"type": "Point", "coordinates": ["77.6", 12.9]},
            {"type": "Point", "coordinates": [object(), 12.9]},
            {"type": "Point", "coordinates": [True, 12.9]},
            {"type": "Point", "coordinates": [float("nan"), 12.9]},
            {"type": "Point", "coordinates": [77.6, float("inf")]},
            {"type": "Point", "coordinates": [181, 12.9]},
            {"type": "Point", "coordinates": [77.6, -91]},
            {"type": "LineString", "coordinates": [77.6, 12.9]},
        ]
        for location in invalid_locations:
            with self.subTest(location=location):
                self.assertIsNone(_valid_geojson_point(location))

    def test_submission_coordinate_validation_uses_same_axis_ranges(self):
        self.assertEqual(_valid_coordinates({"lat": "12.9", "lng": "77.6"}), (12.9, 77.6))
        self.assertIsNone(_valid_coordinates({"lat": "91", "lng": "77.6"}))
        self.assertIsNone(_valid_coordinates({"lat": float("nan"), "lng": 77.6}))

    def test_hotspots_skip_malformed_records_and_coarsen_public_center(self):
        database = Database()
        complaints = database["complaints"]
        # Deliberately already at the output rounding precision to exercise
        # the final collision guard as well as center coarsening.
        exact = [77.612, 12.935]
        for index in range(5):
            complaints.insert_one({
                "status": "assigned", "category": "pothole", "priority": "high",
                "location": {"type": "Point", "coordinates": exact},
                "created_by": ObjectId(), "assigned_official_id": ObjectId(),
                "images": [{"storage_key": "private-test-key"}],
            })
        complaints.insert_one({"status": "assigned", "location": {"coordinates": [float("nan"), 12.9]}})
        complaints.insert_one({"status": "assigned", "location": None})

        hotspots = _hotspot_data(complaints)
        self.assertEqual(len(hotspots), 1)
        self.assertEqual(hotspots[0]["count"], 5)
        self.assertEqual(hotspots[0]["top_category"], "pothole")
        self.assertEqual(hotspots[0]["high_priority"], 5)
        self.assertEqual(hotspots[0]["center"], {"lat": 12.935, "lng": 77.611})
        self.assertNotEqual(hotspots[0]["center"], {"lat": exact[1], "lng": exact[0]})
        self.assertTrue(all(key not in hotspots[0] for key in
                            ("_id", "complaint_id", "created_by", "assigned_official_id", "images", "storage_key")))

    def test_empty_and_insufficient_valid_coordinates_return_no_hotspots(self):
        database = Database()
        self.assertEqual(_hotspot_data(database["complaints"]), [])
        for index in range(4):
            database["complaints"].insert_one({"status": "assigned", "location": {
                "type": "Point", "coordinates": [77.6 + index * 0.0001, 12.9]}})
        self.assertEqual(_hotspot_data(database["complaints"]), [])

    def test_public_endpoints_keep_total_count_when_location_is_invalid(self):
        database = Database()
        app = create_app(database=database, test_config={"TESTING": True, "SECRET_KEY": "geo-test-secret"})
        for index in range(5):
            database["complaints"].insert_one({"status": "assigned", "category": "garbage",
                "location": {"type": "Point", "coordinates": [77.6, 12.9]}})
        database["complaints"].insert_one({"status": "submitted", "location": {"coordinates": [999, 12]}})
        client = app.test_client()
        response = client.get("/hotspots")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["count"], 5)
        overview_response = client.get("/public/overview")
        self.assertEqual(overview_response.status_code, 200)
        overview = overview_response.get_json()
        self.assertEqual(overview["total"], 6)
        self.assertEqual(overview["hotspot_count"], 1)


if __name__ == "__main__":
    unittest.main()
