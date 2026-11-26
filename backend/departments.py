"""Configurable department registry and category routing rules."""
import re
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, jsonify, request
from pymongo.errors import DuplicateKeyError

try:
    from .auth import audit, roles_required
except ImportError:  # direct ``python backend/app.py`` execution
    from auth import audit, roles_required

departments_bp = Blueprint("departments", __name__, url_prefix="/admin/departments")

CATEGORY_KEYS = {
    "pothole", "garbage", "waterlogging", "drainage", "streetlight",
    "water_leak", "damaged_infrastructure", "other", "unclassified",
}

# These are prototype routing groups and category suggestions, not verified
# assignments to real government agencies.
DEFAULT_DEPARTMENTS = (
    ("road-infrastructure", "Road Infrastructure", "Proposed routing group for road surface issues.", ("pothole",)),
    ("solid-waste-management", "Solid Waste Management", "Proposed routing group for waste and cleanliness issues.", ("garbage",)),
    ("stormwater-drainage", "Stormwater Drainage", "Proposed routing group for drainage and waterlogging issues.", ("drainage", "waterlogging")),
    ("street-lighting", "Street Lighting", "Proposed routing group for street lighting issues.", ("streetlight",)),
    ("water-supply", "Water Supply", "Proposed routing group for water leakage issues.", ("water_leak",)),
    ("general-infrastructure", "General Infrastructure", "Proposed routing group for issues without a more specific prototype mapping.", ("damaged_infrastructure", "other")),
)
DEPARTMENT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def department_collection(db=None):
    database = db if db is not None else current_app.extensions["nodal_db"]
    return database["departments"]


def department_public(row):
    return {
        "id": row.get("department_id", ""),
        "department_id": row.get("department_id", ""),
        "name": row.get("name", ""),
        "description": row.get("description", ""),
        "active": row.get("active", True),
        "categories": list(row.get("categories", [])),
        "prototype": bool(row.get("prototype", False)),
    }


def seed_default_departments(db):
    """Install proposed prototype mappings once without overwriting admin edits."""
    collection = department_collection(db)
    if collection.find_one({}):
        return
    now = datetime.now(timezone.utc)
    for department_id, name, description, categories in DEFAULT_DEPARTMENTS:
        row = {
            "department_id": department_id,
            "name": name,
            "name_key": name.casefold(),
            "description": description,
            "active": True,
            "categories": list(categories),
            "prototype": True,
            "created_at": now,
            "updated_at": now,
            "created_by": None,
            "updated_by": None,
        }
        try:
            collection.insert_one(row)
        except DuplicateKeyError:
            # Another app worker initialized the same registry concurrently.
            continue


def find_department(db, department_id=None, name=None, active_only=False):
    collection = department_collection(db)
    query = {}
    if department_id:
        query["department_id"] = department_id
    elif name:
        query["name_key"] = name.strip().casefold()
    else:
        return None
    if active_only:
        query["active"] = True
    return collection.find_one(query)


def department_for_category(db, category):
    if not isinstance(category, str):
        return None
    for row in department_collection(db).find({"active": True}):
        if category in row.get("categories", []):
            return row
    return None


def _category_list(value):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return None
    cleaned = list(dict.fromkeys(item.strip() for item in value))
    if any(item not in CATEGORY_KEYS for item in cleaned):
        return None
    return cleaned


def _mapping_conflict(collection, categories, excluding=None):
    selected = set(categories)
    for row in collection.find({"active": True}):
        if excluding and row.get("department_id") == excluding:
            continue
        if selected.intersection(row.get("categories", [])):
            return row
    return None


@departments_bp.get("")
@roles_required("admin")
def list_departments():
    rows = department_collection(current_app.extensions["nodal_db"]).find({}).sort("name", 1)
    return jsonify([department_public(row) for row in rows])


