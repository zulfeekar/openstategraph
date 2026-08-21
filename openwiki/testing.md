---
title: Testing
description: The three suites, how to run them, and the conventions that keep them isolated.
type: page
---

# Testing

TDD is the standing rule: tests before implementation, and `src/core/` is pure
TypeScript with no excuse for untested logic.

| Suite | Command | Lives in |
| --- | --- | --- |
| Frontend unit | `npm test` (`vitest run`) | beside the source, `*.test.ts(x)` |
| Full frontend gate | `npm run verify` (tsc + eslint + prettier + vitest) | — |
| Backend unit | `cd backend && pytest` | [`backend/tests/`](../backend/tests) and `workflows/<slug>/tests/` |
| Browser E2E | `npx playwright test` | [`e2e/canvas.smoke.spec.ts`](../e2e/canvas.smoke.spec.ts) |

CI runs all three as separate jobs
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)), with `ruff` on the
backend.

> **CI does run and does pass** — this repository has a `beta` git remote,
> and `gh run list` against it shows real, repeated `CI` workflow runs,
> including successes (`CLAUDE.md` records the count as of its last check;
> re-run `gh run list` for the current one rather than trusting a number
> here). Two named exceptions: `openwiki-update.yml` (this page's own
> generator) has run on schedule and failed for a missing `OPENAI_API_KEY`
> secret, and `docs-freshness` is PR-only in a repo that pushes straight to
> `main`, so it has run just once. See `CLAUDE.md`'s OpenWiki correction
> block for the full, sourced account — it is hand-owned and does not get
> overwritten by this generator.

## pytest conventions ([`pytest.ini`](../pytest.ini))

- Two roots: `backend` and `workflows/chinook-assistant` on `pythonpath`;
  `testpaths = backend workflows/chinook-assistant`. **`workflows/` as a whole
  is not swept** (workflow-gallery ticket 46): a package copied out of
  `backend/openstategraph/examples/` brings a `tests/test_<slug>_document.py`
  whose basename collides with the original's under two roots and no
  `__init__.py`. A package's own tests run under
  `openstategraph test <package>`; its *document* is read by the every-package
  sweep in `backend/tests/test_the_one_example.py`. Pinned by
  `backend/tests/test_collection_policy.py`.
- **Live-network tests are opt-in.** Mark them `@pytest.mark.live`; the default
  run is `-m "not live"` and must pass offline.
- Test directories deliberately have **no `__init__.py`** — two roots would
  otherwise collide on a package named `tests`.
- `norecursedirs` excludes `data`, `scratch`, `output` and `templates` —
  generic jail/generated-output conventions for workflow packages, plus the
  scaffold templates, whose four `tests/test_shape.py` files are package data
  (exercised for real by `backend/tests/test_templates.py`, which scaffolds
  each template into a `tmp_path` and runs pytest on the rendered copy). This
  is what keeps a package's own fixtures (the Chinook SQLite lives in
  `workflows/chinook-assistant/data/`) out of collection.

## Isolation seams

Injectability exists for tests, not decoration: `WorkflowStore(root=...)`,
`create_app(graph_factory=..., workflows_root=...)`,
`WorkflowCompiler(port_resolver=...)` and `NodeRuntime(tools=..., functions=...)`
all let a test operate on throwaway data with a stub model.

`WorkflowCompiler.plan()` returns a plain `CompiledPlan`, so routing, bindings
and fan-out are assertable without building or running a graph.
