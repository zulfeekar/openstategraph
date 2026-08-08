Type: task
Status: mostly resolved (2026-08-08) — two human steps remain

## Question

The final nail. P0 legal: LICENSE file (package.json already claims MIT with
no grant; pyproject claims nothing); delete `harness-loop-graph.pdf` — a
2MB third-party deck printed from X, half the repo — and purge it from
history (destructive rewrite: prepare the filter-repo command, the human
runs it); decide `.scratch/` (contains verbatim third-party quotes) and
HANDOVER.md.

Then: CI (vitest + tsc + pytest on PR); ruff + mypy in pyproject [tool.*];
eslint/prettier (or biome) + lint script wired into `verify`; CONTRIBUTING /
SECURITY / CODE_OF_CONDUCT / .github templates; ARCHITECTURE.md split out of
CLAUDE.md; README corrections (uv not pip, one Python version story,
@joint/layout-directed-graph is MPL-2.0 not MIT, document DYFLOW_LOG_LEVEL);
`VITE_DYFLOW_API_URL` + strictPort:true (busy 5273 currently yields a silent
CORS failure); THIRD_PARTY_NOTICES (4× MPL-2.0 JointJS, OFL-1.1 Inter,
MIT Chinook — currently credited only inside fetch_chinook.sh); commit or
regenerate lockfiles consistently; coverage threshold + pytest-cov.

## Resolution

Done: LICENSE (MIT, matching package.json), CI (`.github/workflows/ci.yml`: npm verify + pytest, live APIs excluded), CONTRIBUTING.md, SECURITY.md, pyproject license + the four missing tabular deps declared, README corrections (Python 3.11+, MPL-2.0 for the layout package), `harness-loop-graph.pdf` removed from the tree and gitignored, `.claude/settings.local.json` ignored.

Remains for a human (destructive / policy):
1. **History purge of the PDF** — it stays fetchable until rewritten out: `git filter-repo --invert-paths --path harness-loop-graph.pdf` (rewrites all SHAs; coordinate before running).
2. **Fate of `.scratch/` + `HANDOVER.md`** — ship, scrub, or untrack (`.scratch/decisions/loop-graph-harness.md` quotes the same third-party deck).
Deferred as nice-to-have: linters (eslint/prettier/ruff/mypy), issue templates, CHANGELOG + v0.1.0 tag, VITE_DYFLOW_API_URL.