@departments_bp.post("")
@roles_required("admin")
def create_department():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Send a JSON object."), 400
    department_id = data.get("department_id")
    name = data.get("name")
    description = data.get("description", "")
    categories = _category_list(data.get("categories", []))
    active = data.get("active", True)
    if not isinstance(department_id, str) or not DEPARTMENT_ID_RE.fullmatch(department_id):
        return jsonify(error="Department ID must use lowercase letters, numbers, and hyphens."), 400
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
        return jsonify(error="Department name is required and must be 160 characters or fewer."), 400
    if not isinstance(description, str) or len(description) > 2000:
        return jsonify(error="Description must be 2,000 characters or fewer."), 400
    if categories is None:
        return jsonify(error="Categories must contain only supported complaint category keys."), 400
    if not isinstance(active, bool):
        return jsonify(error="Active must be true or false."), 400

    collection = department_collection(current_app.extensions["nodal_db"])
    name_key = name.strip().casefold()
    if collection.find_one({"department_id": department_id}) or collection.find_one({"name_key": name_key}):
        return jsonify(error="A department with this ID or name already exists."), 409
    if active and _mapping_conflict(collection, categories):
        return jsonify(error="One or more categories are already mapped to another active department."), 409
    now = datetime.now(timezone.utc)
    row = {
        "department_id": department_id,
        "name": name.strip(),
        "name_key": name_key,
        "description": description.strip(),
        "active": active,
        "categories": categories,
        "prototype": False,
        "created_at": now,
        "updated_at": now,
        "created_by": g.current_user["_id"],
        "updated_by": g.current_user["_id"],
    }
    try:
        collection.insert_one(row)
    except DuplicateKeyError:
        return jsonify(error="A department with this ID or name already exists."), 409
    audit("department_created", "department", department_id, {"name": row["name"]})
    return jsonify(department_public(row)), 201


@departments_bp.patch("/<department_id>")
@roles_required("admin")
def update_department(department_id):
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Send a JSON object."), 400
    collection = department_collection(current_app.extensions["nodal_db"])
    row = collection.find_one({"department_id": department_id})
    if not row:
        return jsonify(error="Department not found."), 404
    if "department_id" in data and data["department_id"] != department_id:
        return jsonify(error="Department IDs are stable and cannot be changed."), 400

    updates = {}
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
            return jsonify(error="Department name is required and must be 160 characters or fewer."), 400
        name_key = name.strip().casefold()
        duplicate = collection.find_one({"name_key": name_key})
        if duplicate and duplicate.get("department_id") != department_id:
            return jsonify(error="A department with this name already exists."), 409
        updates.update(name=name.strip(), name_key=name_key)
    if "description" in data:
        description = data["description"]
        if not isinstance(description, str) or len(description) > 2000:
            return jsonify(error="Description must be 2,000 characters or fewer."), 400
        updates["description"] = description.strip()
    if "categories" in data:
        categories = _category_list(data["categories"])
        if categories is None:
            return jsonify(error="Categories must contain only supported complaint category keys."), 400
        updates["categories"] = categories
    if "active" in data:
        if not isinstance(data["active"], bool):
            return jsonify(error="Active must be true or false."), 400
        updates["active"] = data["active"]
    if not updates:
        return jsonify(error="Provide at least one department field to update."), 400
    becomes_active = updates.get("active", row.get("active", True))
    categories = updates.get("categories", row.get("categories", []))
    if becomes_active and _mapping_conflict(collection, categories, excluding=department_id):
        return jsonify(error="One or more categories are already mapped to another active department."), 409
    updates.update(updated_at=datetime.now(timezone.utc), updated_by=g.current_user["_id"])
    try:
        collection.update_one({"department_id": department_id}, {"$set": updates})
    except DuplicateKeyError:
        return jsonify(error="A department with this ID or name already exists."), 409
    audit("department_updated", "department", department_id, {"fields": sorted(updates)})
    return jsonify(department_public(collection.find_one({"department_id": department_id})))
