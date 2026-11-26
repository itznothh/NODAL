import hmac
import os
import secrets
import warnings
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_file, session
from flask_cors import CORS
from pymongo import GEOSPHERE, MongoClient
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    from .deployment_config import validate_production_environment
    from .evidence import EvidenceError, evidence_path, store_evidence
    from .api.vision import vision_bp
    from .auth import admin_bp, auth_bp, audit, current_user, roles_required
    from .departments import department_for_category, departments_bp, find_department, seed_default_departments
    from .geography import (hotspots_for_documents, region_overview_metrics,
                            valid_geojson_point as _valid_geojson_point,
                            valid_longitude_latitude as _valid_longitude_latitude)
    from .regions import regions_bp
except ImportError:  # ``python backend/app.py`` entry point
    from deployment_config import validate_production_environment
    from evidence import EvidenceError, evidence_path, store_evidence
    from api.vision import vision_bp
    from auth import admin_bp, auth_bp, audit, current_user, roles_required
    from departments import department_for_category, departments_bp, find_department, seed_default_departments
    from geography import (hotspots_for_documents, region_overview_metrics,
                            valid_geojson_point as _valid_geojson_point,
                            valid_longitude_latitude as _valid_longitude_latitude)
    from regions import regions_bp

load_dotenv()
MODEL_PATH = Path(__file__).resolve().parent.parent / "ml" / "classifier.joblib"
model = joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None
DATA_NOTICE = "This overview includes legacy demonstration/sample records; counts are not verified civic statistics."
AUDIT_DATABASES = {"nodal_phase7_audit", "nodal_phase8_audit"}
SUPPORTED_CATEGORIES = {"pothole", "garbage", "waterlogging", "drainage", "streetlight",
                       "water_leak", "damaged_infrastructure", "other", "unclassified"}


def predict_category(text):
    return str(model.predict([text])[0]) if model else "unclassified"


def score_priority(text, duplicate_count):
    high_words = ["accident", "overflowing", "flooding", "burst", "open manhole", "unsafe", "skidding"]
    text = text.lower()
    score = sum(word in text for word in high_words) + duplicate_count
    return "high" if score >= 2 else "medium" if score == 1 else "low"


def find_duplicates(complaints, description, lng, lat):
    """Open complaints within 100 m with similar wording."""
    nearby = list(complaints.find({
        "status": {"$nin": ["resolved", "disputed"]},
        "location": {"$near": {"$geometry": {"type": "Point", "coordinates": [lng, lat]}, "$maxDistance": 100}},
    }).limit(20))
    if not nearby:
        return []
    texts = [d.get("description", "") for d in nearby] + [description]
    try:
        tfidf = TfidfVectorizer().fit_transform(texts)
    except ValueError:  # all descriptions empty/stop words
        return []
    sims = cosine_similarity(tfidf[-1], tfidf[:-1]).flatten()
    return [{"id": str(d["_id"]), "description": d.get("description", ""), "similarity": round(float(s), 2)}
            for d, s in zip(nearby, sims) if s >= 0.5]


def clean(doc):
    doc = dict(doc)
    doc["_id"] = str(doc["_id"])
    for key in ("created_by", "assigned_official_id", "department_id"):
        if isinstance(doc.get(key), ObjectId):
            doc[key] = str(doc[key])
    if not doc.get("created_by"):
        doc["data_quality"] = "demo_sample_unverified"
    if "images" in doc:
        doc["images"] = [{key: value for key, value in image.items() if key != "storage_key"} for image in doc["images"]]
        for image in doc["images"]:
            image["url"] = f"/complaints/{doc['_id']}/evidence/{image['id']}"
    return doc


