Type: prototype
Status: open

## Question

The canvas/view layer — drag, rubber-band, snaplines, undo coalescing,
foreignObject measurement loop, export — has zero automated verification;
every regression there has been found by a human. Prototype a Playwright
smoke suite: seed → drag a node → connect two ports → undo → export JSON →
reload → assert document equality; plus one Chat round-trip against a
stubbed backend. Decide whether it lives in CI (headed flake risk) or as a
pre-release gate.
