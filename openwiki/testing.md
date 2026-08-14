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

CI is *configured* to run all three as separate jobs
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)), with `ruff` on the
backend.

> **No GitHub Actions workflow in this repository has ever executed.** The
> checkout has six workflow files under `.github/workflows/` and **zero git
> remotes**, so nothing is pushed and nothing is triggered (`CLAUDE.md`).
> Every gate on this page — and every claim elsewhere in the wiki that a check
> "runs" or "is enforced" — describes intent. The only checks that have
> actually run are the ones you run locally.

## pytest conventions ([`pytest.ini`](../pytest.ini))

- Two roots: `backend` and `workflows/chinook-assistant` on `pythonpath`;
  `testpaths = workflows backend`.
- **Live-network tests are opt-in.** Mark them `@pytest.mark.live`; the default
  run is `-m "not live"` and must pass offline.
- Test directories deliberately have **no `__init__.py`** — two roots would
  otherwise collide on a package named `tests`.
- `norecursedirs` excludes `data`, `scratch` and `output` — generic
  jail/generated-output conventions for workflow packages, and what keeps a
  package's own fixtures (the Chinook SQLite lives in
  `workflows/chinook-assistant/data/`) out of collection.

## Isolation seams

Injectability exists for tests, not decoration: `WorkflowStore(root=...)`,
`create_app(graph_factory=..., workflows_root=...)`,
`WorkflowCompiler(port_resolver=...)` and `NodeRuntime(tools=..., functions=...)`
all let a test operate on throwaway data with a stub model.

`WorkflowCompiler.plan()` returns a plain `CompiledPlan`, so routing, bindings
and fan-out are assertable without building or running a graph.
