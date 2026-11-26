#!/usr/bin/env python
"""Prepare synthetic Phase 8 showcase records through the local NODAL API.

This program is intentionally not imported by Flask and never connects to
MongoDB directly. It targets only the explicitly confirmed local Phase 8 API.
Synthetic official access requests remain pending; this tool never fabricates
independent verification or promotes a synthetic identity.
"""
from __future__ import annotations

import getpass
import json
import os
import secrets
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from http.cookiejar import CookieJar


API_BASE = "http://127.0.0.1:5000"
TARGET_DATABASE = "nodal_phase8_audit"
TARGET_MONGO_URI = "mongodb://127.0.0.1:27017"
ADMIN_CREDENTIALS = Path(r"C:\Users\shiva\AppData\Local\Temp\nodal-phase8-audit-credentials.json")
MARKER = "[SYNTHETIC NODAL SHOWCASE - NOT A VERIFIED CIVIC REPORT]"

PEOPLE = (
    {"key": "citizen-1", "role": "citizen", "name": "NODAL Demo Citizen", "email": "demo-citizen@nodal.test"},
    {"key": "citizen-2", "role": "citizen", "name": "NODAL Demo Citizen 2", "email": "demo-citizen-2@nodal.test"},
    {"key": "official-stormwater", "role": "citizen", "requested_role": "official",
     "name": "NODAL Demo Official", "email": "demo-official@nodal.test",
     "department": "Stormwater Drainage", "designation": "Demonstration Infrastructure Officer",
     "employee_id": "DEMO-ONLY-NOT-A-REAL-EMPLOYEE-ID"},
    {"key": "official-streetlight", "role": "citizen", "requested_role": "official",
     "name": "NODAL Demo Lighting Official", "email": "demo-streetlight@nodal.test",
     "department": "Street Lighting", "designation": "Demonstration Infrastructure Officer",
     "employee_id": "DEMO-ONLY-LIGHTING-NOT-REAL"},
    {"key": "official-road", "role": "citizen", "requested_role": "official",
     "name": "NODAL Demo Roads Official", "email": "demo-road@nodal.test",
     "department": "Road Infrastructure", "designation": "Demonstration Infrastructure Officer",
     "employee_id": "DEMO-ONLY-ROADS-NOT-REAL"},
)

# These fixtures use only fields accepted by POST /complaints. Status and
# assignment values are applied later through the existing admin/official APIs.
COMPLAINTS = (
    {"key": "road-submitted", "citizen": "citizen-1", "category": "pothole",
     "description": "Large damaged road surface on a residential lane near Malleshwaram 8th Cross; synthetic report for interface demonstration.",
     "lat": 13.0067, "lng": 77.5707, "stage": "submitted", "image": False},
    {"key": "garbage-department", "citizen": "citizen-2", "category": "garbage",
     "description": "Overflowing collection point near Jayanagar 4th Block bus stop; synthetic report for interface demonstration.",
     "lat": 12.9250, "lng": 77.5838, "stage": "department_assigned", "department_id": "solid-waste-management"},
    {"key": "drain-assigned", "citizen": "citizen-1", "category": "drainage",
     "description": "Blocked stormwater drain near Indiranagar 12th Main; synthetic report for interface demonstration.",
     "lat": 12.9784, "lng": 77.6408, "stage": "official_assigned", "department_id": "stormwater-drainage",
     "official_email": "demo-official@nodal.test"},
    {"key": "streetlight-department", "citizen": "citizen-2", "category": "streetlight",
     "description": "Non-functional streetlight near Basavanagudi residential streets; synthetic report for interface demonstration.",
     "lat": 12.9435, "lng": 77.5680, "stage": "in_progress", "department_id": "street-lighting",
     "official_email": "demo-streetlight@nodal.test"},
    {"key": "water-leak-department", "citizen": "citizen-1", "category": "water_leak",
     "description": "Water leakage beside a residential road near Rajajinagar; synthetic report for interface demonstration.",
     "lat": 13.0102, "lng": 77.5550, "stage": "department_assigned", "department_id": "water-supply"},
    {"key": "waterlogging-progress", "citizen": "citizen-2", "category": "waterlogging",
     "description": "Rainwater pooling at a junction near Koramangala 5th Block; synthetic report for interface demonstration.",
     "lat": 12.9345, "lng": 77.6150, "stage": "resolution_submitted", "department_id": "stormwater-drainage",
     "official_email": "demo-official@nodal.test", "image": True},
    {"key": "waterlogging-review", "citizen": "citizen-1", "category": "waterlogging",
     "description": "Waterlogging after rainfall along a service road in HSR Layout Sector 2; synthetic report for interface demonstration.",
     "lat": 12.9121, "lng": 77.6446, "stage": "disputed", "department_id": "stormwater-drainage",
     "official_email": "demo-official@nodal.test", "image": True},
    {"key": "footpath-department-assigned", "legacy_keys": ("footpath-resolved",),
     "citizen": "citizen-2", "category": "damaged_infrastructure",
     "description": "Uneven damaged footpath near a residential block in Vijayanagar; synthetic report for interface demonstration.",
     "lat": 12.9700, "lng": 77.5350, "stage": "department_assigned", "department_id": "road-infrastructure",
     "assignment_reason": "Synthetic demo routing override: footpath maintenance is routed to the prototype Road Infrastructure group for this fixture only; this is not a verified government assignment.",
     "image": False},
)


