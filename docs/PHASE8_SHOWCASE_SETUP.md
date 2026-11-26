# Phase 8 local showcase preparation

This is a local, synthetic-data helper. It uses only the Flask API at
`http://127.0.0.1:5000`; it does not construct a Mongo client. It refuses to
run unless its own process environment has the exact Phase 8 audit values and
the operator confirms the live Flask target interactively.

## Important official-account limitation

Public registration creates citizens. The script requests official access for
three synthetic `.test` identities across Stormwater Drainage, Street Lighting,
and Road Infrastructure. Requests stay pending until an administrator performs
the existing independent-verification workflow. The application has no
test-only approval method; this script never sets `independently_verified`,
invents a verification method, or promotes a fictional person. It can still
create citizen complaints and perform permitted department-only admin routing.
Official assignment and lifecycle actions run only when a matching account is
already active in the admin verified-official directory and can authenticate.
Do not claim that a synthetic identity is a real government employee.

Consequently, a complete official lifecycle showcase requires an appropriately
approved identity established through legitimate independent verification.
If none exists, official-only stages are reported as not demonstrated; the
script does not fabricate progress, resolution, rejection, or approval history.

## Prerequisites

- Start the existing Flask server locally on `127.0.0.1:5000` in the Phase 8
  audit environment. The script does not start or restart Flask.
- In the PowerShell session used to run the script, set:

```powershell
$env:NODAL_AUDIT_MODE = 'true'
$env:NODAL_DB_NAME = 'nodal_phase8_audit'
$env:MONGO_URI = 'mongodb://127.0.0.1:27017'
$env:NODAL_ENV = 'development'
```

- Independently verify the existing Flask process is using the same values.
  The application has no runtime-configuration endpoint, so the script cannot
  inspect another process's environment; it requires the operator to attest
  to the live target before it makes API writes.
- Keep the existing admin credentials file at
  `C:\Users\shiva\AppData\Local\Temp\nodal-phase8-audit-credentials.json`.
- Use the repository `.venv-vision`, which includes Pillow for generated
  in-memory demonstration illustrations. If Pillow is absent, image evidence
  is skipped without creating an invalid attachment.

## Run locally

From the repository root in the configured PowerShell session:

```powershell
.\.venv-vision\Scripts\python.exe scripts\prepare_phase8_showcase.py
```

The tool requires typing `AUDIT`, `nodal_phase8_audit`, and a live-target
attestation. It first authenticates the existing administrator and inventories
departments, verified officials, access requests, and complaints through the
API. It never deletes collections or records. It then creates/reuses the
synthetic citizen accounts through public registration and submits/reuses the
synthetic official access request. Reports, assignments, transitions, and
evidence use normal endpoints and preserve application histories. Complaint
descriptions include a synthetic-only marker; images are generated in memory
and uploaded through the normal complaint multipart API.

The first HTTP request may trigger the application's existing one-time index
and default-department initialization hook. That hook is part of the current
application startup/request behavior. The script itself does not directly
write MongoDB data.

## Credentials

Credentials are atomically saved to:

`C:\Users\shiva\AppData\Local\Temp\nodal-phase8-showcase-credentials.json`

Passwords are generated with `secrets`, never printed, and are not stored in
the repository. The administrator password is read from the separate admin
credential file and held only for the login session; the showcase credentials
file contains synthetic accounts only. If an older showcase file contains an
admin entry, the next successful write removes it. The original admin
credential file is read only and never overwritten. If a target account
already exists but is absent from the showcase credentials file, the script
stops rather than resetting its password. The output path is checked to remain
outside the repository.

## Supported records and honest limitations

The script defines eight Bengaluru-area synthetic scenarios covering road,
garbage, drain, streetlight, water leakage, waterlogging, and footpath
categories. The citizen API derives priority and records status history; the
script does not insert complaint documents or histories directly. Category
routing uses existing department IDs; the footpath example records a reasoned,
explicit illustrative override to the prototype Road Infrastructure group.
Its fixture is `footpath-department-assigned` (the old
`footpath-resolved` marker is recognized for safe reruns); it does not claim a
resolved status. These groups are not asserted to be verified government
assignments.
When appropriately authorized test sessions are already available, API
transitions can demonstrate progress, resolution review, rejection, and a
citizen dispute. A rejected resolution remains `in_progress` with an
append-only rejection event.

Pending synthetic access requests do not block citizen complaint creation or
department-only administrative routing. Statuses requiring an official are
advanced only through a matching active verified official session. This may
leave requested stages incomplete. The script never approves an official;
rejection and dispute fixtures require valid lifecycle transitions by the
appropriate official, administrator, and citizen roles.

## Recovery and reruns

The script is designed to be rerun: it reuses credentials and finds complaint
fixtures by stable `[fixture:<key>]` markers. It does not clear or overwrite
accounts or complaints, and does not roll statuses backward. Before a rerun,
review the audit admin portal and credentials file. To stop showcasing a
fixture later, leave it intact or use the application's authorized lifecycle
and retention processes; do not run `backend/seed.py` and do not delete
collections. If a credential is lost, use the normal account-recovery policy;
this script does not reset passwords.
