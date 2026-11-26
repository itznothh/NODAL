"""Production WSGI entrypoint. Start with Waitress, never Flask's dev server."""
import os

try:
    from .deployment_config import validate_production_environment
except ImportError:  # ``waitress-serve backend.wsgi:app`` from repository root
    from deployment_config import validate_production_environment

configuration_errors = validate_production_environment(os.environ)
if configuration_errors:
    raise RuntimeError("Production configuration is invalid: " + " ".join(configuration_errors))

try:
    from .app import app
except ImportError:
    from app import app

app.debug = False
