# Local NODAL demo startup

## Safe local configuration

The tracked `.env.example` is a template, not a secret file. For manual local
development, copy it to `.env`, replace the placeholder `NODAL_SECRET_KEY`
with a fresh random value held only on the developer machine, and keep
`NODAL_DB_NAME=nodal_dev`. Never point this template at `nodal` or a production
database. `.env` and other `.env.*` files are excluded by the root `.gitignore`;
only `.env.example` is allowed. The one-click launcher sets its own isolated
`nodal_phase8_audit` database for its child processes and does not rely on the
manual `.env` database value.

Do not put credentials, exported MongoDB data, uploads or evidence in the
repository. Keep real user data outside the project tree and use isolated
synthetic records for local demonstrations.

Use `START_NODAL.bat` in the repository root to start the local demo. It checks
the MongoDB Windows service and local TCP endpoint, checks ports 5000 and 5174,
starts Flask and Vite in separate PowerShell windows, waits for both HTTP
endpoints, then opens <http://127.0.0.1:5174>.

## What the launcher configures

The launcher overrides any `.env` database settings **for the child processes
only** and uses:

- `NODAL_AUDIT_MODE=true`
- `NODAL_DB_NAME=nodal_phase8_audit`
- `MONGO_URI=mongodb://127.0.0.1:27017`
- `NODAL_ENV=development`
- A cryptographically random `NODAL_SECRET_KEY` held in process memory and
  inherited by the Flask process. It is not printed or saved.
- `VITE_API_BASE=http://127.0.0.1:5000`

The production database name `nodal` is never selected by this launcher. The
existing `.venv-vision` Python environment and `frontend/node_modules` are
required; this launcher does not install dependencies or run seed, bootstrap,
or migration scripts. MongoDB must be installed as the Windows service named
`MongoDB`. If stopped, the launcher attempts to start it and reports a clear
permission/service error if it cannot.

## Port behavior

Before starting either application server, the launcher checks ports 5000 and
5174. If either is occupied, it reports the owning process/PID where Windows
allows inspection and refuses to reuse or duplicate that server because its
database/runtime configuration cannot be proven. Inspect that process and
retry after the port is available. Vite also uses strict port mode.

Flask starts through the Flask CLI with debugger and auto-reload disabled. The
launcher waits up to 60 seconds for `/health` and for Vite to return HTTP 200.
Failure details remain visible in the respective terminal window.

## Stop

Use `STOP_NODAL.bat` to stop only backend/frontend process trees recorded by
this launcher. It checks each PID's process start time before stopping it, so a
reused PID is left alone. MongoDB is deliberately left running because it can
be shared by other local tools. Closing a service terminal manually also stops
that server; the stop file safely ignores already-exited processes.

Launcher process metadata is stored under `%LOCALAPPDATA%\NODAL\local-demo`
and contains process IDs and the isolated target, never the session secret or
demo credentials.

## Preflight without starting services

To check repository prerequisites, MongoDB service visibility and port state
without starting MongoDB, launching Flask/Vite, or contacting a database, run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_nodal.ps1 -CheckOnly
```

No application data is reset. On the first real Flask request, the existing
application startup hook may ensure its indexes and default department
registry in `nodal_phase8_audit`; no complaint records are seeded or modified by
the launcher.
