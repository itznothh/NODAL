# NODAL Phase 1: authentication and access control

## Local configuration

Copy `.env.example` to `.env`, set `NODAL_SECRET_KEY` to a unique random value,
and keep `.env` out of source control. For example, generate a key with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set `NODAL_CORS_ORIGINS` to the exact local frontend origins you use. The
backend accepts the configured origins with credentialed requests; it does
not allow arbitrary origins.

## First administrator

There is no public administrator registration route. Set `MONGO_URI`,
`NODAL_DB_NAME`, `NODAL_BOOTSTRAP_ADMIN_EMAIL`, and
`NODAL_BOOTSTRAP_ADMIN_PASSWORD` in the protected process environment, then
run `python -m backend.bootstrap_admin --database <database-name>` from the
repository root. The CLI requires the explicit database argument to match
`NODAL_DB_NAME`, displays the target, and requires typing its exact name. It
creates at most one initial administrator using a database-backed single-use
lock. Remove bootstrap credentials from the environment afterward. The
database must be reachable. See `DEPLOYMENT.md` for production requirements.

## Account and session rules

- Public registration ignores client-supplied roles and always creates a
  `citizen` account.
- Passwords are hashed with Werkzeug's password hashing implementation; raw
  passwords are never stored or returned.
- Sessions use a signed, HTTP-only, SameSite=Lax cookie with an eight-hour
  lifetime. Set `NODAL_ENV=production` to enable Secure cookies; production
  startup refuses to run without `NODAL_SECRET_KEY`.
- All POST/PATCH/PUT/DELETE API requests require a session-bound CSRF token.
- A role is reloaded from MongoDB on each protected request, so disabled or
  changed accounts lose access without trusting a client role value.
- Citizens can create complaints and read only their own. Officials can access
  complaints assigned to them or routed to their independently verified
  department. Admins can review all legacy complaint records and route new
  reports through controlled lifecycle operations.

## Official access review

An authenticated citizen may submit a pending access request with employee ID,
department, designation, and supporting verification information. These
details are not proof of employment. An administrator must affirm independent
verification, select an independent method, and record verification notes
before approval. Email domains and uploaded IDs alone are not accepted as
verification methods. The platform records the administrator's attestation;
it does not independently contact an agency or verify employment itself.

## Existing complaint records

No complaint documents are migrated or deleted. Older records without
`created_by` are marked in API responses as demonstration/sample records that
are not verified civic reports. Admin views can still inspect them. New citizen
records keep the existing description/category/priority/status/location/time
fields and add ownership/history metadata. Optional image evidence is held in
private filesystem storage; only its metadata and generated storage reference
are stored in MongoDB.

The `seed.py` script deletes all complaints before inserting fixtures. Do not
run it against the active database.

## Development boundaries

Evidence access is checked against complaint ownership and official/admin
permissions. Evidence references are currently stored on the local filesystem
by default; deployers must configure and back up a private evidence directory.
In-memory API tests do not connect to the live MongoDB database.
