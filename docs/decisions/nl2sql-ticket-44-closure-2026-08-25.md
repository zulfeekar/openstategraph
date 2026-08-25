# launch-readiness/44 closure — 2026-08-25

Re-verified live against `workflows/cpl-nl2sql` (osg-demo, package code
unchanged) via `/api/runs` with `workflow_slug` set (`prefetch1`
non-empty). Probe: "What was the charter rate for each cargo shipped from
Mongstad in the last 60 days?" — combines a nonexistent column with a
date-windowed predicate, the two risks the ticket left open.

- Refusal: agent1 states plainly no charter/freight column exists and
  returns real rows with `NULL AS charter_rate` instead of inventing a
  number.
- Hallucinated columns: none — every column used is real, including
  `vessel_imo`, the name the original Q8 failure got wrong.
- Dialect / date predicate: `WHERE load_date >= DATE_SUB(CURRENT_DATE, 60)`,
  Databricks dialect, passed by the validator's widened date-predicate
  check (`ce28e64` in osg-demo).
- validate1/gate1 surfaced a non-blocking `[enumerable]` warning correctly
  rather than blocking or guessing.

All of the ticket's original claims no longer reproduce. Closed resolved.

One new defect found while verifying, filed separately as
launch-readiness/81: `execute1`/`summarize1`/`out1` flattened this correct,
already-validated answer into a generic "could not answer reliably"
message downstream.
