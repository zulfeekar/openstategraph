# Contributing to OpenStateGraph

Two stacks, one repo: a TypeScript editor (`src/`) and a Python LangGraph
runtime (`backend/`). Architecture rules live in `CLAUDE.md` — read the
"Non-negotiables" section before designing anything.

## Setup

```bash
npm install && npm run dev                 # editor → http://localhost:5273
pip install -e "backend[all,dev]"          # runtime deps — see below
PYTHONPATH=backend:workflows/chinook-assistant \
  uvicorn openstategraph.api.main:app --port 8000 --app-dir backend
```

The editor runs on a deterministic Mock provider and needs no key. The backend
defaults to Ollama cloud, which needs `OLLAMA_API_KEY` in `.env` — or
`OLLAMA_HOST`, if you point it at a daemon you run; `ANTHROPIC_API_KEY` or
`OPENAI_API_KEY` is used ahead of it. The test suite needs none of them.

> This said "No API keys required." That was true only because Ollama's
> `ProviderSpec` declared no environment variables and so was always treated as
> configured — an *ambient* credential (a local daemon signing with
> `~/.ollama/id_ed25519`), not the absence of one
> (providers-and-credentials ticket 02).

`[all]` is a *contributor's* install. A consumer installs the lean core —
`langgraph`, `langchain`, `langchain-core`, `pydantic` — plus whichever extras
their workflow actually uses (`[anthropic]`, `[openai]`, `[ollama]`, `[deep]`,
`[sqlite]`, `[server]`, `[mcp]`). Adding a dependency to the core table
without the accompanying case for it fails
`backend/tests/test_distribution_metadata.py`, which is the point.

## The non-negotiables your pull request is judged against

These are the rules a maintainer will block on. They are argued in
[`CLAUDE.md`](CLAUDE.md); this table is the short form plus **the gate that
actually catches a violation** — and, where there is none, that fact stated
rather than implied. A principle with no gate is not a weaker principle; it is
one where review is the only thing between the rule and the tree, so the
argument in your pull-request description carries the weight the test would.

