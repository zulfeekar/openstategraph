Type: task
Status: resolved (2026-08-08) — satisfied across the build-out

## Question

Every defect in the 2026-08-07 findings sweep lived at a seam with zero
tests: request-model fields (`workflow_slug` 422), envelope unwrapping,
`_default_error_handler`'s NodeError shape, resume vs run tool parity, v2
branch documents. Add tests at exactly those seams; extend the real-file
E2E pattern (test_intent_routed_demo_file.py) to every workflow that has a
workflow.json; add a vitest⇄pytest cross-contract test that serializes a
document in TS and compiles it in Python (subprocess) so a one-sided
contract change goes red.

## Resolution

Covered as the features landed rather than as one pass: `test_run_request_seams.py` (7 tests: slug validation, envelope both forms, tool layering/degradation), resume-422 pinned in ticket 33's work, real-file E2E per workflow (`test_chinook_demo_file` 5, `test_code_workshop_file` 6, `test_intent_routed_demo_file` 6, `test_supervisor_archetypes`), defensive error-handler restored in Phase 0. Gate: 437 pytest + 338 vitest.
