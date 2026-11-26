"""Fail-closed validation for the production WSGI entrypoint."""
from urllib.parse import urlsplit


def validate_production_environment(environ):
    """Return configuration errors without exposing secret values."""
    errors = []
    if environ.get("NODAL_ENV", "").strip().lower() != "production":
        errors.append("NODAL_ENV must be set to production.")

    secret = environ.get("NODAL_SECRET_KEY", "")
    if len(secret) < 32 or secret.lower().startswith(("replace-", "change-me", "your-secret")):
        errors.append("NODAL_SECRET_KEY must be a non-placeholder secret of at least 32 characters.")

    mongo_uri = environ.get("MONGO_URI", "").strip()
    if not mongo_uri:
        errors.append("MONGO_URI must be explicitly configured.")
    else:
        try:
            parsed = urlsplit(mongo_uri)
            if parsed.scheme not in {"mongodb", "mongodb+srv"} or not parsed.netloc:
                errors.append("MONGO_URI must be a valid MongoDB connection URI.")
        except ValueError:
            errors.append("MONGO_URI must be a valid MongoDB connection URI.")

    database_name = environ.get("NODAL_DB_NAME", "").strip()
    if not database_name:
        errors.append("NODAL_DB_NAME must be explicitly configured for production.")
    if database_name in {"nodal_phase7_audit", "nodal_phase8_audit"}:
        errors.append("Production WSGI startup cannot target an audit database.")

    audit_mode = environ.get("NODAL_AUDIT_MODE", "false").strip().lower()
    if audit_mode not in {"", "0", "false", "no", "off"}:
        errors.append("NODAL_AUDIT_MODE must be disabled for production.")

    origins = [origin.strip() for origin in environ.get("NODAL_CORS_ORIGINS", "").split(",") if origin.strip()]
    if not origins or "*" in origins:
        errors.append("NODAL_CORS_ORIGINS must explicitly list trusted production origins; wildcards are not allowed.")
    else:
        for origin in origins:
            try:
                parsed = urlsplit(origin)
                valid_port = parsed.port is None or 1 <= parsed.port <= 65535
            except ValueError:
                parsed = None
                valid_port = False
            if (parsed is None or parsed.scheme != "https" or not parsed.netloc or not parsed.hostname
                    or parsed.username or parsed.password or not valid_port
                    or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                errors.append("Production CORS entries must be HTTPS origins without paths, queries, or fragments.")
                break
            if "localhost" in parsed.hostname.lower() or parsed.hostname in {"127.0.0.1", "::1"}:
                errors.append("Production CORS origins cannot include localhost development origins.")
                break

    return errors