| Non-negotiable | What fails you |
| --- | --- |
| **Interface → Abstract → Base → Concrete.** Every entity family declares the ladder, and consumers import the `I*` interface, never the class. Inheritance must earn itself. | **Gate**, for the agent family: `backend/tests/test_agent_family.py` pins `IAgent → AbstractAgentNode → Base/React/Deep/Custom`, including that `DeepAgentNode` is a *sibling* of `ReactAgentNode`. `backend/tests/test_agent_node_wiring.py` refuses inline construction. Other families are held by the API snapshot and by review. |
| **No god classes** — ~10 public members, one reason to change. `WorkflowController` is at its ceiling; extend it with a collaborator, never a method. `WorkflowModel` is a *recorded exception*, not an open invitation. | **No gate.** Nothing counts members. `src/controller/WorkflowController.ts` states the rule in a comment and a reviewer enforces it; "this adds a public member to `WorkflowController`" is a blocking comment however good the code is. |
| **Extend by registering, never by editing the engine.** Every extension point is a `Registry<T>`; a new capability must not require touching `core/`. | **Partial.** The mechanism is tested (`src/core/kernel/kernel.coverage.test.ts`; `backend/tests/test_extensions.py`, `test_plugin_capabilities.py`) but nothing detects a capability added *by editing `core/`* instead of registering. Review catches that. |
| **`core/` imports neither React nor JointJS.** It is plain TypeScript that could run in Node or a worker. | **Gate**, as of ship-it ticket 02: `eslint.config.js` carries a `no-restricted-imports` block scoped to `src/core/**` that **errors** on `react`, `react-dom`, `@joint/*`, and relative escapes into `canvas/`, `view/`, `app/` or `controller/`. It fires in your editor, and in `npm run verify`. The tree was clean when the rule landed. |
| **Pydantic is the single source of truth for the run/stream seam**, published as the generated `docs/openapi.json`. | **No gate on the TypeScript side yet, and the rule has been narrowed to say so.** There is no pydantic → TypeScript generator and there will not be one — `src/core/runtime/RuntimeClient.ts` is a deliberate hand-written client, and the decision (plus the three reasons codegen was rejected, and the drift test that should replace it) is [`docs/decisions/typescript-runtime-types.md`](docs/decisions/typescript-runtime-types.md). Until that test lands, a hand-mirror is review-only: expect a reviewer to ask which schema it mirrors. The Python half of the seam *is* gated — see the `docs/openapi.json` row below. |
| **`port_specs.json` is generated from the TypeScript node catalogue** (the one place TypeScript is authoritative). | **Gate, both sides.** `src/nodes/portSpecs.test.ts` compares the committed bytes inside `npm run verify`; CI's `generated-port-specs` job regenerates and diffs. Fix with `npm run generate:ports`. |
| **`docs/openapi.json` is generated from the FastAPI app.** | **Gate, both sides.** `backend/tests/test_openapi_contract.py` plus CI's `generated-openapi` job. Fix with `python3 scripts/generate_openapi.py`. |
| **Expressions are a JSON AST, never host-language code.** A router predicate is serialisable data, never a Python or JavaScript lambda. | **No gate.** No schema rejects a code-shaped value in `workflow.json`. Review only. |
| **Reducers are a named enum**, and a state key more than one node type can write needs one. | **Gate, per channel**: `backend/tests/test_answer_channel_concurrency.py`, `test_attempts_channel_concurrency.py`, `test_feedback_channel_concurrency.py` assert the named reducer on `RunState.__annotations__`; `test_turn_reset.py` pins that every named reducer understands `RESET`; `test_architecture_audit_2026_08.py` fails the day a second node writes `question`. A **brand-new** channel with an inline lambda matches no test — add the assertion with the channel. |
| **The compile seam is one-directional**: `workflow.json` → runtime, never back. Nothing reads runtime objects into the model. | **No gate.** Stated in `backend/openstategraph/compile/workflow_compiler.py` and probed indirectly by `backend/tests/test_mount_overrides.py` (overrides apply to the child *document*). A new read-back that avoids those behaviours passes. |
| **Our own runtime vocabulary** — LangGraph type names never leak into `workflow.json` or `core/`. | **Weak.** `backend/tests/test_plugin_interop.py` checks a fixed token list on *plugin* import only. Nothing scans the shipped documents or `src/core/`. |
| **Middleware order is a named slot table**, never a list position or a priority integer. | **Gate.** `backend/tests/test_agent_family.py` — replacement by slot name, unknown slots appended in insertion order, removal empties a slot. |
| **The output contract is composed last and is not editable.** A developer supplies rules; the base keeps the shape of the answer. Never ship the contract as a pre-filled editable field. | **Gate — the strongest one here.** `backend/tests/test_skill_layer.py` drives the real `SystemPrompt` across agent, grader, router and orchestrator and asserts the contract is last whatever a skill says. Structurally, `backend/openstategraph/abc/prompt.py` gives the editable layer no reach into preamble or contract. |
| **Cardinality belongs to the port**, not the node: `maxConnections` on the port descriptor, enforced by `capacityRule`. No node-level "multiple edges" flag. | **Gate.** `src/core/model/contracts/ports.test.ts` pins the resolved defaults; `ConnectionValidator.test.ts` (`describe('capacity rule')`) pins replacement, fan-out and the tool bus. |
| **Never put a non-finite number in a serialisable field.** `int \| None`, with `None` meaning unbounded. | **Gate, three layers.** `src/core/model/contracts/ports.test.ts` sweeps every registered node's ports; `src/nodes/portSpecs.test.ts` requires a finite number or an explicit null; `backend/tests/test_node_catalogue.py` pins `None`-means-unbounded. |
| **The published Python surface does not change by accident.** | **Gate.** `backend/tests/test_public_api.py` diffs a *signature*-level snapshot (`backend/tests/public_api.txt`) — a renamed parameter or a flipped default fails it. Failing it is a decision to make deliberately, not a bug to paper over. |
| **We are a compiler, not a runtime.** Any proposal to interpret the graph ourselves is a proposal to reimplement checkpointing, `Send`, reducers and streaming. | **No gate, and none is possible.** Rejected in review, on the argument in `CLAUDE.md` § *We are a compiler, not a runtime*. |

Two more that are policy rather than architecture: **LangGraph and LangChain
facts come from the `docs-langchain` MCP server, never from memory**, and
**Ollama means Ollama cloud** — never benchmark, demo or debug against a local
model and report the result as representative. The cloud is reached by
`OLLAMA_API_KEY` and the `default_endpoint` on Ollama's `ProviderSpec`, not by
an ambient local daemon; a spec that reaches a vendor without naming a variable
someone can set, see and revoke is the defect ticket 02 closed.

## Tests — the gate for every PR

```bash
npm run verify              # tsc + eslint + prettier + vitest
python -m pytest -q         # FROM THE REPO ROOT. live-API tests: pytest -m live
python -m ruff check backend   # ALSO from the repo root — see below
cd backend && python -m mypy
```

**Typecheck with `npm run typecheck` (`tsc -b`), never with `npx tsc
--noEmit`.** The root `tsconfig.json` is a *solution* config — `files: []` and
nothing but `references` — so a bare `tsc --noEmit` resolves it, finds no input
files, checks nothing and exits 0. It is not a weaker gate, it is not a gate:
it reported success over 29 broken test files and one real production bug (a
dedup guard reading a field its type never declared, so it could never fire).
Only `tsc -b` follows the project references to `tsconfig.app.json` and
`tsconfig.node.json`, which is where the code actually is.

**pytest runs from the repo root, and only the root.** The root `pytest.ini`
is what declares `testpaths = workflows backend` and puts the example
workflow's `tools`/`functions` on `sys.path`. `cd backend && pytest` never
reads it, so it silently runs 49 fewer tests — the entire `workflows/` half,
which CI does run. `mypy` is the opposite: it reads
`backend/pyproject.toml` and wants to be run from `backend/`.

