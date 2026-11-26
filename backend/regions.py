"""Versioned administrative region registry and read-only endpoints.

No region records or indexes are created by importing this module. Boundary
versions are intended to be append-only: a replacement is a new version and
an approved version is never edited in place.
"""
import math
import re
from datetime import datetime

from flask import Blueprint, current_app, jsonify

try:
    from .auth import roles_required
    from .geography import filter_complaints_to_region, hotspots_for_documents, region_overview_metrics
except ImportError:  # direct ``python backend/app.py`` execution
    from auth import roles_required
    from geography import filter_complaints_to_region, hotspots_for_documents, region_overview_metrics


regions_bp = Blueprint("regions", __name__)
REGION_TYPES = {"country", "state", "city", "ward"}
APPROVAL_STATUSES = {"draft", "approved", "rejected", "superseded"}
REDISTRIBUTION_STATES = {"cleared", "pending", "restricted"}
REGION_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")

# A template only; it is not inserted into MongoDB or returned as an approved
# region. The region type uses the current schema's ``city`` value to represent
# the metropolitan pilot; the source artifact, exact boundary and redistribution
# permission remain pending verification.
BENGALURU_PILOT_TEMPLATE = {
    "region_id": "in-ka-greater-bengaluru",
    "name": "Greater Bengaluru Area",
    "region_type": "city",
    "parent_region_id": "in-ka",
    "boundary": None,
    "boundary_version": "source-pending",
    "source": {
        "organization": "Government of Karnataka / Greater Bengaluru Authority",
        "title": "Official city-corporation delimitation maps (candidate source; not a GBA boundary artifact)",
        "url": "https://www.bbmp.gov.in/maps/",
    },
    "provenance": {
        "dataset_id": "",
        "acquired_at": None,
        "checksum_sha256": "",
        "notes": "No geometry acquired. The official portal lists five corporation maps; complete GBA coverage and source artifact provenance are not established.",
    },
    "license": {
        "name": "Not established",
        "url": "https://www.bbmp.gov.in/maps/",
        "redistribution_status": "pending",
    },
    "approval_status": "draft",
}

PARENT_TYPE = {"state": "country", "city": "state", "ward": "city"}


def _position_valid(position):
    if not isinstance(position, (list, tuple)) or len(position) not in {2, 3}:
        return False
    numbers = []
    for value in position:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        try:
            number = float(value)
        except (OverflowError, ValueError):
            return False
        if not math.isfinite(number):
            return False
        numbers.append(number)
    longitude, latitude = numbers[:2]
    return -180 <= longitude <= 180 and -90 <= latitude <= 90


def _ring_valid(ring):
    if not isinstance(ring, (list, tuple)) or len(ring) < 4:
        return False
    if not all(_position_valid(point) for point in ring):
        return False
    if list(ring[0]) != list(ring[-1]):
        return False
    vertices = [tuple(point[:2]) for point in ring[:-1]]
    if len(set(vertices)) < 3:
        return False
    area2 = sum(vertices[index][0] * vertices[(index + 1) % len(vertices)][1]
                - vertices[(index + 1) % len(vertices)][0] * vertices[index][1]
                for index in range(len(vertices)))
    return not math.isclose(area2, 0.0, abs_tol=1e-12)


def validate_boundary(geometry):
    """Return structural GeoJSON validation errors without external GIS deps.

    This validates RFC 7946 geometry shape, closed non-empty rings, non-zero
    area, and WGS84 coordinate ranges. Full topology (self intersections,
    hole containment, polygon overlaps) must be validated in an approved GIS
    import workflow before approval.
    """
    errors = []
    if not isinstance(geometry, dict) or not isinstance(geometry.get("type"), str) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        return ["boundary must be a GeoJSON Polygon or MultiPolygon."]
    if "crs" in geometry:
        errors.append("boundary must use RFC 7946 longitude/latitude coordinates and must not include a crs member.")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or not coordinates:
        return errors + ["boundary coordinates must be non-empty."]

    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    if geometry["type"] == "MultiPolygon" and not all(isinstance(polygon, (list, tuple)) and polygon for polygon in polygons):
        return errors + ["MultiPolygon must contain non-empty Polygon coordinate arrays."]
    for polygon_index, polygon in enumerate(polygons):
        if not isinstance(polygon, (list, tuple)) or not polygon:
            errors.append(f"Polygon {polygon_index} must contain an exterior ring.")
            continue
        for ring_index, ring in enumerate(polygon):
            if not _ring_valid(ring):
                errors.append(f"Polygon {polygon_index} ring {ring_index} is invalid or empty.")
    return errors