class SetupError(RuntimeError):
    pass


class ApiError(SetupError):
    def __init__(self, method: str, path: str, status: int, message: str):
        super().__init__(f"{method} {path} returned HTTP {status}: {message}")
        self.status = status


class ApiClient:
    def __init__(self):
        self.cookies = CookieJar()
        # Do not route loopback requests through a machine proxy.
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))
        self.csrf_token = None

    def request(self, method: str, path: str, payload=None, multipart=None, expect_json=True):
        headers = {"Accept": "application/json"}
        if not expect_json:
            headers["Accept"] = "*/*"
        body = None
        if method in {"POST", "PATCH", "PUT", "DELETE"}:
            if not self.csrf_token:
                self.request("GET", "/auth/csrf")
            headers["X-CSRF-Token"] = self.csrf_token
        if multipart is not None:
            boundary = "nodal-" + secrets.token_hex(16)
            chunks = []
            for name, value in multipart["fields"].items():
                chunks.extend((f"--{boundary}\r\n".encode(),
                               f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                               str(value).encode("utf-8"), b"\r\n"))
            image_name, image_bytes = multipart["image"]
            chunks.extend((f"--{boundary}\r\n".encode(),
                           f'Content-Disposition: form-data; name="image"; filename="{image_name}"\r\n'.encode(),
                           b"Content-Type: image/png\r\n\r\n", image_bytes, b"\r\n",
                           f"--{boundary}--\r\n".encode()))
            body = b"".join(chunks)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(API_BASE + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=12) as response:
                raw = response.read()
                if not expect_json:
                    mime_type = response.headers.get_content_type().lower()
                    return response.status, raw, mime_type
                data = json.loads(raw.decode("utf-8")) if raw else None
                if isinstance(data, dict) and data.get("csrf_token"):
                    self.csrf_token = data["csrf_token"]
                return response.status, data
        except HTTPError as error:
            raw = error.read()
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = {}
            message = data.get("error", "request rejected") if isinstance(data, dict) else "request rejected"
            raise ApiError(method, path, error.code, str(message)) from None
        except (URLError, TimeoutError, OSError) as error:
            raise SetupError(f"Cannot reach the local NODAL API at {API_BASE}: {error}") from None

    def json(self, method: str, path: str, payload=None):
        return self.request(method, path, payload=payload)[1]

    def login(self, email: str, password: str):
        self.request("GET", "/auth/csrf")
        _, result = self.request("POST", "/auth/login", {"email": email, "password": password})
        return result["user"]


def require_target_environment():
    expected = {
        "NODAL_AUDIT_MODE": "true",
        "NODAL_DB_NAME": TARGET_DATABASE,
        "MONGO_URI": TARGET_MONGO_URI,
        "NODAL_ENV": "development",
    }
    mismatches = [key for key, value in expected.items() if os.environ.get(key) != value]
    if mismatches:
        raise SetupError("Refusing to proceed; this script's environment does not exactly match: " + ", ".join(mismatches))
    parsed = urlsplit(TARGET_MONGO_URI)
    if (parsed.scheme != "mongodb" or parsed.hostname != "127.0.0.1" or parsed.port != 27017
            or parsed.username or parsed.password or parsed.path not in {"", "/"}):
        raise SetupError("The fixed MongoDB URI failed validation.")
    parsed_api = urlsplit(API_BASE)
    if parsed_api.scheme != "http" or parsed_api.hostname != "127.0.0.1" or parsed_api.port != 5000:
        raise SetupError("The API destination must remain local at 127.0.0.1:5000.")


