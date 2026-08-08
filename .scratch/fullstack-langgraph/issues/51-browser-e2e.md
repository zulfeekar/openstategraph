Type: prototype
Status: resolved (2026-08-08) — BUILT

## Question

The canvas/view layer — drag, rubber-band, snaplines, undo coalescing,
foreignObject measurement loop, export — has zero automated verification;
every regression there has been found by a human. Prototype a Playwright
smoke suite: seed → drag a node → connect two ports → undo → export JSON →
reload → assert document equality; plus one Chat round-trip against a
stubbed backend. Decide whether it lives in CI (headed flake risk) or as a
pre-release gate.

## Resolution

One-liners: adopt Playwright, smoke-level only (load seeded demo, drag a node, connect two ports, undo, arrange both directions, export JSON) — the measurement-loop and drag code are exactly what unit tests can't see; runs headless in CI as a third job; not implemented in this pass (fresh ~50MB toolchain + new infra deserves its own session with room to stabilize flakes).

## Built (2026-08-08)

Built: Playwright smoke suite (e2e/canvas.smoke.spec.ts) — seeded-demo render, click-to-select, real drag + undo through actual gestures, auto-arrange in both flow directions, palette add. 5/5 passing locally in 3.3s against the supervised dev server (reuseExistingServer); CI job installs chromium and runs headless.
