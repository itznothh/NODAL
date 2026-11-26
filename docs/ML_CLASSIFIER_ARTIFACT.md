# Text classifier artifact provenance

`ml/classifier.joblib` is excluded from Git because its training-data provenance
and suitability for public distribution have not been established. The backend
loads this file when it is present. If it is absent, its category helper returns
`unclassified`; complaint submission remains available, but automatic text-based
category inference is unavailable.

## Current regeneration limitation

`ml/train_classifier.py` currently reads complaint descriptions and category
labels directly from the MongoDB database named `nodal`. It does not use
`NODAL_DB_NAME` to select a database, does not accept a reviewed CSV path, and
does not provide an audit-database guard. Therefore, **do not execute this
script as it currently exists**. Setting `.env` to `nodal_dev` does not change
its hard-coded database selection.

## Safe regeneration procedure

Before regeneration, the training implementation must be revised and reviewed
to accept an explicit source, such as a curated CSV or an explicitly selected
isolated database. The workflow should:

1. Use only consented, appropriately licensed or synthetic complaint text with
   reviewed category labels. Never use production `nodal` data by default.
2. Require the dataset/database target explicitly and fail before connecting if
   the target is absent or not approved for training.
3. Keep the dataset, evaluation outputs and generated artifact outside Git
   unless privacy, license, provenance and distribution review explicitly
   approves publication.
4. Use held-out evaluation data and report real results from that run. Do not
   copy metrics from earlier runs or infer accuracy from the existence of the
   artifact.
5. Save the generated artifact locally as `ml/classifier.joblib`; the ignore
   rule keeps it out of Git by default.

Until those safeguards exist, there is no safe command to regenerate this
artifact from the current script. This note intentionally does not provide a
command that could read the production database.
