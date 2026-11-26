"""Authentication, account registration, and official access review routes."""
import re
import secrets
from datetime import datetime, timezone
from functools import wraps

from bson import ObjectId
from bson.errors import InvalidId
from flask import Blueprint, current_app, g, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from pymongo.errors import DuplicateKeyError

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
VALID_ROLES = {"citizen", "official", "admin"}
INDEPENDENT_VERIFICATION_METHODS = {"department_contact", "official_directory", "supervisor_confirmation"}


def db():
    return current_app.extensions["nodal_db"]


def user_id(user):
    return str(user["_id"])


def public_user(user):
    return {"id": user_id(user), "full_name": user.get("full_name", ""),
            "email": user.get("email", ""), "role": user.get("role", "citizen"),
            "department": user.get("department"), "department_id": user.get("department_id"),
            "status": user.get("status", "active")}


def audit(action, subject_type, subject_id=None, details=None):
    db()["audit_logs"].insert_one({
        "actor_id": ObjectId(session["user_id"]) if session.get("user_id") else None,
        "action": action, "subject_type": subject_type,
        "subject_id": str(subject_id) if subject_id else None,
        "details": details or {}, "created_at": datetime.now(timezone.utc),
    })


def current_user():
    if getattr(g, "current_user", None) is not None:
        return g.current_user
    raw_id = session.get("user_id")
    if not raw_id:
        return None
    try:
        found = db()["users"].find_one({"_id": ObjectId(raw_id)})
    except (InvalidId, TypeError):
        found = None
    if not found or found.get("status", "active") != "active" or found.get("role") not in VALID_ROLES:
        session.clear()
        return None
    g.current_user = found
    return found


def is_verified_official(user):
    """Return whether the existing admin approval workflow verified this account."""
    return (
        user.get("role") == "official"
        and user.get("status", "active") == "active"
        and isinstance(user.get("official_verified_at"), datetime)
        and isinstance(user.get("official_verified_by"), ObjectId)
    )


def auth_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return jsonify(error="Authentication required."), 401
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @auth_required
        def wrapped(*args, **kwargs):
            user = g.current_user
            if user.get("role") not in roles:
                return jsonify(error="You do not have permission to perform this action."), 403
            if user.get("role") == "official" and "official" in roles and not is_verified_official(user):
                return jsonify(error="Official access requires active administrator verification."), 403
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _valid_email(email):
    return isinstance(email, str) and len(email) <= 254 and EMAIL_RE.fullmatch(email.strip()) is not None


def _password_error(password):
    if not isinstance(password, str) or len(password) < 12:
        return "Password must be at least 12 characters."
    if len(password) > 256:
        return "Password must be 256 characters or fewer."
    return None


@auth_bp.get("/csrf")
def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return jsonify(csrf_token=token)


@auth_bp.post("/register")
def register():
    data = _json_object()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    full_name = data.get("full_name", "").strip() if isinstance(data.get("full_name", ""), str) else ""
    email = data.get("email", "").strip().lower() if isinstance(data.get("email", ""), str) else ""
    password = data.get("password")
    if not full_name or len(full_name) > 120:
        return jsonify(error="Full name is required (maximum 120 characters)."), 400
    if not _valid_email(email):
        return jsonify(error="Enter a valid email address."), 400
    password_error = _password_error(password)
    if password_error:
        return jsonify(error=password_error), 400
    users = db()["users"]
    if users.find_one({"email": email}):
        return jsonify(error="An account with that email already exists."), 409
    user = {"full_name": full_name, "email": email,
            "password_hash": generate_password_hash(password), "role": "citizen",
            "status": "active", "created_at": datetime.now(timezone.utc)}
    try:
        inserted = users.insert_one(user)
    except DuplicateKeyError:
        return jsonify(error="An account with that email already exists."), 409
    user["_id"] = inserted.inserted_id
    session.clear()
    session.permanent = True
    session["user_id"] = user_id(user)
    session["csrf_token"] = secrets.token_urlsafe(32)
    audit("citizen_registered", "user", user["_id"], {"role": "citizen"})
    return jsonify(success=True, user=public_user(user), csrf_token=session["csrf_token"]), 201