def confirm_target():
    print("This tool uses only the local API at 127.0.0.1:5000; it never connects to MongoDB directly.")
    if input("Type AUDIT to confirm audit mode: ").strip() != "AUDIT":
        raise SetupError("Audit-mode confirmation did not match.")
    if input(f"Type {TARGET_DATABASE} to confirm the database name: ").strip() != TARGET_DATABASE:
        raise SetupError("Database confirmation did not match.")
    phrase = f"I VERIFIED THE LIVE FLASK TARGET IS {TARGET_DATABASE}"
    if input(f"{phrase}: ").strip() != phrase:
        raise SetupError("Live Flask target confirmation did not match.")


def credentials_output_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise SetupError("LOCALAPPDATA is unavailable; refusing to save credentials to an unknown location.")
    destination = Path(r"C:\Users\shiva\AppData\Local\Temp\nodal-phase8-showcase-credentials.json").resolve()
    expected = (Path(local_app_data) / "Temp" / "nodal-phase8-showcase-credentials.json").resolve()
    if destination != expected:
        raise SetupError("The required credentials path does not match this Windows user's LOCALAPPDATA Temp directory.")
    repo_root = Path(__file__).resolve().parents[1]
    if destination == repo_root or repo_root in destination.parents:
        raise SetupError("Credential output unexpectedly resolves inside the repository.")
    return destination


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SetupError(f"Required credentials file is missing: {path}") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SetupError(f"Could not safely read credentials file: {path}") from None


def extract_admin_credentials(document):
    candidates = [document]
    if isinstance(document, dict):
        candidates.extend((document.get("admin"), document.get("accounts", {}).get("admin")
                           if isinstance(document.get("accounts"), dict) else None))
    for item in candidates:
        if isinstance(item, dict):
            email = item.get("email") or item.get("admin_email")
            password = item.get("password") or item.get("admin_password")
            if isinstance(email, str) and isinstance(password, str) and email and password:
                return email, password
    raise SetupError("The existing admin credentials file must contain admin email and password fields.")


def load_showcase_credentials(path: Path, excluded_emails=()):
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SetupError("Existing showcase credentials file is unreadable; no credentials were changed.") from None
    accounts = document.get("accounts", {}) if isinstance(document, dict) else {}
    excluded = {str(email).strip().lower() for email in excluded_emails}

    def keep_account(key, row):
        email = str(row.get("email") or key).strip().lower()
        return email not in excluded and row.get("role") != "admin"

    if isinstance(accounts, list):
        return {row["email"].lower(): row for row in accounts
                if isinstance(row, dict) and row.get("email") and keep_account(row["email"], row)}
    if isinstance(accounts, dict):
        return {str(email).lower(): row for email, row in accounts.items()
                if isinstance(row, dict) and keep_account(email, row)}
    raise SetupError("Existing showcase credential structure is not recognized.")


def save_credentials(path: Path, database_name: str, accounts: dict):
    expected_emails = {person["email"].lower() for person in PEOPLE}
    if any(email.lower() not in expected_emails or row.get("role") == "admin"
           for email, row in accounts.items()):
        raise SetupError("Refusing to save non-showcase or administrator credentials in the showcase credentials file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"database": database_name, "api_base": API_BASE,
               "updated_at": datetime.now(timezone.utc).isoformat(), "accounts": accounts}
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=".nodal-showcase-", suffix=".tmp", delete=False) as temp:
            temp_name = temp.name
            json.dump(payload, temp, indent=2)
            temp.write("\n")
        os.replace(temp_name, path)
        try:
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass
    except OSError:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise SetupError("Could not write the showcase credentials file.") from None


def ensure_account(person: dict, accounts: dict, credential_path: Path):
    email = person["email"].lower()
    existing = accounts.get(email)
    if existing:
        password = existing.get("password")
        if not isinstance(password, str) or not password:
            raise SetupError(f"Credentials for existing account {email} are incomplete; no password was reset.")
        client = ApiClient()
        user = client.login(email, password)
        existing.update(role=user["role"], department=user.get("department"),
                        requested_role=person.get("requested_role"))
        return client, user, False

    password = secrets.token_urlsafe(32)
    client = ApiClient()
    try:
        client.request("GET", "/auth/csrf")
        _, result = client.request("POST", "/auth/register", {
            "full_name": person["name"], "email": email, "password": password,
        })
    except ApiError as error:
        if error.status == 409:
            raise SetupError(f"Account {email} already exists but is not in the showcase credentials file. Add its valid credentials there to reuse it; the account was not changed.") from None
        raise
    user = result["user"]
    accounts[email] = {"role": user["role"], "email": email, "password": password,
                       "department": None, "requested_role": person.get("requested_role")}
    save_credentials(credential_path, TARGET_DATABASE, accounts)
    return client, user, True