**`ruff` is neither, and getting it wrong looks like success.** CI runs
`python -m ruff check backend` **from the repo root**, and that is the spelling
to match. Run it from `backend/` and the path does not exist, so you get
`backend:1:1: E902 No such file or directory` — one error, no files linted, and
nothing that reads like "your lint is broken". Scoping to the files you touched
has the same shape: two sessions reported "ruff clean on the files I touched"
on a tree carrying 22 violations (`organisms-first-class` 47). Ruff finds its
config by walking up from each file, so the root spelling configures itself
correctly; if you must run it from `backend/`, the equivalent is
`python -m ruff check openstategraph tests`.

**Ruff's version is pinned** — `ruff==0.14.10` in `backend[dev]`, and `ci.yml`
installs no second copy. Do not install a floating one beside it: an unpinned
linter is a gate that can go red with no commit in between. Raising the pin is a
deliberate commit.

`mypy` is the backend's counterpart to `tsc`: its settings live in
`backend/pyproject.toml`, and it is scoped to `openstategraph/` — `tests/` is
deliberately outside it.

It **is** clean today, so any error it reports is yours — but do not take that
from this paragraph, which has now been wrong in both directions. It said
"clean today" while four errors stood, and then said "3 errors" for the two
hours it took `organisms-first-class` 48 to close them. The claim is pinned in
`backend/tests/test_the_type_gate_actually_runs.py` instead, which is the only
version of it that can fail.

**Both gates now have the pin prose cannot give them.**
`backend/tests/test_the_lint_gate_actually_runs.py` runs `ruff check backend`
and `backend/tests/test_the_type_gate_actually_runs.py` runs
`cd backend && python -m mypy`, both inside `pytest`, so a violation costs one
test run to notice. They exist because CI last executed on 2026-08-16 and
roughly 180 commits landed behind it (`organisms-first-class` 49) — **do not
read a green CI badge as a statement about the current tree.**

The type gate's price, measured rather than guessed: **~46s on a fresh checkout**
(and a ~310M `.mypy_cache`), **~3.2s warm** against a ~147s suite. **mypy is
pinned exactly** — `mypy==1.19.1` — for the same reason ruff is.

Run mypy from `backend/`. From the repo root it finds no config, checks nothing
and exits 0 — the mirror image of ruff's trap, and just as quiet.

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

`docs/openapi.json` is the same arrangement in the other language: it is
generated from the FastAPI app, committed because it is the *published*
contract (`docs/api.md` is written against it), and guarded by
`backend/tests/test_openapi_contract.py` plus CI's `generated-openapi` job.
Change a route, a response model or a docstring on an endpoint, and run:

```bash
python3 scripts/generate_openapi.py
```

The docstring matters as much as the signature — it becomes the endpoint's
`description` in the published document, so a docstring that has drifted from
the code ships as a wrong contract, not as a stale comment.

`openwiki/**` is generated too, by a scheduled GitHub Actions workflow. Do not
hand-edit it to *add* documentation — fix the source and let the refresh pick
it up. Correcting a page that names a file or a directory which no longer
exists is the one exception, because a dead link is the failure the page is
there to prevent.

Every generated page carries a `FRESHNESS` block naming the commit and date it
was generated from, so a reader can tell a current page from one written weeks
ago. The generator does not write that block and a refresh deletes it: run
`python3 scripts/stamp_wiki_freshness.py` after `openwiki code --update`, and
`backend/tests/test_a_generated_wiki_page_says_when_it_was_generated.py` will
name any page you missed.

## Adding things

Everything is a registry; extending never edits `core/`. See README's
"Extension points" table. A new workflow is a package under
`workflows/<slug>/` — `workflow.json` + `AGENTS.md` required; `tools/`,
`functions/`, `middlewares/`, `skills/`, `knowledge/`, `evals/`, `tests/` and
`data/` discovered by convention. The full contract is
[`openwiki/workflows/package-contract.md`](openwiki/workflows/package-contract.md).

## What happens to your pull request

**Open it from a fork; nothing here needs your trust.** CI runs on the
`pull_request` trigger, which means a fork's build gets a read-only token and
**no repository secrets** — so every check runs on your branch exactly as it
would on ours, and no check can be "unblocked" by a maintainer's credentials.
The only workflow that holds a secret is the release train, and it never runs
on a pull request.

Seven checks run, and one aggregate:

| Check | What fails it |
| --- | --- |
| `frontend` | `npm run verify` — tsc, ESLint, Prettier, Vitest |
| `backend` | ruff, mypy, and pytest under a coverage floor |
| `generated-port-specs` | `port_specs.json` was not regenerated after a node or port change (`npm run generate:ports`) |
| `generated-openapi` | `docs/openapi.json` was not regenerated after an API change (`python3 scripts/generate_openapi.py`) |
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
`## Unreleased` section at the top of `CHANGELOG.md`, in the same pull
request. Create that section if there isn't one.

Write prose, not a commit subject. The existing entries are the format: what
changed, why it changed, and what an existing user has to do about it. That
file becomes the release notes verbatim — see
[`docs/releasing.md`](docs/releasing.md) for how, and for everything a
maintainer does from there.
