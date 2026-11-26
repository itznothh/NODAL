"""One-time first-admin bootstrap. No HTTP route exposes this capability."""
import os
import secrets
import argparse
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

try:
    from .auth import _password_error, _valid_email
except ImportError:  # direct script execution
    from auth import _password_error, _valid_email


def create_first_admin(database, email, password, full_name="NODAL Administrator"):
    email = email.strip().lower() if isinstance(email, str) else ""
    if not _valid_email(email):
        raise ValueError("NODAL_BOOTSTRAP_ADMIN_EMAIL must be a valid email address.")
    error = _password_error(password)
    if error:
        raise ValueError(error)
    users = database["users"]
    users.create_index("email", unique=True)
    lock_token = secrets.token_urlsafe(24)
    try:
        database["bootstrap_locks"].insert_one({"_id": "first_admin", "token": lock_token})
    except DuplicateKeyError as exc:
        raise RuntimeError("First-admin bootstrap has already run or is in progress.") from exc
    try:
        if users.find_one({"role": "admin"}):
            raise RuntimeError("An administrator already exists; bootstrap is disabled.")
        if users.find_one({"email": email}):
            raise RuntimeError("That email already belongs to an account.")
        result = users.insert_one({"full_name": full_name.strip()[:120], "email": email,
                                   "password_hash": generate_password_hash(password), "role": "admin",
                                   "status": "active", "bootstrap_created": True})
        return result.inserted_id
    except Exception:
        database["bootstrap_locks"].delete_one({"_id": "first_admin", "token": lock_token})
        raise


def resolve_database_target(database_argument, environ):
    """Require the CLI target to match an explicit process database setting."""
    target = database_argument.strip() if isinstance(database_argument, str) else ""
    configured = environ.get("NODAL_DB_NAME", "").strip()
    mongo_uri = environ.get("MONGO_URI", "").strip()
    if not target:
        raise ValueError("Pass an explicit --database target.")
    if not configured:
        raise ValueError("NODAL_DB_NAME must be explicitly configured.")
    if configured != target:
        raise ValueError("--database must exactly match NODAL_DB_NAME.")
    if not mongo_uri:
        raise ValueError("MONGO_URI must be explicitly configured.")
    return target, mongo_uri


def main(argv=None, input_fn=input):
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    parser = argparse.ArgumentParser(description="Create the first NODAL administrator in an explicitly selected database.")
    parser.add_argument("--database", required=True, help="Database name; must match NODAL_DB_NAME exactly")
    args = parser.parse_args(argv)
    email = os.getenv("NODAL_BOOTSTRAP_ADMIN_EMAIL", "")
    password = os.getenv("NODAL_BOOTSTRAP_ADMIN_PASSWORD", "")
    full_name = os.getenv("NODAL_BOOTSTRAP_ADMIN_NAME", "NODAL Administrator")
    if not email or not password:
        raise SystemExit("Set NODAL_BOOTSTRAP_ADMIN_EMAIL and NODAL_BOOTSTRAP_ADMIN_PASSWORD before running bootstrap.")
    try:
        database_name, mongo_uri = resolve_database_target(args.database, os.environ)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Administrator will be created in MongoDB database: {database_name}")
    if input_fn(f"Type {database_name} to confirm: ").strip() != database_name:
        raise SystemExit("Database confirmation did not match; no administrator was created.")
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        admin_id = create_first_admin(client[database_name], email, password, full_name)
        print(f"Created first administrator account {email} ({admin_id}). Remove bootstrap credentials from the environment.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
