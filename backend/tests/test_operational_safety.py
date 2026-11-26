"""Pure configuration tests; these never connect to MongoDB or run scripts."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app import app as flask_app
from backend.app import create_app
from backend.bootstrap_admin import resolve_database_target
from backend.deployment_config import validate_production_environment
from backend.seed import validate_seed_target


class ProductionConfigurationTests(unittest.TestCase):
    def valid_environment(self):
        return {
            "NODAL_ENV": "production",
            "NODAL_SECRET_KEY": "a-strong-random-secret-value-of-at-least-32-characters",
            "MONGO_URI": "mongodb://db.example.test:27017",
            "NODAL_DB_NAME": "nodal",
            "NODAL_AUDIT_MODE": "false",
            "NODAL_CORS_ORIGINS": "https://nodal.example.test,https://admin.example.test",
        }

    def test_valid_production_environment_passes(self):
        self.assertEqual(validate_production_environment(self.valid_environment()), [])

    def test_missing_and_weak_production_settings_fail_closed(self):
        environment = self.valid_environment()
        for key in ("NODAL_SECRET_KEY", "MONGO_URI", "NODAL_DB_NAME", "NODAL_CORS_ORIGINS"):
            candidate = dict(environment)
            candidate.pop(key)
            with self.subTest(key=key):
                self.assertTrue(validate_production_environment(candidate))
        for value in ("short", "replace-with-a-random-secret-before-use"):
            candidate = dict(environment, NODAL_SECRET_KEY=value)
            self.assertTrue(any("NODAL_SECRET_KEY" in error for error in validate_production_environment(candidate)))

    def test_audit_database_wildcard_and_http_origins_are_rejected(self):
        for updates in (
            {"NODAL_DB_NAME": "nodal_phase8_audit"},
            {"NODAL_CORS_ORIGINS": "*"},
            {"NODAL_CORS_ORIGINS": "http://nodal.example.test"},
            {"NODAL_AUDIT_MODE": "true"},
        ):
            with self.subTest(updates=updates):
                self.assertTrue(validate_production_environment({**self.valid_environment(), **updates}))

    def test_flask_factory_rejects_weak_production_secret(self):
        environment = {
            "NODAL_ENV": "production",
            "NODAL_SECRET_KEY": "short",
            "NODAL_AUDIT_MODE": "false",
        }
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
                create_app(database=object())

    def test_direct_flask_server_refuses_production(self):
        with patch.dict(os.environ, {"NODAL_ENV": "production"}, clear=False):
            with patch.object(flask_app, "run") as run:
                with self.assertRaisesRegex(SystemExit, "Refusing to start production"):
                    from backend.app import run_development_server
                    run_development_server(flask_app)
                run.assert_not_called()

    def test_wsgi_rejects_missing_config_before_importing_application(self):
        environment = dict(os.environ)
        for key in ("NODAL_SECRET_KEY", "MONGO_URI", "NODAL_DB_NAME", "NODAL_CORS_ORIGINS"):
            environment.pop(key, None)
        environment.update(NODAL_ENV="production", NODAL_AUDIT_MODE="false")
        check = """
import sys
try:
    import backend.wsgi
except RuntimeError as error:
    assert 'NODAL_SECRET_KEY' in str(error)
    assert 'backend.app' not in sys.modules
else:
    raise AssertionError('invalid WSGI configuration unexpectedly started')
"""
        result = subprocess.run([sys.executable, "-c", check], cwd=Path(__file__).resolve().parents[2],
                                env=environment, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_valid_wsgi_import_uses_deferred_mocked_mongo_and_debug_is_off(self):
        environment = {
            "NODAL_ENV": "production",
            "NODAL_SECRET_KEY": "a-strong-random-secret-value-of-at-least-32-characters",
            "MONGO_URI": "mongodb://127.0.0.1:27017",
            "NODAL_DB_NAME": "nodal_deploy_smoke_test",
            "NODAL_AUDIT_MODE": "false",
            "NODAL_CORS_ORIGINS": "https://nodal.example.test",
            "USERPROFILE": str(Path(__file__).resolve().parents[2]),
        }
        check = """
from unittest.mock import patch
with patch('pymongo.MongoClient') as factory:
    import backend.wsgi as wsgi
    assert wsgi.app.debug is False
    factory.assert_called_once()
    assert factory.call_args.kwargs.get('connect') is False
    assert not factory.return_value.admin.command.called
"""
        result = subprocess.run([sys.executable, "-c", check], cwd=Path(__file__).resolve().parents[2],
                                env={**os.environ, **environment}, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


class OperationalScriptTargetTests(unittest.TestCase):
    def test_bootstrap_requires_explicit_matching_database_and_uri(self):
        env = {"NODAL_DB_NAME": "nodal_audit_test", "MONGO_URI": "mongodb://127.0.0.1:27017"}
        self.assertEqual(resolve_database_target("nodal_audit_test", env),
                         ("nodal_audit_test", "mongodb://127.0.0.1:27017"))
        for target, settings in (
            (None, env),
            ("nodal", env),
            ("nodal_audit_test", {"MONGO_URI": env["MONGO_URI"]}),
            ("nodal", {**env, "NODAL_DB_NAME": "nodal_audit_test"}),
            ("nodal_audit_test", {"NODAL_DB_NAME": "nodal_audit_test"}),
        ):
            with self.subTest(target=target, settings=settings):
                with self.assertRaises(ValueError):
                    resolve_database_target(target, settings)

    def test_seed_requires_explicit_target_and_refuses_production_database(self):
        env = {"NODAL_DB_NAME": "nodal_audit_test", "MONGO_URI": "mongodb://127.0.0.1:27017"}
        self.assertEqual(validate_seed_target("nodal_audit_test", env),
                         ("nodal_audit_test", "mongodb://127.0.0.1:27017"))
        with self.assertRaisesRegex(ValueError, "refuses the production"):
            validate_seed_target("nodal", {**env, "NODAL_DB_NAME": "nodal"})
        with self.assertRaisesRegex(ValueError, "refuses the production"):
            validate_seed_target("NODAL", {**env, "NODAL_DB_NAME": "NODAL"})
        with self.assertRaises(ValueError):
            validate_seed_target(None, env)
        with self.assertRaises(ValueError):
            validate_seed_target("nodal_audit_test", {"NODAL_DB_NAME": "nodal_audit_test"})


if __name__ == "__main__":
    unittest.main()
