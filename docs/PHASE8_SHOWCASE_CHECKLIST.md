# Phase 8 showcase verification checklist

Run only after independently confirming the Phase 8 audit runtime. The setup
script reports its API checks, but these manual checks remain useful for the
browser showcase.

## Before running

- [ ] Flask process uses `NODAL_AUDIT_MODE=true`.
- [ ] Flask process uses `NODAL_DB_NAME=nodal_phase8_audit`.
- [ ] Flask process uses `MONGO_URI=mongodb://127.0.0.1:27017`.
- [ ] Flask process uses `NODAL_ENV=development` and a non-empty process-local secret.
- [ ] The existing Phase 8 admin credentials file is present and unchanged.
- [ ] The exact audit database name was typed at the script prompt.
- [ ] Existing departments, access requests, and complaint markers were reviewed before adding fixtures.

## After running

- [ ] Credentials JSON is in `%LOCALAPPDATA%\Temp`, outside the repository; passwords were not printed.
- [ ] Citizen registration/login succeeds and each citizen list contains only its own tagged complaints.
- [ ] The official access request is visibly pending unless an administrator performed valid independent verification.
- [ ] A pending synthetic request cannot access official APIs.
- [ ] Any active verified official sees only individually assigned or authorized department complaints.
- [ ] Admin sees tagged synthetic complaints, routing history, and lifecycle history.
- [ ] Complaint states advance only through normal admin/official transition APIs.
- [ ] Evidence renders for its owner/admin/authorized official; another citizen receives denial/not-found.
- [ ] Every record description includes the synthetic-only marker; no real-world incident is implied.
- [ ] Existing complaints, accounts, and audit events remain present; rerunning creates no duplicate fixture markers.
- [ ] Any stages skipped for lack of a legitimately approved official are recorded as not demonstrated, not reported as passed.

## Recovery

- [ ] Do not use `backend/seed.py`, collection drops, or bulk deletion.
- [ ] Keep the original audit admin credential file intact.
- [ ] Use ordinary authorized lifecycle transitions for any correction; retain the append-only histories.
- [ ] If the credentials file is damaged, recover it from the local secure backup or use the application's approved credential recovery. Do not reset an existing account from this script.