def validate_region_document(document, existing_versions=(), parent=None):
    """Return validation errors for one immutable region-version document."""
    if not isinstance(document, dict):
        return ["region document must be an object."]
    errors = []
    required = ("region_id", "name", "region_type", "parent_region_id", "boundary",
                "boundary_version", "source", "provenance", "license",
                "approval_status", "created_at", "updated_at")
    missing = [key for key in required if key not in document]
    if missing:
        errors.append("missing required fields: " + ", ".join(missing) + ".")
        return errors

    region_id = document["region_id"]
    region_type = document["region_type"]
    parent_id = document["parent_region_id"]
    version = document["boundary_version"]
    status = document["approval_status"]
    if not isinstance(region_id, str) or not REGION_ID_RE.fullmatch(region_id):
        errors.append("region_id must be a stable lowercase slug.")
    if not isinstance(document["name"], str) or not document["name"].strip() or len(document["name"]) > 160:
        errors.append("name must be a non-empty string of at most 160 characters.")
    valid_region_type = isinstance(region_type, str) and region_type in REGION_TYPES
    valid_status = isinstance(status, str) and status in APPROVAL_STATUSES
    if not valid_region_type:
        errors.append("region_type must be country, state, city, or ward.")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        errors.append("boundary_version must be a non-empty version label of at most 64 characters.")
    if not valid_status:
        errors.append("approval_status must be draft, approved, rejected, or superseded.")
    if parent_id is not None and (not isinstance(parent_id, str) or not REGION_ID_RE.fullmatch(parent_id)):
        errors.append("parent_region_id must be null or a stable lowercase region ID.")
    if valid_region_type and region_type == "country" and parent_id is not None:
        errors.append("country regions cannot have a parent.")
    if valid_region_type and region_type in PARENT_TYPE and parent_id is None:
        errors.append(f"{region_type} regions require a {PARENT_TYPE[region_type]} parent.")
    if parent is not None:
        if not isinstance(parent, dict) or parent.get("region_id") != parent_id or parent.get("approval_status") != "approved":
            errors.append("parent region must match parent_region_id and be approved.")
        elif valid_region_type and PARENT_TYPE.get(region_type) != parent.get("region_type"):
            errors.append(f"{region_type} parent must have type {PARENT_TYPE.get(region_type)}.")
    elif parent_id is not None and status == "approved":
        errors.append("approved regions require a verified approved parent region.")

    for field in ("source", "provenance", "license"):
        if not isinstance(document[field], dict):
            errors.append(f"{field} must be an object.")
    source = document["source"] if isinstance(document["source"], dict) else {}
    provenance = document["provenance"] if isinstance(document["provenance"], dict) else {}
    license_info = document["license"] if isinstance(document["license"], dict) else {}
    for field in ("created_at", "updated_at"):
        value = document[field]
        if not isinstance(value, datetime) or value.tzinfo is None:
            errors.append(f"{field} must be a timezone-aware datetime.")

    boundary = document["boundary"]
    if boundary is None:
        if valid_status and status in {"approved", "superseded"}:
            errors.append("approved or superseded region versions require a boundary.")
    else:
        errors.extend(validate_boundary(boundary))
    if valid_status and status in {"approved", "superseded"}:
        if not source.get("organization") or not source.get("title") or not source.get("url"):
            errors.append("approved region versions require source organization, title, and URL.")
        if not provenance.get("dataset_id") or not SHA256_RE.fullmatch(str(provenance.get("checksum_sha256", ""))):
            errors.append("approved region versions require a dataset ID and SHA-256 source checksum.")
        if not license_info.get("name") or not license_info.get("url"):
            errors.append("approved region versions require license name and URL.")
        if license_info.get("redistribution_status") != "cleared":
            errors.append("approved region versions require documented redistribution clearance.")
        if not document.get("approved_by") or not isinstance(document.get("approved_at"), datetime):
            errors.append("approved region versions require approver identity and timestamp.")

    for existing in existing_versions:
        if isinstance(existing, dict) and existing.get("region_id") == region_id and existing.get("boundary_version") == version:
            errors.append("region_id and boundary_version must be unique.")
            break
    return errors


def _region_collection():
    return current_app.extensions["nodal_db"]["regions"]


def _approved_regions():
    rows = [row for row in _region_collection().find({}) if isinstance(row, dict)]
    by_id = {}
    for row in rows:
        region_id = row.get("region_id")
        if row.get("approval_status") == "approved" and isinstance(region_id, str) and REGION_ID_RE.fullmatch(region_id):
            by_id.setdefault(region_id, []).append(row)
    # Ambiguous current versions and invalid ancestry are withheld publicly.
    result = {}
    visiting = set()

    def valid_region(region_id):
        if not isinstance(region_id, str):
            return None
        if region_id in result:
            return result[region_id]
        candidates = by_id.get(region_id, [])
        if not region_id or len(candidates) != 1 or region_id in visiting:
            return None
        row = candidates[0]
        visiting.add(region_id)
        parent = valid_region(row.get("parent_region_id")) if row.get("parent_region_id") is not None else None
        visiting.remove(region_id)
        other_versions = [existing for existing in rows if existing is not row]
        if validate_region_document(row, other_versions, parent):
            return None
        result[region_id] = row
        return row

    for region_id in by_id:
        valid_region(region_id)
    return result


