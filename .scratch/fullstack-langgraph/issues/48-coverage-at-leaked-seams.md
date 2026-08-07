Type: task
Status: open

## Question

Every defect in the 2026-08-07 findings sweep lived at a seam with zero
tests: request-model fields (`workflow_slug` 422), envelope unwrapping,
`_default_error_handler`'s NodeError shape, resume vs run tool parity, v2
branch documents. Add tests at exactly those seams; extend the real-file
E2E pattern (test_intent_routed_demo_file.py) to every workflow that has a
workflow.json; add a vitest⇄pytest cross-contract test that serializes a
document in TS and compiles it in Python (subprocess) so a one-sided
contract change goes red.
