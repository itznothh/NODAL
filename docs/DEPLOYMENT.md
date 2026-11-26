# NODAL production deployment and operational safety

This document describes production startup and safe operational commands. Do
not use the seed script on a live database. These instructions do not claim
that a particular deployment host, TLS proxy, MongoDB backup, or civic model
has been configured or verified.

## Required production configuration

Set these values in the backend process environment or a protected secret
manager. Do not commit `.env` or expose secrets in logs.

| Variable | Production requirement |
| --- | --- |
| `NODAL_ENV` | Exactly `production`. |
| `NODAL_SECRET_KEY` | Random, private value of at least 32 characters. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. |
| `MONGO_URI` | Explicit MongoDB URI. Use authentication and TLS when connecting to a remote MongoDB service. |
| `NODAL_DB_NAME` | Explicit application database name. Production WSGI refuses either audit database. |
| `NODAL_AUDIT_MODE` | `false` or unset. Audit mode is not accepted by production WSGI. |
| `NODAL_CORS_ORIGINS` | Comma-separated exact HTTPS origins, without paths. Wildcards and localhost origins are rejected. |
| `NODAL_EVIDENCE_DIR` | Persistent private directory outside the application repository. Restrict filesystem permissions to the service account. |

`NODAL_VISION_MODE` is optional and defaults to `demo`. Civic mode requires a
separately trained and validated artifact set; the ImageNet demo is generic
image recognition and is not a civic issue detector.

## MongoDB

Install and secure MongoDB separately. Create an application database user
with only the permissions NODAL requires on `NODAL_DB_NAME`. Restrict network
access to the application host, enable authentication, and use TLS for remote
connections. Confirm the URI and database name in the protected deployment
configuration before starting the service. Never point audit or test work at
the production database.

The application creates required indexes and proposed prototype department
mappings on its first request if the department registry is empty. These are
additive initialization writes; they do not seed complaints.

## Backend WSGI startup

Install the pinned application dependencies, including Waitress:

```powershell
python -m pip install -r requirements-before-vision.txt
```

For image inference, install the compatible vision dependencies from
`ml/vision/requirements-vision.txt` in the same environment. TensorFlow may
require platform-specific wheels and additional memory; validate that runtime
on the target host before enabling the inference endpoint.

From the repository root, start Waitress behind a TLS-terminating reverse
proxy. This loopback example assumes the proxy forwards to port 8000:

```powershell
waitress-serve --listen=127.0.0.1:8000 backend.wsgi:app
```

The application constructs its Mongo client with connection deferred until a
request needs the database. `backend.wsgi` fails at startup if production configuration is incomplete,
weak, points at an audit database, enables audit mode, or has unsafe CORS
origins. The Flask development server refuses to start when
`NODAL_ENV=production`. Do not expose the Waitress listener directly to the
public internet; configure TLS, request limits, health monitoring, log
retention, process supervision, and firewall rules at the hosting layer.

## Frontend production build

Set `VITE_API_BASE` to the absolute HTTPS base URL of the production API before
building. The production Vite build fails if this value is missing.

```powershell
$env:VITE_API_BASE = 'https://api.example.org'
Set-Location frontend
npm ci
npm run lint
npm run build
```

Serve the generated `frontend/dist` directory from the chosen static host. The
frontend uses credentialed API requests, so configure the exact frontend
origin in backend `NODAL_CORS_ORIGINS` and preserve HTTPS and cookie behavior.

## First administrator bootstrap

Bootstrap is an explicit one-time operation, separate from application
startup. Set `MONGO_URI`, `NODAL_DB_NAME`, and the bootstrap email/password in
the protected shell environment. The database name must be explicitly
provided both as `NODAL_DB_NAME` and as the CLI argument. The CLI displays the
selected database and requires typing its exact name before it connects.

```powershell
$env:NODAL_DB_NAME = 'nodal'
$env:MONGO_URI = 'mongodb://db-host:27017/?authSource=admin&tls=true'
$env:NODAL_BOOTSTRAP_ADMIN_EMAIL = 'administrator@example.org'
$env:NODAL_BOOTSTRAP_ADMIN_PASSWORD = '<unique password of at least 12 characters>'
python -m backend.bootstrap_admin --database nodal
```

Use the actual protected URI; provide authentication through the deployment's
secret manager or protected process environment rather than a committed file.
Do not paste credentials into a shared terminal transcript. Confirm the displayed database before typing
the confirmation. Remove bootstrap credentials from the process environment
afterward. The existing database-backed one-time lock remains in effect. The
CLI is never invoked by WSGI startup.

## Evidence storage and recovery

Complaint evidence is stored as generated files outside MongoDB, under
`NODAL_EVIDENCE_DIR`. Use a private persistent volume; ephemeral container
storage is unsuitable. Back up the evidence directory and MongoDB data as a
coordinated recovery set. MongoDB records contain file references, so restoring
only one side can leave missing files or orphaned evidence. Restrict evidence
read access to the service account and retain backups according to the
organization's approved retention policy.

Before production changes, take and verify a restorable MongoDB backup using
the MongoDB tooling and recovery procedure appropriate to the deployment.
Test restoration into a separate, isolated database and evidence directory.
Do not test recovery by overwriting production. Record backup timestamps,
scope, encryption, retention, and restore validation.

## Safe database operations

- `backend/seed.py` is destructive: it deletes every complaint in the selected
  database and inserts synthetic demo complaints. It refuses database
  `nodal`, requires `--database` matching an explicit `NODAL_DB_NAME`, an
  explicit `MONGO_URI`, and an exact typed confirmation. It is for explicitly
  authorized development/testing only; never run it in production.
- `backend/bootstrap_admin.py` is not a seed command, but creates a privileged
  account. It requires the explicit database target and exact typed
  confirmation. Never run it against a database without an approved
  administrator bootstrap plan.
- Never use existing demonstration/sample complaints as verified civic
  reports, and never represent the ImageNet demo as civic classification.
- Before any database command, confirm the effective host and database from
  the same process environment that will execute it. Keep production and audit
  credentials separate.
