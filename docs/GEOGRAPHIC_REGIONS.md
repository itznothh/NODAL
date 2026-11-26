# Geographic Region Registry

## Status

The region registry is a versioned, read-only foundation. It does not add
complaint fields, create MongoDB collections or indexes, or import boundaries.
Region-scoped read APIs and pure filtering helpers exist, but Bengaluru remains
a draft template with `boundary: null`; no GBA statistics are available or
returned for it.

## Record shape

Each immutable boundary version is one document in the future `regions`
collection:

```text
region_id             stable lowercase ID, for example in-ka-bengaluru
name                  display name
region_type           country | state | city | ward
parent_region_id      null for country; otherwise stable parent ID
boundary              GeoJSON Polygon/MultiPolygon, or null for a draft
boundary_version      source/version label; unique with region_id
source                organization, title, URL
provenance            dataset ID, acquisition time, SHA-256, notes
license               name, URL, redistribution_status
approval_status       draft | approved | rejected | superseded
approved_by/at        required when approved or superseded
created_at/updated_at timezone-aware datetimes
```

Boundary updates create a new `(region_id, boundary_version)` document. An
approved version is not edited in place. Future indexes should include a unique
compound index on `(region_id, boundary_version)` and a query index for the
current approved version. This phase intentionally creates neither index.

## Validation and API

`backend/regions.py` validates IDs, types, parent hierarchy, version uniqueness,
timestamps, approval requirements, redistribution clearance, GeoJSON type,
non-empty closed rings, non-zero area, and longitude/latitude ranges. The
coordinate order is RFC 7946 `[longitude, latitude]`. The dependency-free
validator does not prove full polygon topology (for example, self intersections,
hole containment, or polygon overlap); an approved GIS import must perform that
check before approval.

`GET /public/regions` returns approved, valid records with valid approved
ancestry, excluding geometry. `GET /public/regions/<region_id>` returns the
boundary only when exactly one approved valid version exists. Draft, rejected,
superseded-only, malformed, and ambiguous records are not exposed publicly.
`GET /admin/regions` is admin-only and lists versions for review. There are no
write or approval endpoints.

### Region aggregate API contracts

`GET /public/regions/<region_id>/overview` returns:

```json
{
  "scope": {"type": "region", "region": {
    "region_id": "<id>", "name": "<name>",
    "region_type": "<type>", "boundary_version": "<version>"
  }},
  "metrics": {
    "total_complaints": 12, "open_complaints": 9,
    "high_priority_open": null, "hotspot_count": null
  },
  "data_quality_notice": "...",
  "privacy_suppression": {
    "minimum_count": 5, "suppressed_metrics": ["high_priority_open"],
    "sparse_hotspot_clusters_suppressed": true,
    "hotspot_centers_coarsened": true,
    "exact_complaint_points_returned": false,
    "formal_anonymity_guarantee": false
  }
}
```

Counts below five are returned as `null`; when the total is sparse, all metrics
are suppressed. Hotspot clusters require at least five points. The shape above
is illustrative only; no counts are fabricated or emitted for the unpopulated
GBA draft.

`GET /public/regions/<region_id>/hotspots` returns the same `scope`,
`data_quality_notice`, and `privacy_suppression` metadata plus a `hotspots`
array using the existing aggregate hotspot fields. It contains no complaint IDs,
citizen data, assignments, evidence references, or individual complaint points.

Errors use `{ "error": {"code": "...", "message": "..."}, "scope": ... }`:

- Invalid region ID: `400 invalid_region_id`.
- Unknown ID: `404 region_not_found`.
- Draft/rejected/unapproved region: `409 region_not_approved`.
- Approved record without geometry: `409 boundary_missing`.
- Retired-only version: `410 boundary_version_retired`.
- Malformed/ambiguous approved registry state: `422 invalid_region` or `409 region_version_ambiguous`.

### Filtering, edge, and privacy policies

The shared `backend/geography.py` service validates each stored `[longitude,
latitude]` pair, then filters before aggregation. Missing, malformed, out-of-range,
and outside-boundary points do not contribute to a region. Complaint lifecycle
metrics keep the existing platform meanings: total includes all statuses;
open excludes `resolved` and `disputed`; high priority is counted only among
open complaints. A valid point with category `unclassified` remains locatable
and may contribute to region totals.

The point-in-polygon policy includes outer boundaries and polygon-ring
boundaries, excludes hole interiors, and supports MultiPolygon. Overlapping
approved regions are independent scopes; a point can count in both. This phase
does not assign exclusive region ownership. Boundary inclusion can therefore
lead to double counting across overlapping or shared edges; a future region
registry policy must decide whether to retain inclusive membership or apply a
deterministic tie-break rule.

Sparse metric counts are suppressed below five, and hotspots preserve the
minimum five point cluster threshold. Hotspot centers are coarsened to three
decimal places and guarded against equaling any eligible exact input point.
These controls reduce direct location exposure but do not provide differential
privacy or a formal anonymity guarantee; repeated queries and auxiliary data can
still enable inference. More robust privacy controls may require cell-level
aggregation, complementary suppression, and rate limiting.

### Query and performance strategy

