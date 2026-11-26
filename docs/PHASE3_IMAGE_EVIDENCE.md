# Phase 3: image-assisted complaint reporting

## Citizen flow

Citizens may optionally select a JPEG, PNG, or WebP image (maximum 5 MB) in
the report dashboard and request predictions before submitting. In default
`demo` mode the ImageNet output is general object recognition, not civic issue
detection. The citizen chooses the complaint category in the report form;
predictions do not create a report, assign it, or resolve it. Description and
map location remain required.

Submitting a selected image sends the report and image together to
`POST /complaints` as multipart form data. The backend validates the image,
stores it in private filesystem storage under a generated filename, then
inserts its metadata and reference in the complaint document with status
`submitted`. If the complaint insert fails, the newly stored file is removed.
The configured `NODAL_EVIDENCE_DIR` defaults to
`<local application data>/NODAL/evidence`, outside the repository. Deployments
should set it to a private, backed-up filesystem or managed volume with
restricted operating-system permissions.

## Evidence access

Complaint responses expose metadata and a relative URL, never the filesystem
key. `GET /complaints/<complaint_id>/evidence/<evidence_id>` looks up the
complaint first and allows only its citizen owner, a verified official with
the assigned department/account scope, or an administrator. Files are sent as
attachments with private no-store cache headers and `nosniff`.

## Storage and limitations

MongoDB stores metadata (generated evidence ID/key, content type, byte size,
SHA-256 digest, dimensions, and upload time), not image bytes. Only one image
per report is currently accepted by the UI, though the record format allows
multiple evidence entries. Evidence is stored as the validated source bytes;
this release does not strip EXIF metadata, virus-scan files, or provide a
cloud object-storage adapter. Backups must include the configured evidence
directory as well as MongoDB. Evidence references are not public URLs.
