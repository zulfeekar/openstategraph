# Contributing to OpenStateGraph

Two stacks, one repo: a TypeScript editor (`src/`) and a Python LangGraph
runtime (`backend/`). Architecture rules live in `CLAUDE.md` — read the
"Non-negotiables" section before designing anything.

## Setup

```bash
npm install && npm run dev                 # editor → http://localhost:5273
pip install -e "backend[all,dev]"          # runtime deps — see below
PYTHONPATH=backend:workflows/chinook-nl-to-sql \
  uvicorn openstategraph.api.main:app --port 8000 --app-dir backend
```

No API keys required: the editor runs on a deterministic Mock provider, the
backend defaults to Ollama cloud.

`[all]` is a *contributor's* install. A consumer installs the lean core —
`langgraph`, `langchain`, `langchain-core`, `pydantic` — plus whichever extras
their workflow actually uses (`[anthropic]`, `[openai]`, `[ollama]`, `[deep]`,
`[sqlite]`, `[server]`, `[mcp]`). Adding a dependency to the core table
without the accompanying case for it fails
`backend/tests/test_distribution_metadata.py`, which is the point.

## Tests — the gate for every PR

```bash
npm run verify              # tsc + eslint + prettier + vitest
python -m pytest -q         # live-API tests are opt-in: pytest -m live
cd backend && python -m ruff check . && python -m mypy
```

`mypy` is the backend's counterpart to `tsc`: its settings live in
`backend/pyproject.toml` and it is clean today, so any error it reports is
yours. It is scoped to `openstategraph/` — `tests/` is deliberately outside it.

TDD is the house style: tests land with (ideally before) the change.

**Docs land with the code.** CI's `docs-freshness` job fails a PR that touches
`src/` or `backend/` without touching `README.md`, `docs/` or `openwiki/`. If
the change genuinely needs no documentation, put `docs: not-needed` in any
commit message in the PR and the job passes.

## Generated artifacts — regenerate, never hand-edit

`backend/openstategraph/compile/port_specs.json` is **generated** from the
TypeScript node catalogue and committed. Change a node type, a port, a port's
cardinality or a port type, and you must run:

```bash
npm run generate:ports
```

The TypeScript side is authoritative here (the opposite direction to
Pydantic → TypeScript, which is the rule for *runtime* types): `src/nodes/**`
is where a node type is declared and where `ports` is a function of node data;
Python only reads the shape. The artifact is committed because an installed
wheel has no Node.js — a consumer running `load_workflow` cannot regenerate it.

Two gates catch a stale copy: `src/nodes/portSpecs.test.ts` compares the built
catalogue to the committed bytes inside `npm run verify`, and CI's
`generated-port-specs` job regenerates and diffs the working tree. Both name
the command in the failure. Do not edit the JSON by hand.

## Adding things

Everything is a registry; extending never edits `core/`. See README's
"Extension points" table. A new workflow is a package under
`workflows/<slug>/` — `workflow.json` + `AGENTS.md` required; `tools/`,
`functions/`, `middlewares/`, `tests/`, `data/` discovered by convention.

## What happens to your pull request

**Open it from a fork; nothing here needs your trust.** CI runs on the
`pull_request` trigger, which means a fork's build gets a read-only token and
**no repository secrets** — so every check runs on your branch exactly as it
would on ours, and no check can be "unblocked" by a maintainer's credentials.
The only workflow that holds a secret is the release train, and it never runs
on a pull request.

Six checks run, and one aggregate:

| Check | What fails it |
| --- | --- |
| `frontend` | `npm run verify` — tsc, ESLint, Prettier, Vitest |
| `backend` | ruff, mypy, and pytest under a coverage floor |
| `generated-port-specs` | `port_specs.json` was not regenerated after a node or port change |
| `clean-install` | the built wheel fails in an empty venv outside the checkout |
| `docs-freshness` | `src/` or `backend/` changed and no documentation did |
| `e2e` | the Playwright suite |
| `ci-success` | any of the above — this is the one branch protection requires |

A maintainer reviews against `CLAUDE.md`, not taste: the architecture checklist
in the pull-request template is drawn from it, and "this adds a public member to
`WorkflowController`" is a blocking comment no matter how good the code is.
`.github/CODEOWNERS` requests the reviewer automatically. Paths you touch also
add labels (`frontend`, `backend`, `workflows`, `docs`, `ci`, `e2e`) — for
sorting the queue, nothing more.

### `docs: not-needed`

The `docs-freshness` check exists because documentation written a week later is
documentation written by a stranger. It fails when a pull request touches
`src/` or `backend/` and touches none of `README.md`, `docs/`, `openwiki/`.

It is a prompt, not a wall. If the change genuinely has no user-visible or
architectural surface — an internal rename, a test-only change, a dependency
pin — say so and it passes:

```bash
git commit --allow-empty -m "docs: not-needed — internal refactor only"
```

Write the reason after the dash. The check only greps for the phrase, but the
reason is what a reviewer reads, and "docs: not-needed" with nothing after it
invites the question you were trying to skip.

### Commit messages

**No prefix convention. Write a subject that says what changed and why.** The
log reads like `RC-01: generate the port table from TypeScript; the hand copy
held 10 of 38 node types`, and that is the standard — a sentence, not a
category. Nothing is parsed out of your commits: the changelog is written by a
human and the version is bumped by a release pull request, so `feat:` and
`fix:` prefixes would buy nothing today. (The one exception is the literal
string `docs: not-needed`, above, which *is* parsed.)

If that ever changes — adopting Conventional Commits and `release-please` is a
1.0 item, argued in [`docs/releasing.md`](docs/releasing.md) and
[`docs/decisions/sdk-practice.md`](docs/decisions/sdk-practice.md) — it will be
announced, and it will apply going forward rather than retroactively.

### The changelog is part of the change

If your pull request changes anything a user can observe — behaviour, a CLI
flag, a public symbol, an install footprint — add an entry to the
`## X.Y.Z — unreleased` section at the top of `CHANGELOG.md`, in the same pull
request. Create that section if there isn't one.

Write prose, not a commit subject. The existing entries are the format: what
changed, why it changed, and what an existing user has to do about it. That
file becomes the release notes verbatim — see
[`docs/releasing.md`](docs/releasing.md) for how, and for everything a
maintainer does from there.