def routing_view(doc, database, viewer=None):
    """Expose stored routing suggestions without changing complaint records."""
    result = clean(doc)
    if viewer and viewer.get("role") in {"citizen", "official"}:
        # Non-admin views retain useful history while hiding internal account IDs.
        result.pop("created_by", None)
        if viewer.get("role") == "official":
            result["assigned_to_viewer"] = doc.get("assigned_official_id") == viewer.get("_id")
        result.pop("assigned_official_id", None)
        result["status_history"] = [
            {key: value for key, value in event.items() if key != "actor_id"}
            for event in result.get("status_history", [])
        ]
        private_assignment_keys = {"official_id", "previous_official_id", "administrator_id"}
        result["assignment_history"] = [
            {key: value for key, value in entry.items() if key not in private_assignment_keys}
            for entry in result.get("assignment_history", [])
        ]
    if not doc.get("created_by"):
        return result
    suggested_id = doc.get("suggested_department_id")
    suggested_name = doc.get("suggested_department_name")
    if not suggested_id and not suggested_name:
        suggested = department_for_category(database, doc.get("category"))
        if suggested:
            suggested_id = suggested.get("department_id")
            suggested_name = suggested.get("name")
    result["suggested_department_id"] = suggested_id
    result["suggested_department_name"] = suggested_name
    result["routing_review_required"] = bool(doc.get("routing_review_required", not suggested_id))
    result["awaiting_department_review"] = bool(
        not doc.get("department") and doc.get("status", "submitted") == "submitted"
    )
    return result


def _valid_coordinates(data):
    try:
        raw_lat, raw_lng = data["lat"], data["lng"]
        if isinstance(raw_lat, bool) or isinstance(raw_lng, bool):
            return None
        lat, lng = float(raw_lat), float(raw_lng)
    except (KeyError, OverflowError, TypeError, ValueError):
        return None
    point = _valid_longitude_latitude([lng, lat])
    if point is None:
        return None
    return point[1], point[0]


def _status_history(status, actor_id, actor_role, action, note=None, evidence=None):
    return {"status": status, "actor_id": actor_id, "actor_role": actor_role,
            "action": action, "note": note, "evidence": evidence or [],
            "created_at": datetime.now(timezone.utc)}


def _complaint_access(user, complaint):
    if user["role"] == "admin":
        return True
    if user["role"] == "citizen":
        return complaint.get("created_by") == user["_id"]
    return (complaint.get("assigned_official_id") == user["_id"] or
            (bool(user.get("department_id")) and complaint.get("department_id") == user.get("department_id")) or
            (bool(user.get("department")) and complaint.get("department") == user.get("department")))


def _transition_error(role, status, target):
    rules = {
        "admin": {"submitted": {"triaged"}, "open": {"triaged"},
                  "resolution_submitted": {"resolved", "in_progress"},
                  "resolved": {"in_progress"}, "reopening_requested": {"in_progress", "resolved"},
                  "disputed": {"in_progress", "resolved"}},
        "official": {"assigned": {"in_progress"}, "in_progress": {"resolution_submitted"}},
        "citizen": {"resolved": {"reopening_requested", "disputed"}},
    }
    if target not in rules.get(role, {}).get(status, set()):
        return f"Transition from '{status}' to '{target}' is not permitted for {role} accounts."
    return None


def _hotspot_data(complaints):
    docs = list(complaints.find({"status": {"$nin": ["resolved", "disputed"]}}))
    return hotspots_for_documents(docs)


def configured_database_name(environ=None):
    """Select the application database and require an explicit audit target."""
    environ = os.environ if environ is None else environ
    audit_mode_value = environ.get("NODAL_AUDIT_MODE", "").strip().lower()
    if audit_mode_value in {"1", "true", "yes", "on"}:
        audit_mode = True
    elif audit_mode_value in {"", "0", "false", "no", "off"}:
        audit_mode = False
    else:
        raise RuntimeError("NODAL_AUDIT_MODE must be a boolean value.")

    configured_name = environ.get("NODAL_DB_NAME")
    if audit_mode and configured_name is None:
        raise RuntimeError("NODAL_DB_NAME must be explicitly set to an approved isolated audit database in audit mode.")
    database_name = configured_name.strip() if configured_name is not None else "nodal"
    if not database_name:
        raise RuntimeError("NODAL_DB_NAME cannot be empty.")
    if audit_mode and database_name not in AUDIT_DATABASES:
        raise RuntimeError("Audit mode may only use nodal_phase7_audit or nodal_phase8_audit.")
    return database_name