The application already creates a `2dsphere` index on `complaints.location`.
The current pure-service/API path scans and filters in Python after resolving an
approved boundary. This keeps corrupt legacy-coordinate handling explicit and
works for a small pilot, but is O(N) in complaint count and is not the final
large-dataset query plan. Before activating a real boundary at scale, use
MongoDB `$geoWithin` with the approved Polygon/MultiPolygon to use the existing
2dsphere index, then revalidate returned points in Python before aggregation.
Test that plan against malformed legacy documents and the actual MongoDB server
version first; if geospatial query/index behavior rejects malformed rows, use a
safe staged cleanup/classification plan or a validated candidate query rather
than weakening coordinate validation. Aggregation should operate only on the
spatial candidate set, not the platform-wide collection.

The existing `GET /public/overview` and `GET /hotspots` remain platform-wide
with their prior response shapes and meanings.

## Greater Bengaluru Area boundary evidence and approval gate

Research checked these sources on 26 November 2026:

1. **Governing Act:** the [Greater Bengaluru Governance Act, 2024 (Karnataka Act 36 of 2025)](https://www.indiacode.nic.in/bitstream/123456789/21664/1/36_of_2025_%28e%29.pdf)
   says the Act extends to the Greater Bengaluru Area "as notified by the
   Government". Section 3 provides for a government notification declaring the
   larger urban area of Bengaluru and any other specified areas, and allows the
   territorial limits to be modified by notification. The Act itself does not
   supply a machine-readable boundary. IndiaCode records the commencement as
   15 May 2025 under notification UDD 100 BBS 2025 P-2 dated 14 May 2025.
2. **Five corporation final notification:** Karnataka Government notification
   UDD 170 BBS 2025 dated 2 September 2025, Gazette No. 522, constitutes five
   corporations and gives their specified boundaries in Schedule I. The
   document is available as a [Gazette-text/PDF copy](https://data.opencity.in/dataset/dface0f0-4bf5-4a29-83a1-b6e73f538b6c/resource/9aa1c130-3247-4e79-ab2a-b64176ce9d8a/download/9050.pdf)
   and a [PDF mirror](https://blrpost.com/wp-content/uploads/2025/09/881181194852-5-City-Corporations-List-03092025.pdf).
   These copies identify Government of Karnataka as issuer and list the five
   corporations, but are not hosted on an official Karnataka government domain.
   The underlying official gazette file and its exact source URI still need to
   be obtained for the provenance packet.
3. **Official GBA map portals:** the [BBMP/GBA maps page](https://www.bbmp.gov.in/maps/)
   offers five corporation delimitation maps. The [GBA ward delimitation portal](https://bbmp.gov.in/gba-corporations-delimitation-2025/index.html)
   identifies itself as the final-notification ward portal and lists 369 ward
   maps. These are official leads for corporation/ward geometry, not a verified
   single parent GBA boundary. The reviewed portals do not state redistribution
   terms for NODAL.
4. **OpenCity catalog:** its [GBA corporation dataset](https://data.opencity.in/dataset/greater-bengaluru-authority-corporations-delimitation-2025)
   lists KML/PDF material and reports Government of Karnataka as source. A
   catalog license label of "Other (Public Domain)" is not sufficient evidence
   that the original geometry may be redistributed by NODAL. No catalog artifact
   was downloaded.
5. **Survey of India:** its [official mapping portal](https://onlinemaps.surveyofindia.gov.in/AboutPortal.aspx)
   describes administrative boundary products, but not a current GBA polygon.
   The [SoI digital licence](https://surveyofindia.gov.in/documents/digital-licence.pdf)
   and [pricing catalog](https://surveyofindia.gov.in/documents/uploads/document-776-Price%20List%20for%20Digital%20Products.pdf)
   require checking terms for the specific product and proposed public use.
6. **Comparison only:** [DataMeet municipal spatial data](https://github.com/datameet/Municipal_Spatial_Data)
   contains community-curated Bengaluru/BBMP geometries; it may represent an
   earlier jurisdiction and is not a substitute for the GBA notification.

The Act's section 3 declaration notification that precisely identifies the GBA
territorial limit was not located in an authoritative source during this pass.
The five-corporation notification establishes five corporations *within* the
GBA, but the reviewed evidence does not prove that the union of the five is
exactly the entire GBA. It also does not provide a clear redistribution license
for NODAL. Consequently, no artifact was downloaded, hashed, converted, or
topologically validated. No area, bounding box, or containment claim is made.

The offline draft template now uses ID `in-ka-greater-bengaluru`, parent
`in-ka`, and the existing `city` type (the schema has no metropolitan-region
type). It has no boundary and its license status is pending; it is not inserted
into MongoDB. Approval requires: (a) the section 3 GBA notification or equivalent
authoritative extent, (b) an official geometry that is demonstrably the full GBA
or verified geometries for all five corporations plus proof their union equals
the notified parent extent, (c) written or explicit license terms covering
storage, processing, and redistribution, and (d) offline GIS validation and
checksums for original and converted artifacts.

## Explicitly deferred

- Administrative boundary import and MongoDB collection/index migration.
- Any mutation or approval endpoint/workflow.
- Complaint-to-region classification and historical reclassification.
- City/state/ward complaint statistics and hotspot filtering.
- Policy for overlapping/edge points, boundary revisions, and public small-cell
  suppression.