@auth_bp.post("/login")
def login():
    data = _json_object()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    email = data.get("email", "").strip().lower() if isinstance(data.get("email", ""), str) else ""
    password = data.get("password")
    if not _valid_email(email) or not isinstance(password, str) or len(password) > 256:
        return jsonify(error="Email or password is incorrect."), 401
    user = db()["users"].find_one({"email": email})
    try:
        valid_password = bool(user and check_password_hash(user.get("password_hash", ""), password))
    except (TypeError, ValueError):
        valid_password = False
    if not user or user.get("status", "active") != "active" or not valid_password:
        return jsonify(error="Email or password is incorrect."), 401
    session.clear()
    session.permanent = True
    session["user_id"] = user_id(user)
    session["csrf_token"] = secrets.token_urlsafe(32)
    audit("login", "user", user["_id"])
    return jsonify(success=True, user=public_user(user), csrf_token=session["csrf_token"])


@auth_bp.post("/logout")
@auth_required
def logout():
    user = g.current_user
    audit("logout", "user", user["_id"])
    session.clear()
    return jsonify(success=True)


@auth_bp.get("/me")
@auth_required
def me():
    return jsonify(user=public_user(g.current_user))


@auth_bp.patch("/profile")
@roles_required("citizen", "official", "admin")
def update_profile():
    data = _json_object()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    full_name = data.get("full_name")
    if not isinstance(full_name, str) or not full_name.strip() or len(full_name.strip()) > 120:
        return jsonify(error="Full name is required (maximum 120 characters)."), 400
    value = full_name.strip()
    db()["users"].update_one({"_id": g.current_user["_id"]}, {"$set": {
        "full_name": value, "profile_updated_at": datetime.now(timezone.utc),
    }})
    g.current_user["full_name"] = value
    audit("profile_updated", "user", g.current_user["_id"], {"fields": ["full_name"]})
    return jsonify(success=True, user=public_user(g.current_user))


@auth_bp.post("/official-access-requests")
@roles_required("citizen")
def request_official_access():
    data = _json_object()
    if data is None:
        return jsonify(error="Send a JSON object."), 400
    fields = ("employee_id", "department", "designation", "verification_information")
    values = {key: data.get(key, "").strip() if isinstance(data.get(key, ""), str) else "" for key in fields}
    if any(not values[key] for key in fields):
        return jsonify(error="Employee ID, department, designation, and supporting verification information are required."), 400
    if any(len(value) > 2000 for value in values.values()):
        return jsonify(error="Request fields must be 2,000 characters or fewer."), 400
    requests = db()["official_access_requests"]
    existing = requests.find_one({"user_id": g.current_user["_id"], "status": "pending"})
    if existing:
        return jsonify(error="You already have a pending official access request."), 409
    record = {**values, "user_id": g.current_user["_id"], "status": "pending",
              "created_at": datetime.now(timezone.utc)}
    try:
        inserted = requests.insert_one(record)
    except DuplicateKeyError:
        return jsonify(error="You already have a pending official access request."), 409
    audit("official_access_requested", "official_access_request", inserted.inserted_id)
    return jsonify(success=True, request={"id": str(inserted.inserted_id), "status": "pending"}), 201


@auth_bp.get("/official-access-requests/mine")
@roles_required("citizen")
def my_official_requests():
    rows = db()["official_access_requests"].find({"user_id": g.current_user["_id"]}).sort("created_at", -1)
    return jsonify([{"id": str(row["_id"]), "status": row["status"], "department": row["department"],
                     "created_at": row["created_at"].isoformat(), "decision_notes": row.get("decision_notes")} for row in rows])


@admin_bp.get("/official-access-requests")
@roles_required("admin")
def list_official_requests():
    status = request.args.get("status", "pending")
    if status not in {"pending", "approved", "rejected", "all"}:
        return jsonify(error="Invalid request status."), 400
    query = {} if status == "all" else {"status": status}
    rows = db()["official_access_requests"].find(query).sort("created_at", -1).limit(200)
    users = db()["users"]
    return jsonify([{"id": str(row["_id"]), "user_id": str(row["user_id"]),
                     "full_name": (users.find_one({"_id": row["user_id"]}) or {}).get("full_name", "Unknown user"),
                     "email": (users.find_one({"_id": row["user_id"]}) or {}).get("email", ""),
                     "employee_id": row["employee_id"], "department": row["department"],
                     "designation": row["designation"], "verification_information": row["verification_information"],
                     "status": row["status"], "created_at": row["created_at"].isoformat()} for row in rows])