def make_demo_png(kind: str) -> bytes:
    """Make a clearly synthetic diagram in memory; no image file is created."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return b""
    image = Image.new("RGB", (640, 360), "#f4f0e7")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 230, 640, 360), fill="#68746d")
    draw.rectangle((0, 0, 640, 230), fill="#dce4d7")
    if kind == "drain":
        for x in range(150, 500, 42):
            draw.line((x, 210, x, 305), fill="#343a40", width=8)
        draw.rectangle((115, 200, 525, 318), outline="#263f35", width=10)
        draw.ellipse((260, 225, 390, 310), fill="#263f35")
    else:
        draw.polygon([(205, 260), (280, 232), (365, 245), (430, 282), (370, 315), (275, 305)], fill="#263f35")
        draw.polygon([(80, 250), (118, 180), (156, 250)], fill="#d97757")
        draw.polygon([(480, 250), (518, 180), (556, 250)], fill="#d97757")
    font = ImageFont.load_default()
    draw.rounded_rectangle((16, 16, 265, 55), radius=4, fill="#fffdf8", outline="#d97757", width=2)
    draw.text((26, 28), "SYNTHETIC DEMO - NOT A REAL INCIDENT", fill="#263f35", font=font)
    import io
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def describe_existing_state(admin: ApiClient, credential_accounts: dict):
    departments = admin.json("GET", "/admin/departments")
    officials = admin.json("GET", "/admin/officials")
    requests = admin.json("GET", "/admin/official-access-requests?status=all")
    complaints = admin.json("GET", "/complaints")
    overview = admin.json("GET", "/admin/overview")
    if len(complaints) + len(COMPLAINTS) > 500:
        raise SetupError("The API's 500-item admin complaint cap could hide fixture markers after insertion; no showcase complaints were created.")
    print(f"Read existing audit data through admin APIs: {len(departments)} departments, {len(officials)} verified officials, {len(requests)} access requests, {len(complaints)} complaints.")
    print(f"Admin overview loaded for {overview.get('total_complaints', 'unknown')} existing complaints.")
    return departments, officials, requests, complaints


def validate_existing_fixture_markers(complaints: list):
    """Reject ambiguous fixture markers before any showcase write is attempted."""
    marker_owners = {}
    for fixture in COMPLAINTS:
        for key in (fixture["key"], *fixture.get("legacy_keys", ())):
            previous = marker_owners.setdefault(key, fixture["key"])
            if previous != fixture["key"]:
                raise SetupError(f"Fixture marker key {key!r} is configured for multiple fixtures.")

    matches_by_fixture = {fixture["key"]: [] for fixture in COMPLAINTS}
    multi_fixture_complaints = []
    for complaint in complaints:
        description = str(complaint.get("description", ""))
        found = {marker_owners[key] for key in marker_owners if f"[fixture:{key}]" in description}
        if len(found) > 1:
            multi_fixture_complaints.append(sorted(found))
        for fixture_key in found:
            matches_by_fixture[fixture_key].append(complaint)

    duplicated_fixture_keys = sorted(
        fixture_key for fixture_key, matches in matches_by_fixture.items() if len(matches) > 1
    )
    if multi_fixture_complaints or duplicated_fixture_keys:
        conflicts = []
        if duplicated_fixture_keys:
            conflicts.append("fixture keys found in multiple existing complaints: "
                             + ", ".join(duplicated_fixture_keys))
        if multi_fixture_complaints:
            involved = sorted({key for group in multi_fixture_complaints for key in group})
            conflicts.append("single complaints contain markers for multiple fixtures: "
                             + ", ".join(involved))
        raise SetupError("Conflicting existing showcase markers; no accounts, requests, or complaints were created: "
                         + "; ".join(conflicts))

    return {fixture_key: matches[0] for fixture_key, matches in matches_by_fixture.items() if matches}


def ensure_official_request(person: dict, client: ApiClient, user: dict, admin_requests: list):
    if user.get("email", "").strip().lower() != person["email"].lower():
        raise SetupError(f"Logged-in identity does not match the intended official request fixture {person['email']}.")
    if user.get("full_name", "").strip() != person["name"]:
        raise SetupError(f"Account name does not match the intended official request fixture {person['email']}.")
    if user.get("role") == "official":
        return None
    if user.get("role") != "citizen":
        raise SetupError(f"The requested official account {person['email']} is not a citizen account and cannot use the access-request workflow.")
    mine = client.json("GET", "/auth/official-access-requests/mine")
    pending = [row for row in mine if row.get("status") == "pending"]
    if pending:
        admin_pending = next((row for row in admin_requests
                              if row.get("email", "").strip().lower() == person["email"].lower()
                              and row.get("status") == "pending"), None)
        if (not admin_pending
                or admin_pending.get("full_name", "").strip() != person["name"]
                or admin_pending.get("employee_id", "").strip() != person["employee_id"]
                or admin_pending.get("department", "").strip().casefold() != person["department"].casefold()
                or admin_pending.get("designation", "").strip() != person["designation"]):
            raise SetupError(f"Pending request for {person['email']} does not match the intended identity and department; it was not reused or changed.")
        return "pending"
    if any(row.get("status") == "approved" for row in mine):
        raise SetupError("The official request says approved but the account is still a citizen; admin review is inconsistent.")
    payload = {
        "employee_id": person["employee_id"],
        "department": person["department"],
        "designation": person["designation"],
        "verification_information": "Synthetic NODAL showcase identity only. Not a real public employee and not evidence of government employment.",
    }
    result = client.json("POST", "/auth/official-access-requests", payload)
    return result.get("request", {}).get("status", "pending")


def active_department(departments, department_id):
    return next((row for row in departments if row.get("department_id") == department_id and row.get("active")), None)


def make_complaint(citizen_client: ApiClient, fixture: dict):
    description = f"{MARKER} [fixture:{fixture['key']}] {fixture['description']}"
    fields = {"description": description, "category": fixture["category"],
              "lat": fixture["lat"], "lng": fixture["lng"]}
    if fixture.get("image"):
        png = make_demo_png("drain" if fixture["category"] in {"drainage", "waterlogging"} else "road")
        if png:
            return citizen_client.request("POST", "/complaints", multipart={
                "fields": fields, "image": (f"synthetic-{fixture['key']}.png", png),
            })[1]
        print(f"Pillow unavailable; image skipped for {fixture['key']}.")
    return citizen_client.json("POST", "/complaints", fields)


def ensure_assign(admin: ApiClient, complaint: dict, fixture: dict, official_row=None):
    if complaint.get("status") in {"resolved", "disputed"}:
        return complaint
    existing_department_id = complaint.get("department_id")
    existing_official_id = complaint.get("assigned_official_id")
    target_id = fixture.get("department_id")
    if not target_id:
        return complaint
    if existing_department_id == target_id and (not official_row or str(existing_official_id) == official_row.get("id")):
        return complaint
    payload = {"department_id": target_id, "reason": fixture.get("assignment_reason") or
               f"Synthetic showcase fixture {fixture['key']}; administrative routing is illustrative only."}
    if official_row:
        payload["official_id"] = official_row["id"]
    return admin.json("POST", f"/complaints/{complaint['_id']}/assign", payload)


def transition(client: ApiClient, complaint: dict, target: str, notes: str, evidence=None):
    if complaint.get("status") == target:
        return complaint
    payload = {"status": target, "notes": notes}
    if evidence is not None:
        payload["evidence"] = evidence
    return client.json("POST", f"/complaints/{complaint['_id']}/transition", payload)


def verify_access(admin, citizen_clients, official_clients, complaints_by_key):
    def verify_evidence(client, image, context):
        path = image.get("url")
        expected_mime = str(image.get("content_type", "")).split(";", 1)[0].strip().lower()
        if not path or not expected_mime:
            raise SetupError(f"{context} evidence metadata is missing its URL or recorded MIME type.")
        status, body, actual_mime = client.request("GET", path, expect_json=False)
        if status != 200 or not body:
            raise SetupError(f"{context} evidence access did not return a non-empty HTTP 200 response.")
        if actual_mime != expected_mime:
            raise SetupError(f"{context} evidence MIME type mismatch: expected {expected_mime}, got {actual_mime}.")

    # Each citizen should list only records created in that account's session.
    owner_ids = {key: set() for key in citizen_clients}
    for fixture in COMPLAINTS:
        complaint = complaints_by_key.get(fixture["key"])
        if complaint:
            owner_ids[fixture["citizen"]].add(complaint["_id"])
    for person_key, client in citizen_clients.items():
        visible = client.json("GET", "/complaints")
        if {row["_id"] for row in visible if row.get("description", "").find(MARKER) >= 0} != owner_ids[person_key]:
            raise SetupError(f"Citizen ownership verification failed for {person_key}.")
        other_ids = set().union(*(ids for key, ids in owner_ids.items() if key != person_key))
        for complaint_id in other_ids:
            try:
                client.request("GET", f"/complaints/{complaint_id}")
            except ApiError as error:
                if error.status == 404:
                    continue
                raise
            raise SetupError(f"Citizen {person_key} could read another citizen's complaint {complaint_id}.")
    all_visible = admin.json("GET", "/complaints")
    admin_ids = {row["_id"] for row in all_visible if MARKER in row.get("description", "")}
    expected_ids = {item["_id"] for item in complaints_by_key.values()}
    if admin_ids != expected_ids:
        raise SetupError("Admin showcase complaint visibility check failed.")
    for email, client in official_clients.items():
        allowed = client.json("GET", "/complaints")
        profile = next((p for p in PEOPLE if p["email"] == email), None)
        department = profile.get("department") if profile else None
        if department:
            for row in allowed:
                if MARKER in row.get("description", "") and row.get("department") != department and not row.get("assigned_to_viewer"):
                    raise SetupError(f"Official department-scope check failed for {email}.")
        for row in allowed:
            if MARKER not in row.get("description", ""):
                continue
            for image in row.get("images", []):
                verify_evidence(client, image, f"Official {email}")
    for key, complaint in complaints_by_key.items():
        if complaint.get("images"):
            owner_key = next((fixture["citizen"] for fixture in COMPLAINTS if fixture["key"] == key), None)
            if owner_key is None:
                continue
            owner = citizen_clients[owner_key]
            for image in complaint.get("images", []):
                path = image.get("url")
                verify_evidence(owner, image, "Complaint owner")
                for other_key, other_client in citizen_clients.items():
                    if other_key == owner_key:
                        continue
                    try:
                        other_client.request("GET", path, expect_json=False)
                    except ApiError as error:
                        if error.status == 404:
                            continue
                        raise
                    raise SetupError("Another citizen could retrieve synthetic evidence they do not own.")
                verify_evidence(admin, image, "Administrator")
    if official_clients:
        admin_rows = admin.json("GET", "/complaints")
        for email, client in official_clients.items():
            profile = next((p for p in PEOPLE if p["email"] == email), None)
            department = profile.get("department") if profile else None
            if not department:
                continue
            for row in admin_rows:
                if MARKER not in row.get("description", ""):
                    continue
                is_assigned = row.get("assigned_official_id") == next(
                    (entry.get("id") for entry in admin.json("GET", "/admin/officials")
                     if entry.get("email", "").lower() == email.lower()), None)
                if row.get("department") == department or is_assigned:
                    continue
                try:
                    client.request("GET", f"/complaints/{row['_id']}")
                except ApiError as error:
                    if error.status == 404:
                        continue
                    raise
                raise SetupError(f"Official {email} accessed an unrelated department complaint.")


def main():
    if os.name != "nt":
        raise SetupError("This local showcase script is intended for the specified Windows workstation.")
    require_target_environment()
    confirm_target()
    output_path = credentials_output_path()
    admin_email, admin_password = extract_admin_credentials(read_json(ADMIN_CREDENTIALS))
    accounts = load_showcase_credentials(output_path, excluded_emails={admin_email})
    synthetic_emails = {person["email"].lower() for person in PEOPLE}
    # Older iterations stored the admin in this output file. Remove that entry
    # from the next atomic write; the admin password remains only in this process.
    for email, entry in list(accounts.items()):
        if email == admin_email.lower() or entry.get("role") == "admin":
            accounts.pop(email, None)
        elif email not in synthetic_emails:
            raise SetupError(f"The existing credentials file contains an unrecognized account ({email}); it was not overwritten.")

    admin = ApiClient()
    if admin.json("GET", "/health").get("status") != "ok":
        raise SetupError("Local Flask health check did not return status=ok.")
    admin_user = admin.login(admin_email, admin_password)
    if admin_user.get("role") != "admin":
        raise SetupError("The preserved account did not authenticate as an administrator.")
    departments, verified_officials, requests, existing_complaints = describe_existing_state(admin, accounts)
    existing_by_marker = validate_existing_fixture_markers(existing_complaints)
    save_credentials(output_path, TARGET_DATABASE, accounts)
    needed_depts = {"solid-waste-management", "stormwater-drainage", "street-lighting", "water-supply", "road-infrastructure"}
    missing_departments = sorted(dept for dept in needed_depts if not active_department(departments, dept))
    if missing_departments:
        raise SetupError("Required active prototype departments are missing: " + ", ".join(missing_departments))

    citizen_clients = {}
    citizen_users = {}
    for person in (PEOPLE[0], PEOPLE[1]):
        client, user, created = ensure_account(person, accounts, output_path)
        if user.get("role") != "citizen":
            raise SetupError(f"Expected citizen role for {person['email']}.")
        citizen_clients[person["key"]] = client
        citizen_users[person["key"]] = user
        save_credentials(output_path, TARGET_DATABASE, accounts)
        print(f"{'Created' if created else 'Reused'} citizen account {person['email']}.")

    official_sessions = {}
    verified_by_email = {row.get("email", "").lower(): row for row in verified_officials}
    for official_person in PEOPLE[2:]:
        official_client, official_user, created = ensure_account(official_person, accounts, output_path)
        request_status = ensure_official_request(official_person, official_client, official_user, requests)
        official_row = verified_by_email.get(official_person["email"].lower())
        if official_user.get("role") == "official" and not official_row:
            raise SetupError(f"Account {official_person['email']} has official role but is absent from the admin verified-official directory.")
        if official_row:
            if official_row.get("department") != official_person["department"]:
                raise SetupError(f"Verified demo account {official_person['email']} has a different department; it was not changed.")
            approved_request = next((row for row in requests
                                     if row.get("email", "").strip().lower() == official_person["email"].lower()
                                     and row.get("status") == "approved"), None)
            if (not approved_request
                    or approved_request.get("full_name", "").strip() != official_person["name"]
                    or approved_request.get("employee_id", "").strip() != official_person["employee_id"]
                    or approved_request.get("department", "").strip().casefold()
                    != official_person["department"].casefold()
                    or approved_request.get("designation", "").strip() != official_person["designation"]):
                raise SetupError(
                    f"Verified account {official_person['email']} has no matching approved request identity and department; it was not reused.")
            logged_official = official_client.login(
                official_person["email"], accounts[official_person["email"].lower()]["password"])
            if logged_official.get("role") != "official":
                raise SetupError(f"Verified official credentials did not authenticate for {official_person['email']}.")
            accounts[official_person["email"].lower()].update(
                role="official", department=logged_official.get("department"), access_request_status="approved")
            official_sessions[official_person["email"]] = official_client
        else:
            accounts[official_person["email"].lower()].update(
                role="citizen", department=None, requested_role="official",
                access_request_status=request_status or "pending")
            print(f"{'Created' if created else 'Reused'} synthetic official access request for {official_person['email']} ({request_status or 'pending'}).")
        save_credentials(output_path, TARGET_DATABASE, accounts)

    if not official_sessions:
        print("All synthetic official requests remain unverified; no official access or lifecycle transition is attempted.")

    clients_by_person = {**citizen_clients}
    owners = {person["key"]: person["email"] for person in PEOPLE[:2]}
    complaints_by_key = dict(existing_by_marker)
    for fixture in COMPLAINTS:
        complaint = complaints_by_key.get(fixture["key"])
        citizen_client = clients_by_person[fixture["citizen"]]
        if complaint is not None and complaint.get("created_by") != citizen_users[fixture["citizen"]].get("id"):
            raise SetupError(f"Existing marker {fixture['key']} belongs to a different account; it was not modified.")
        if complaint is None:
            complaint = make_complaint(citizen_client, fixture)
        complaints_by_key[fixture["key"]] = complaint
        department_id = fixture.get("department_id")
        assigned_official = next((row for row in verified_officials
                                  if row.get("email", "").lower() == fixture.get("official_email", "").lower()), None)
        if fixture.get("official_email") and assigned_official is None:
            print(f"Individual assignment skipped for {fixture['key']}: no verified official in {department_id}; department routing may still be recorded.")
        complaint = ensure_assign(admin, complaint, fixture, assigned_official)
        complaints_by_key[fixture["key"]] = complaint

        status = complaint.get("status")
        officer = official_sessions.get(fixture.get("official_email"))
        authorized_officer = bool(officer and assigned_official
                                  and assigned_official.get("email", "").lower()
                                  == fixture.get("official_email", "").lower())
        if fixture["stage"] in {"in_progress", "resolution_submitted", "resolved", "resolution_rejected", "disputed"} and authorized_officer:
            if complaint.get("status") == "assigned":
                complaint = transition(officer, complaint, "in_progress",
                                       f"{MARKER} Synthetic progress update for {fixture['key']}.")
            if fixture["stage"] in {"resolution_submitted", "resolved", "resolution_rejected", "disputed"}:
                evidence_refs = [image.get("url") for image in complaint.get("images", []) if image.get("url")]
                status = complaint.get("status")
                if status == "in_progress":
                    if not evidence_refs:
                        print(f"NOT DEMONSTRATED: resolution for {fixture['key']} needs a real uploaded synthetic evidence image.")
                    else:
                        complaint = transition(officer, complaint, "resolution_submitted",
                                               f"{MARKER} Synthetic resolution notes for {fixture['key']}.", evidence_refs)
                if fixture["stage"] == "resolution_rejected" and complaint.get("status") == "resolution_submitted":
                    complaint = transition(admin, complaint, "in_progress",
                                           f"{MARKER} Synthetic admin rejection; further illustrative work is required.")
                if fixture["stage"] == "disputed":
                    if complaint.get("status") == "resolution_submitted":
                        complaint = transition(admin, complaint, "in_progress",
                                               f"{MARKER} Synthetic admin rejection; further illustrative work is required.")
                    if complaint.get("status") == "in_progress" and evidence_refs:
                        complaint = transition(officer, complaint, "resolution_submitted",
                                               f"{MARKER} Synthetic revised resolution after requested further work.", evidence_refs)
                if fixture["stage"] in {"resolved", "disputed"} and complaint.get("status") == "resolution_submitted" and evidence_refs:
                    complaint = transition(admin, complaint, "resolved",
                                           f"{MARKER} Admin review of synthetic resolution.", evidence_refs)
                if fixture["stage"] == "disputed" and complaint.get("status") == "resolved":
                    owner_client = citizen_clients[fixture["citizen"]]
                    complaint = transition(owner_client, complaint, "disputed",
                                           f"{MARKER} Synthetic citizen dispute for interface demonstration.")
        complaints_by_key[fixture["key"]] = complaint

    verify_access(admin, citizen_clients, official_sessions, complaints_by_key)
    expected_status = {
        "submitted": "submitted", "department_assigned": "assigned", "official_assigned": "assigned",
        "in_progress": "in_progress", "resolution_submitted": "resolution_submitted", "resolved": "resolved",
        "resolution_rejected": "in_progress", "disputed": "disputed",
    }
    incomplete = []
    for fixture in COMPLAINTS:
        actual = complaints_by_key[fixture["key"]].get("status")
        if actual != expected_status[fixture["stage"]]:
            incomplete.append(f"{fixture['key']}: expected {expected_status[fixture['stage']]}, got {actual}")
        if fixture["stage"] == "official_assigned" and not complaints_by_key[fixture["key"]].get("assigned_official_id"):
            incomplete.append(f"{fixture['key']}: department status exists without the requested individual official assignment")
        if fixture["stage"] == "disputed":
            actions = {event.get("action") for event in complaints_by_key[fixture["key"]].get("status_history", [])}
            for required_action in ("resolution_rejected", "resolution_approved", "resolution_disputed"):
                if required_action not in actions:
                    incomplete.append(f"{fixture['key']}: lifecycle history lacks {required_action}")
        requires_official = fixture["stage"] in {
            "official_assigned", "in_progress", "resolution_submitted", "resolved", "resolution_rejected", "disputed"
        }
        if requires_official and fixture.get("official_email") not in official_sessions:
            incomplete.append(
                f"{fixture['key']}: {fixture['stage']} cannot be demonstrated because no legitimately verified "
                f"official account and credentials are available for {fixture.get('department_id')}"
            )
    print(f"Processed {len(complaints_by_key)} tagged complaints through APIs.")
    for item in incomplete:
        print(f"NOT DEMONSTRATED: {item}")
    print(f"Credentials saved outside the repository: {output_path}")
    print("Synthetic records are not verified civic reports; no department contact or external verification was performed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SetupError as error:
        print(f"SETUP STOPPED: {error}", file=sys.stderr)
        raise SystemExit(2)