def _api_region(row, include_boundary=False):
    response = {key: row.get(key) for key in (
        "region_id", "name", "region_type", "parent_region_id", "boundary_version",
        "source", "provenance", "license", "approval_status", "approved_at", "created_at", "updated_at",
    )}
    if include_boundary:
        response["boundary"] = row.get("boundary")
    for key in ("created_at", "updated_at", "approved_at"):
        if isinstance(response.get(key), datetime):
            response[key] = response[key].isoformat()
    if isinstance(row.get("approved_at"), datetime):
        response["approved_at"] = row["approved_at"].isoformat()
    return response


def resolve_region_for_geographic_api(region_id):
    """Resolve a single usable approved version or return an API error tuple."""
    if not isinstance(region_id, str) or not REGION_ID_RE.fullmatch(region_id):
        return None, ("invalid_region_id", "Region ID must be a lowercase stable region identifier.", 400)

    rows = list(_region_collection().find({"region_id": region_id}))
    if not rows:
        if region_id == BENGALURU_PILOT_TEMPLATE["region_id"]:
            return None, ("region_not_approved", "This region is a draft and is not available for geographic statistics.", 409)
        return None, ("region_not_found", "Region was not found.", 404)

    approved = [row for row in rows if isinstance(row, dict) and row.get("approval_status") == "approved"]
    if len(approved) > 1:
        return None, ("region_version_ambiguous", "More than one approved boundary version exists.", 409)
    if not approved:
        statuses = {row.get("approval_status") for row in rows if isinstance(row, dict)}
        if "superseded" in statuses:
            return None, ("boundary_version_retired", "The region boundary version is retired.", 410)
        if statuses & {"draft", "rejected"}:
            return None, ("region_not_approved", "The region boundary has not been approved.", 409)
        return None, ("invalid_region", "Region registry data is invalid.", 422)

    row = approved[0]
    if row.get("boundary") is None:
        return None, ("boundary_missing", "The approved region has no usable boundary.", 409)
    if not isinstance(row.get("boundary_version"), str):
        return None, ("invalid_region", "The approved region boundary version is invalid.", 422)

    approved_registry = _approved_regions()
    if region_id not in approved_registry:
        return None, ("invalid_region", "The approved region metadata or geometry is invalid.", 422)
    return approved_registry[region_id], None


def _region_api_error(region_id, error):
    code, message, status = error
    return jsonify(error={"code": code, "message": message},
                   scope={"type": "region", "region_id": region_id}), status


def _regional_data_notice():
    return ("Region totals include only complaints with valid coordinates inside the approved boundary. "
            "Missing or invalid locations cannot be assigned to a region. Platform-wide demonstration records may be included.")


def _privacy_suppression(suppressed_metrics=()):
    return {
        "minimum_count": 5,
        "suppressed_metrics": list(suppressed_metrics),
        "sparse_hotspot_clusters_suppressed": True,
        "hotspot_centers_coarsened": True,
        "exact_complaint_points_returned": False,
        "formal_anonymity_guarantee": False,
    }


def _geographic_complaints(region):
    # Current pilot data is small and unclassified legacy rows need strict
    # application-level validation. This scan keeps filtering behavior pure and
    # testable; production scaling should prefilter with the existing 2dsphere
    # index ($geoWithin) and revalidate returned points before aggregation.
    documents = list(current_app.extensions["nodal_db"]["complaints"].find({}))
    return filter_complaints_to_region(documents, region["boundary"])


def _region_metadata(region):
    return {"region_id": region["region_id"], "name": region["name"],
            "region_type": region["region_type"], "boundary_version": region["boundary_version"]}


@regions_bp.get("/public/regions")
def list_public_regions():
    regions = _approved_regions()
    return jsonify([_api_region(regions[region_id]) for region_id in sorted(regions)])


@regions_bp.get("/public/regions/<region_id>")
def get_public_region(region_id):
    region = _approved_regions().get(region_id)
    if region is None:
        return jsonify(error="Approved region not found."), 404
    return jsonify(_api_region(region, include_boundary=True))


@regions_bp.get("/public/regions/<region_id>/overview")
def public_region_overview(region_id):
    region, error = resolve_region_for_geographic_api(region_id)
    if error:
        return _region_api_error(region_id, error)
    complaints = _geographic_complaints(region)
    metrics, suppressed = region_overview_metrics(complaints)
    return jsonify(scope={"type": "region", "region": _region_metadata(region)},
                   metrics=metrics, data_quality_notice=_regional_data_notice(),
                   privacy_suppression=_privacy_suppression(suppressed))


@regions_bp.get("/public/regions/<region_id>/hotspots")
def public_region_hotspots(region_id):
    region, error = resolve_region_for_geographic_api(region_id)
    if error:
        return _region_api_error(region_id, error)
    complaints = _geographic_complaints(region)
    return jsonify(scope={"type": "region", "region": _region_metadata(region)},
                   hotspots=hotspots_for_documents(complaints),
                   data_quality_notice=_regional_data_notice(),
                   privacy_suppression=_privacy_suppression())


@regions_bp.get("/admin/regions")
@roles_required("admin")
def list_admin_regions():
    rows = list(_region_collection().find({}))
    rows.sort(key=lambda row: (str(row.get("region_id", "")), str(row.get("boundary_version", ""))))
    return jsonify([_api_region(row, include_boundary=True) for row in rows])