def create_app(database=None, mongo_client=None, test_config=None):
    """Create Flask app; tests can inject an isolated in-memory database."""
    if os.getenv("NODAL_ENV", "development").strip().lower() == "production":
        configuration_errors = validate_production_environment(os.environ)
        if configuration_errors:
            raise RuntimeError("Production configuration is invalid: " + " ".join(configuration_errors))
    database_name = configured_database_name()
    app = Flask(__name__)
    secret_key = os.getenv("NODAL_SECRET_KEY")
    if not secret_key:
        if os.getenv("NODAL_ENV", "development").lower() == "production":
            raise RuntimeError("NODAL_SECRET_KEY must be configured in production.")
        secret_key = secrets.token_hex(32)
        warnings.warn("NODAL_SECRET_KEY is unset; sessions will reset when the process restarts.", RuntimeWarning)
    elif os.getenv("NODAL_ENV", "development").strip().lower() == "production" and len(secret_key) < 32:
        raise RuntimeError("NODAL_SECRET_KEY must contain at least 32 characters in production.")
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_NAME="nodal_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("NODAL_ENV", "development").lower() == "production",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        EVIDENCE_DIR=Path(os.getenv("NODAL_EVIDENCE_DIR", str(Path(os.getenv("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "NODAL" / "evidence"))),
    )
    if test_config:
        app.config.update(test_config)
    repo_root = Path(__file__).resolve().parents[1]
    evidence_root = Path(app.config["EVIDENCE_DIR"]).expanduser().resolve()
    if evidence_root == repo_root or repo_root in evidence_root.parents:
        raise RuntimeError("EVIDENCE_DIR must resolve outside the repository.")
    app.config["EVIDENCE_DIR"] = evidence_root
    if database is None:
        mongo_client = mongo_client or MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"),
                                                    serverSelectionTimeoutMS=5000, connect=False)
        database = mongo_client[database_name]
    app.extensions["nodal_db"] = database
    app.extensions["nodal_mongo_client"] = mongo_client
    app.extensions["nodal_indexes_ready"] = False

    origins_value = os.getenv("NODAL_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    origins = [item.strip() for item in origins_value.split(",") if item.strip()]
    if os.getenv("NODAL_ENV", "development").lower() != "production":
        origins.append("http://127.0.0.1:5174")
    origins = list(dict.fromkeys(origins))
    CORS(app, origins=origins, supports_credentials=True)
    app.register_blueprint(vision_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(departments_bp)
    app.register_blueprint(regions_bp)

    @app.before_request
    def ensure_indexes_and_csrf():
        if not app.extensions["nodal_indexes_ready"]:
            db = app.extensions["nodal_db"]
            db["complaints"].create_index([("location", GEOSPHERE)])
            db["users"].create_index("email", unique=True)
            db["official_access_requests"].create_index([("user_id", 1)], unique=True,
                                                          partialFilterExpression={"status": "pending"})
            db["audit_logs"].create_index([("created_at", -1)])
            db["departments"].create_index("department_id", unique=True)
            db["departments"].create_index("name_key", unique=True)
            seed_default_departments(db)
            app.extensions["nodal_indexes_ready"] = True
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            expected = session.get("csrf_token", "")
            supplied = request.headers.get("X-CSRF-Token", "")
            if not expected or not supplied or not hmac.compare_digest(expected, supplied):
                return jsonify(error="CSRF token missing or invalid. Refresh the page and try again."), 403
        return None

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(success=False, error="Request is too large. Maximum request size is 8 MB; image evidence is limited to 5 MB."), 413

    @app.get("/")
    def home():
        return jsonify(message="NODAL API running")

    @app.get("/health")
    def health():
        client = app.extensions.get("nodal_mongo_client")
        if client is not None:
            client.admin.command("ping")
        return jsonify(status="ok")

    @app.get("/public/overview")
    def public_overview():
        complaints = app.extensions["nodal_db"]["complaints"]
        docs = list(complaints.find({}))
        open_docs = [d for d in docs if d.get("status") not in {"resolved", "disputed"}]
        hotspots = _hotspot_data(complaints)
        return jsonify(total=len(docs), open=len(open_docs),
                       high_priority=sum(d.get("priority") == "high" for d in open_docs),
                       hotspot_count=len(hotspots), data_notice=DATA_NOTICE)

    @app.post("/complaints")
    @roles_required("citizen")
    def create_complaint():
        is_multipart = request.mimetype == "multipart/form-data"
        data = request.form.to_dict() if is_multipart else request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Send a JSON object."), 400
        description = data.get("description")
        if not isinstance(description, str) or not description.strip() or len(description.strip()) > 2000:
            return jsonify(error="Description is required and must be 2,000 characters or fewer."), 400
        coordinates = _valid_coordinates(data)
        if coordinates is None:
            return jsonify(error="Valid latitude and longitude are required."), 400
        category = data.get("category")
        if category is not None and (not isinstance(category, str) or category not in SUPPORTED_CATEGORIES):
            return jsonify(error="Choose a supported complaint category."), 400
        image_file = request.files.get("image") if is_multipart else None
        image_bytes = None
        if image_file and image_file.filename:
            image_bytes = image_file.read(5 * 1024 * 1024 + 1)
            if len(image_bytes) > 5 * 1024 * 1024:
                return jsonify(error="Image is too large. Maximum size is 5 MB."), 413
        lat, lng = coordinates
        complaints = app.extensions["nodal_db"]["complaints"]
        duplicates = find_duplicates(complaints, description.strip(), lng, lat)
        image_metadata = None
        if image_bytes is not None:
            try:
                image_metadata = store_evidence(image_bytes, app.config["EVIDENCE_DIR"])
            except EvidenceError as err:
                return jsonify(error=err.message), err.status
        user = g.current_user
        final_category = category or predict_category(description.strip())
        suggested = department_for_category(app.extensions["nodal_db"], final_category)
        doc = {"description": description.strip(),
               "category": final_category,
               "priority": score_priority(description.strip(), len(duplicates)),
               "status": "submitted", "location": {"type": "Point", "coordinates": [lng, lat]},
               "created_at": datetime.now(timezone.utc), "created_by": user["_id"],
               "suggested_department_id": suggested.get("department_id") if suggested else None,
               "suggested_department_name": suggested.get("name") if suggested else None,
               "routing_review_required": suggested is None,
               "assignment_history": [],
               "status_history": [_status_history("submitted", str(user["_id"]), user["role"], "submitted")]}
        if image_metadata:
            doc["images"] = [image_metadata]
        try:
            inserted = complaints.insert_one(doc)
        except Exception:
            if image_metadata:
                path = evidence_path(app.config["EVIDENCE_DIR"], image_metadata["storage_key"])
                if path:
                    path.unlink(missing_ok=True)
            return jsonify(error="Could not save the report and its image. Nothing was submitted."), 503
        doc["_id"] = inserted.inserted_id
        audit("complaint_created", "complaint", inserted.inserted_id)
        response = routing_view(doc, app.extensions["nodal_db"], user)
        # Avoid returning another resident's complaint ID or description to a
        # citizen. Similarity scores communicate a possible match without exposing
        # the other complaint record.
        response["possible_duplicates"] = [
            {"similarity": item["similarity"]} for item in duplicates
        ]
        return jsonify(response), 201

    @app.get("/complaints/<complaint_id>/evidence/<evidence_id>")
    @roles_required("citizen", "official", "admin")
    def get_complaint_evidence(complaint_id, evidence_id):
        try:
            oid = ObjectId(complaint_id)
        except (InvalidId, TypeError):
            return jsonify(error="Invalid complaint ID."), 400
        complaint = app.extensions["nodal_db"]["complaints"].find_one({"_id": oid})
        if not complaint or not _complaint_access(g.current_user, complaint):
            return jsonify(error="Evidence not found."), 404
        metadata = next((item for item in complaint.get("images", []) if item.get("id") == evidence_id), None)
        if metadata is None:
            return jsonify(error="Evidence not found."), 404
        path = evidence_path(app.config["EVIDENCE_DIR"], metadata.get("storage_key", ""))
        if path is None:
            return jsonify(error="Evidence file is missing from secure storage."), 404
        response = send_file(path, mimetype=metadata["content_type"], as_attachment=False,
                             download_name=f"complaint-evidence-{evidence_id}{path.suffix}")
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/complaints")
    @roles_required("citizen", "official", "admin")
    def list_complaints():
        user = g.current_user
        query = {}
        if user["role"] == "citizen":
            query["created_by"] = user["_id"]
        elif user["role"] == "official":
            query["$or"] = ([{"assigned_official_id": user["_id"]}, {"department": user["department"]}]
                            if user.get("department") else [{"assigned_official_id": user["_id"]}])
        if request.args.get("status"):
            query["status"] = request.args["status"]
        if request.args.get("category"):
            query["category"] = request.args["category"]
        priority = request.args.get("priority")
        if priority:
            if priority not in {"low", "medium", "high"}:
                return jsonify(error="Invalid priority filter."), 400
            query["priority"] = priority
        department = request.args.get("department")
        if department:
            if len(department) > 160:
                return jsonify(error="Department filter is too long."), 400
            query["department"] = department
        docs = list(app.extensions["nodal_db"]["complaints"].find(query).sort("created_at", -1).limit(500))
        if user["role"] == "official":
            docs = [doc for doc in docs if _complaint_access(user, doc)]
        return jsonify([routing_view(doc, app.extensions["nodal_db"], user) for doc in docs])

    @app.get("/complaints/<complaint_id>")
    @roles_required("citizen", "official", "admin")
    def get_complaint(complaint_id):
        try:
            oid = ObjectId(complaint_id)
        except InvalidId:
            return jsonify(error="Invalid id."), 400
        complaint = app.extensions["nodal_db"]["complaints"].find_one({"_id": oid})
        if not complaint:
            return jsonify(error="Not found."), 404
        user = g.current_user
        if not _complaint_access(user, complaint):
            return jsonify(error="Complaint not found."), 404
        return jsonify(routing_view(complaint, app.extensions["nodal_db"], user))

    @app.patch("/complaints/<complaint_id>")
    @roles_required("admin")
    def update_complaint(complaint_id):
        return jsonify(error="Use the assignment and transition endpoints; complaint fields cannot be edited directly."), 405

    @app.post("/complaints/<complaint_id>/assign")
    @roles_required("admin")
    def assign_complaint(complaint_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Send a JSON object."), 400
        try:
            oid = ObjectId(complaint_id)
        except InvalidId:
            return jsonify(error="Invalid id."), 400
        complaints = app.extensions["nodal_db"]["complaints"]
        existing = complaints.find_one({"_id": oid})
        if not existing:
            return jsonify(error="Not found."), 404
        if not existing.get("created_by"):
            return jsonify(error="Legacy demonstration records are read-only sample data."), 409
        current_status = existing.get("status", "submitted")
        if current_status in {"resolved", "disputed"}:
            return jsonify(error="Resolved or disputed complaints cannot be reassigned."), 409
        database = app.extensions["nodal_db"]
        selected_id = data.get("department_id")
        selected_name = data.get("department")
        if selected_id is not None and not isinstance(selected_id, str):
            return jsonify(error="Department ID must be a string."), 400
        if selected_id:
            selected_department = find_department(database, department_id=selected_id, active_only=True)
        elif isinstance(selected_name, str) and selected_name.strip():
            selected_department = find_department(database, name=selected_name, active_only=True)
        else:
            selected_department = None
        if selected_department is None:
            return jsonify(error="Select an active department from the registry."), 400
        department = selected_department["name"]
        department_id = selected_department["department_id"]
        reason = data.get("reason", data.get("note", ""))
        if not isinstance(reason, str) or len(reason.strip()) > 2000:
            return jsonify(error="Assignment reason must be 2,000 characters or fewer."), 400
        previous_department_id = existing.get("department_id")
        previous_department = existing.get("department")
        suggested_department_id = existing.get("suggested_department_id")
        suggested_department_name = existing.get("suggested_department_name")
        if not suggested_department_id and not suggested_department_name:
            suggestion = department_for_category(database, existing.get("category"))
            if suggestion:
                suggested_department_id = suggestion.get("department_id")
                suggested_department_name = suggestion.get("name")
        changed_department = (
            (previous_department_id and previous_department_id != department_id)
            or (not previous_department_id and previous_department and previous_department != department)
        )
        override_suggestion = bool(suggested_department_id and suggested_department_id != department_id)
        needs_reason = bool(changed_department or override_suggestion or not suggested_department_id)
        if needs_reason and not reason.strip():
            return jsonify(error="A reason is required for a manual override, reassignment, or unmapped category."), 400
        official_id = None
        if data.get("official_id"):
            try:
                official_id = ObjectId(data["official_id"])
            except (InvalidId, TypeError):
                return jsonify(error="Invalid official ID."), 400
            official = database["users"].find_one({"_id": official_id, "role": "official", "status": "active"})
            if (not official or not official.get("official_verified_at") or not official.get("official_verified_by")
                    or not official.get("department")):
                return jsonify(error="Only an active, administrator-verified official can be assigned."), 400
            if official.get("department_id") != department_id and official.get("department") != department:
                return jsonify(error="The official's verified department does not match this assignment."), 400
        status = "assigned" if current_status in {"submitted", "open", "triaged", "assigned"} else current_status
        assignment_reason = reason.strip() or "Assigned to the suggested department"
        now = datetime.now(timezone.utc)
        effective_official_id = official_id or (existing.get("assigned_official_id") if not changed_department else None)
        history_entry = {
            "suggested_department_id": suggested_department_id,
            "suggested_department_name": suggested_department_name,
            "previous_department_id": previous_department_id,
            "previous_department": previous_department,
            "department_id": department_id,
            "department": department,
            "official_id": str(effective_official_id) if effective_official_id else None,
            "previous_official_id": str(existing["assigned_official_id"]) if existing.get("assigned_official_id") else None,
            "administrator_id": str(g.current_user["_id"]),
            "timestamp": now,
            "reason": assignment_reason,
        }
        event = _status_history(status, str(g.current_user["_id"]), "admin", "assigned",
                                assignment_reason)
        values = {"department": department, "department_id": department_id,
                  "suggested_department_id": suggested_department_id,
                  "suggested_department_name": suggested_department_name,
                  "routing_review_required": not bool(suggested_department_id),
                  "status": status, "updated_at": now}
        if official_id:
            values["assigned_official_id"] = official_id
        update = {"$set": values, "$push": {"status_history": event, "assignment_history": history_entry}}
        if not official_id and existing.get("assigned_official_id") and changed_department:
            update["$unset"] = {"assigned_official_id": ""}
        complaints.update_one({"_id": oid}, update)
        audit("complaint_assigned" if not previous_department else "complaint_reassigned", "complaint", oid,
              {"department": department, "department_id": department_id,
               "previous_department": previous_department, "reason": assignment_reason,
               "official_id": str(effective_official_id) if effective_official_id else None})
        return jsonify(routing_view(complaints.find_one({"_id": oid}), database, g.current_user))

    @app.get("/admin/officials")
    @roles_required("admin")
    def list_verified_officials():
        rows = app.extensions["nodal_db"]["users"].find({"role": "official", "status": "active"}).sort("full_name", 1).limit(500)
        return jsonify([{"id": str(row["_id"]), "full_name": row.get("full_name", ""),
                         "email": row.get("email", ""), "department": row.get("department", ""),
                         "department_id": row.get("department_id")}
                        for row in rows if row.get("official_verified_at") and row.get("official_verified_by")])

    @app.get("/admin/overview")
    @roles_required("admin")
    def admin_overview():
        """Return administrator-only workload counts from the existing records."""
        database = app.extensions["nodal_db"]
        complaint_rows = list(database["complaints"].find({}))
        status_names = ("submitted", "assigned", "in_progress", "resolution_submitted", "resolved")
        status_counts = Counter(row.get("status", "submitted") for row in complaint_rows)

        registry = list(database["departments"].find({}))
        workloads = {}
        name_to_id = {}
        for department in registry:
            department_id = department.get("department_id", "")
            name = department.get("name", department_id or "Department")
            if name:
                name_to_id[name.casefold()] = department_id
            workloads[department_id or name] = {
                "department_id": department_id or None,
                "department": name,
                "active": department.get("active", True),
                "total": 0,
                **{status: 0 for status in status_names},
            }

        for complaint in complaint_rows:
            department_id = complaint.get("department_id")
            department_name = complaint.get("department")
            if not department_id and department_name:
                department_id = name_to_id.get(str(department_name).casefold())
            key = department_id or department_name or "unassigned"
            if key not in workloads:
                workloads[key] = {
                    "department_id": department_id,
                    "department": department_name or "Unassigned",
                    "active": None,
                    "total": 0,
                    **{status: 0 for status in status_names},
                }
            bucket = workloads[key]
            bucket["total"] += 1
            status = complaint.get("status", "submitted")
            if status in status_names:
                bucket[status] += 1

        pending_requests = list(database["official_access_requests"].find({"status": "pending"}))
        return jsonify(
            total_complaints=len(complaint_rows),
            status_counts={status: status_counts.get(status, 0) for status in status_names},
            department_workload=sorted(workloads.values(), key=lambda item: item["department"].casefold()),
            pending_official_requests=len(pending_requests),
            resolutions_awaiting_review=status_counts.get("resolution_submitted", 0),
            data_notice=DATA_NOTICE,
        )

    @app.get("/admin/complaints/unmapped")
    @roles_required("admin")
    def list_unmapped_complaints():
        database = app.extensions["nodal_db"]
        mapped = {category for dept in database["departments"].find({"active": True})
                  for category in dept.get("categories", [])}
        rows = database["complaints"].find({})
        results = []
        for row in rows:
            if not row.get("created_by") or row.get("data_quality") == "demo_sample_unverified":
                continue
            if row.get("routing_review_required") or row.get("category") not in mapped:
                results.append(routing_view(row, database))
        return jsonify(results)

    @app.post("/complaints/<complaint_id>/transition")
    @roles_required("citizen", "official", "admin")
    def transition_complaint(complaint_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("status"), str):
            return jsonify(error="A target status is required."), 400
        target = data["status"]
        note = data.get("notes", "")
        evidence = data.get("evidence", [])
        if not isinstance(note, str) or len(note.strip()) > 2000:
            return jsonify(error="Notes must be 2,000 characters or fewer."), 400
        if not isinstance(evidence, list) or len(evidence) > 10 or any(not isinstance(item, str) or not item.strip() or len(item) > 1000 for item in evidence):
            return jsonify(error="Evidence must be a list of up to 10 non-empty references (1,000 characters each)."), 400
        user = g.current_user
        try:
            oid = ObjectId(complaint_id)
        except InvalidId:
            return jsonify(error="Invalid id."), 400
        complaints = app.extensions["nodal_db"]["complaints"]
        existing = complaints.find_one({"_id": oid})
        if not existing:
            return jsonify(error="Not found."), 404
        if not _complaint_access(user, existing):
            return jsonify(error="Complaint not found."), 404
        if not existing.get("created_by"):
            return jsonify(error="Legacy demonstration records are read-only sample data."), 409
        old_status = existing.get("status", "submitted")
        error = _transition_error(user["role"], old_status, target)
        if error:
            return jsonify(error=error), 409
        if target == "resolution_submitted" and (not note.strip() or not evidence):
            return jsonify(error="Resolution requires notes and at least one supporting evidence reference."), 400
        if (user["role"] == "admin" and old_status == "resolution_submitted"
                and target == "in_progress" and not note.strip()):
            return jsonify(error="A reason is required when rejecting a submitted resolution."), 400
        if target in {"reopening_requested", "disputed"} and not note.strip():
            return jsonify(error="A note explaining the dispute is required."), 400
        if target == "resolved" and (not note.strip() or not evidence):
            return jsonify(error="Resolution requires notes and at least one supporting evidence reference."), 400
        action = {"reopening_requested": "resolution_disputed", "disputed": "resolution_disputed"}.get(target, target)
        if user["role"] == "admin" and old_status == "resolution_submitted":
            action = "resolution_approved" if target == "resolved" else "resolution_rejected"
        event = _status_history(target, str(user["_id"]), user["role"], action, note.strip() or None, evidence)
        changed = complaints.update_one({"_id": oid, "status": old_status}, {
            "$set": {"status": target, "updated_at": datetime.now(timezone.utc)}, "$push": {"status_history": event}})
        if changed.matched_count != 1:
            return jsonify(error="Complaint changed concurrently; refresh and retry."), 409
        audit("complaint_status_transition", "complaint", oid, {"from": old_status, "to": target, "action": action})
        return jsonify(routing_view(complaints.find_one({"_id": oid}), app.extensions["nodal_db"], user))

    @app.delete("/complaints/<complaint_id>")
    @roles_required("admin")
    def delete_complaint(complaint_id):
        return jsonify(error="Complaints are retained as an append-only civic record and cannot be deleted."), 405

    @app.get("/hotspots")
    def hotspots():
        return jsonify(_hotspot_data(app.extensions["nodal_db"]["complaints"]))

    return app


def run_development_server(app_instance):
    if os.getenv("NODAL_ENV", "development").strip().lower() == "production":
        raise SystemExit("Refusing to start production with Flask's development server. Use the configured WSGI server: waitress-serve backend.wsgi:app")
    app_instance.run(debug=True, port=5000)


if __name__ == "__main__":
    if os.getenv("NODAL_ENV", "development").strip().lower() == "production":
        raise SystemExit("Refusing to start production with Flask's development server. Use the configured WSGI server: waitress-serve backend.wsgi:app")
    app = create_app()
    run_development_server(app)
else:
    app = create_app()