@admin_bp.post("/official-access-requests/<request_id>/decision")
@roles_required("admin")
def decide_official_request(request_id):
    try:
        oid = ObjectId(request_id)
    except (InvalidId, TypeError):
        return jsonify(error="Invalid request ID."), 400
    data = _json_object()
    decision = data.get("decision") if data else None
    if not isinstance(decision, str) or decision not in {"approve", "reject"}:
        return jsonify(error="Decision must be 'approve' or 'reject'."), 400
    requests = db()["official_access_requests"]
    record = requests.find_one({"_id": oid, "status": "pending"})
    if not record:
        return jsonify(error="Pending official access request not found."), 404
    if record["user_id"] == g.current_user["_id"]:
        return jsonify(error="Administrators cannot approve their own official access request."), 403
    update = {"status": "rejected", "decided_at": datetime.now(timezone.utc),
              "decided_by": g.current_user["_id"], "decision_notes": str(data.get("notes", ""))[:2000]}
    if decision == "approve":
        try:
            from .departments import find_department
        except ImportError:  # direct ``python backend/app.py`` execution
            from departments import find_department
        method = data.get("verification_method", "")
        notes = data.get("verification_notes", "")
        department_id = data.get("department_id")
        department_name = data.get("department", record["department"])
        independently_verified = data.get("independently_verified") is True
        if (not independently_verified or not isinstance(method, str) or method not in INDEPENDENT_VERIFICATION_METHODS
                or not isinstance(notes, str) or not notes.strip()):
            return jsonify(error="Approval requires independent verification, its method, and verification notes."), 400
        selected_department = None
        if isinstance(department_id, str) and department_id:
            selected_department = find_department(db(), department_id=department_id, active_only=True)
        elif isinstance(department_name, str) and department_name.strip():
            selected_department = find_department(db(), name=department_name, active_only=True)
        if not selected_department:
            return jsonify(error="Choose an active department from the registry for official access."), 400
        department = selected_department["name"]
        department_id = selected_department["department_id"]
        user_result = db()["users"].update_one({"_id": record["user_id"], "role": "citizen", "status": "active"},
                                               {"$set": {"role": "official", "department": department,
                                                          "department_id": department_id,
                                                          "official_verified_at": datetime.now(timezone.utc),
                                                          "official_verified_by": g.current_user["_id"]}})
        if user_result.matched_count != 1:
            return jsonify(error="The requesting account is no longer an active citizen account."), 409
        update.update(status="approved", verification_method=method.strip()[:160],
                      verification_notes=notes.strip()[:2000], independently_verified=True,
                      approved_department=department, approved_department_id=department_id)
    else:
        notes = data.get("notes")
        if not isinstance(notes, str) or not notes.strip():
            return jsonify(error="A reason is required to reject an official access request."), 400
        if len(notes.strip()) > 2000:
            return jsonify(error="Rejection reason must be 2,000 characters or fewer."), 400
        update["decision_notes"] = notes.strip()
    changed = requests.update_one({"_id": oid, "status": "pending"}, {"$set": update})
    if changed.matched_count != 1:
        if decision == "approve":
            db()["users"].update_one({"_id": record["user_id"], "role": "official",
                                      "official_verified_by": g.current_user["_id"]},
                                     {"$set": {"role": "citizen"},
                                      "$unset": {"department": "", "department_id": "",
                                                 "official_verified_at": "", "official_verified_by": ""}})
        return jsonify(error="This request was already decided."), 409
    audit("official_access_approved" if decision == "approve" else "official_access_rejected", "official_access_request", oid,
          {"user_id": str(record["user_id"]), "department": update.get("approved_department"),
           "department_id": update.get("approved_department_id")})
    return jsonify(success=True, status=update["status"])
