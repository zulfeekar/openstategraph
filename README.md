# OpenStateGraph — AI Workflow Builder

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.3.0%20unreleased-informational.svg)](CHANGELOG.md)

> **Who this page is for:** you have installed nothing yet, and you want the
> stack running. Read straight down — Install, First run, Where to read next —
> and everything after that is reference. The whole documentation set is
> indexed by intent at [`docs/README.md`](docs/README.md). Changing
> OpenStateGraph itself is [CONTRIBUTING.md](CONTRIBUTING.md); adding it to a
> service you already run is
> [docs/adding-openstategraph-to-your-project.md](docs/adding-openstategraph-to-your-project.md).

**Draw an agent workflow on a canvas. Get a plain LangGraph `StateGraph` you
can import, test and deploy without this project.**

A canvas is a `workflow.json` file in your git repository. It compiles to an
ordinary LangGraph object that runs anywhere Python runs — from a script, under
`pytest`, in production, with this editor deleted.

```python
from openstategraph import load_workflow

workflow = load_workflow("./workflows/chinook-assistant")
workflow.graph          # a langgraph CompiledStateGraph. Yours now.
```

---

## Install

`openstategraph` is a **developer tool**, like a formatter: install it once,
globally, and point it at any project. You need **Python 3.11+**.

```bash
uv tool install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  --index-strategy unsafe-best-match \
  "openstategraph[server,ollama]==0.3.0rc14"
```

Swap `ollama` for `anthropic`, `openai` or `azure` — the extra names the vendor
you already pay. If your shell then cannot find the command, `~/.local/bin` is
not on your `PATH`: run `uv tool update-shell` and open a new terminal.

**That is a pre-release on TestPyPI, and every flag above is the cost of it.**
`https://pypi.org/pypi/openstategraph/json` answers 404 today, so the package
comes from TestPyPI (`--index-url`), its dependencies from PyPI
(`--extra-index-url`, because TestPyPI carries no `pydantic` 2.x), `uv` is told
it may mix the two (`--index-strategy unsafe-best-match`), and the version is
exact because pip and `uv` skip pre-releases otherwise. `pipx install` takes
the same two index flags. **All three flags disappear the day this reaches
PyPI**, leaving `uv tool install "openstategraph[server,ollama]"` —
[Releasing](docs/releasing.md) says when that is.

**The wheel carries the canvas.** The built editor ships as package data — 110
files, 1.6 MB of a 4.82 MB wheel, and the browser payload with Mermaid is 57%
of the download — so one process serves the editor at `/`, the chat surface at
`/chat` and the API under `/api`, from one origin. No clone, no Docker, no
`npm`. Measured footprint:
[`docs/what-is-this.md`](docs/what-is-this.md#the-dependency-picture-measured).

> Changing OpenStateGraph itself rather than using it? That is a different
> path: [Working on OpenStateGraph itself](#working-on-openstategraph-itself).

## First run

```bash
mkdir my-demo && cd my-demo
openstategraph init .
```

`init` turns the directory you are standing in into a project, and prints what
it wrote:

| It writes | What it is |
| --- | --- |
| `openstategraph.yaml` | the config — `workflows_dir:`, and the project's own identity |
| `.gitignore` | `.env` and `.openstategraph/` |
| `workflows/starter/` | the smallest workflow that runs: Input → Agent → Output, pinning no model, with its own `tests/` |
| `AGENTS.md` | how to build here, addressed to your coding agent |
| three skills | under **both** `.claude/skills/` and `.agents/skills/`, so whichever convention your agent follows it finds them |
| four agent config files | `.mcp.json`, `.vscode/mcp.json`, `.cursor/mcp.json`, `.codex/config.toml` — one entry each, from one descriptor |

It never writes a `.env`: a generated credential file is a committed one
waiting to happen. An existing directory is merged into, never overwritten, and
a conflicting entry is reported as kept. Full flags:
[`init`](docs/cli.md#init).

**Now give it one credential.** `init` never writes a `.env` for you, and
without one the very next step refuses: a run prints *"the only provider
integration installed; set `OLLAMA_API_KEY` or `OLLAMA_HOST` to use it"* and
stops. One line fixes it:

```bash
echo 'OLLAMA_API_KEY=your-key-here' > .env
```

Any one of the providers in [Environment variables](#environment-variables)
will do — `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or the Azure set instead, if
that is the vendor you already pay. `openstategraph env-example` prints the
whole block with the names and no values; `openstategraph providers` then says
which of them this install can actually see. (A workflow with no model-calling
node needs none of this.)

Then open it:

```bash
openstategraph .
```

One verb, pointed at a folder. It says **which** directory and which workflows
root it chose and why — the failure this verb exists to end is standing in the
wrong place and silently editing another project's workflows — picks a free
port, and opens your browser on the editor, with the chat at `/chat` and the
API at `/api/health`. `workflows/starter` is on the canvas. Press **Run**.

## With your coding agent

Open your coding agent in the project and say:

> **use OpenStateGraph** — I want a workflow that reads a support ticket,
> decides which team it belongs to, and drafts a reply the team can send

That sentence is the whole interface, and what follows is not a code generator
taking a guess. Your agent reads the ground rules first — the node vocabulary
and the engineering rules — so it cannot invent a node type that compiles to
nothing. Then it interviews you one question per turn, files the work as cards
on the board, and builds one card at a time test-first: failing test, watch it
fail, make it pass, **break the fix and watch it fail again**, commit. The
board refuses a finished card that carries no commit.

It will not run your workflows without permission (runs are off by default,
`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`, because a run costs money), and it will not
draw a picture of something that already compiles — a diagram comes from the
compiler (`openstategraph graph`), never from the agent's imagination.

**Two doors, same steps, same board.** Your agent uses whichever it has: the
`openstategraph` **MCP** server, which `init` registered in all four config
files ([the MCP layer](docs/mcp.md)), or the **command line**, where every step
is a verb ([the `openstategraph` command](docs/cli.md)). The skill is
`.claude/skills/openstategraph/` (and `.agents/skills/openstategraph/`), and its
`references/engineering-rules.md` is generated at install time from the same
text the `get_engineering_rules` MCP tool serves, so the two doors cannot
disagree. Full walk:
[the OpenStateGraph skill](docs/the-openstategraph-skill.md).

## The board

The editor reads your runs back. A radar in the top bar opens the **patrol
board**. A patrol reads every recorded finding from your own runs — a repeated
tool call, an unstable result, a node that failed — classifies each one, and
files a card. It reads; it never runs anything, and it costs no model call.

```bash
openstategraph patrol run          # 0 finding(s) read / 0 card(s) filed, on a fresh project
openstategraph kanban triage       # what to do first, and the rule that says so
```

Four columns — `Detected` (needs doing, not deciding), `Needs You` (a judgement
only a person may make), `In Progress`, `Resolved`. Fixing a card is
**evidence-gated rather than trust-gated**: `attend` is atomic, `red` refuses
without a test id and a reason, `green` refuses a test id that disagrees with
the one recorded at `red`, and `finished` refuses unless both are durably on the
card. Every verb is also an MCP tool. Full page:
[the patrol board](docs/the-patrol-board.md).

## Building a new module

When nothing in the vocabulary fits your step, the answer is a **new module
built through the family's base and registered** — never a special case wired
into the engine, and never a node type invented in a prompt.

**Run the interview first.** [`skills/atom-forge/`](skills/atom-forge/SKILL.md)
is the agent-agnostic procedure: plain markdown, no special tooling. It routes
first (is this on the canvas, or does something on the canvas use it?), then
asks one question at a time across nine dimensions, **verifying each answer
against this installation** rather than taking it on trust. An interview that
ends *"this platform cannot do that yet — here is the ticket"* is a **correct
outcome**. [Building an atom](docs/building-an-atom.md) is the pipeline it
hands off to.

## Where to read next

**[`docs/README.md`](docs/README.md) is the documentation index** — one
canonical page per intent. The five most people want first:

| I want to… | Read |
| --- | --- |
| decide whether this is for me | [What this is](docs/what-is-this.md) — the tiers, how it compares to Langflow/Flowise/n8n/Dify and to raw LangGraph, the measured footprint, and when *not* to use it |
| understand what I am drawing | [On the canvas](docs/on-the-canvas.md) — what a workflow, a node, a mount and a loop are |
| look up a node type | [The module index](docs/modules.md) — every built-in, one line each |
| use it in a project of my own | [Using it in your project](docs/adoption.md), then [the HTTP API](docs/api.md) |
| have my own LLM compose the graph | [The MCP layer](docs/mcp.md) |

---

## The CLI at a glance

Every verb, with its flags and exit codes, is [`docs/cli.md`](docs/cli.md) —
one enumeration, deliberately, so a reader looking up a flag has one place to
look.

| Verb | What it does |
| --- | --- |
| [`init`](docs/cli.md#init) | make a directory you already have into a project |
| [`new`](docs/cli.md#new) | start a new package from a scaffold (`--list-templates`) |
| [`examples`](docs/cli.md#examples) | `list` the worked examples in the wheel, `copy` one into your project |
| [`nodes`](docs/cli.md#nodes) | every node type this install has, and one type's fields, options and ports |
| [`validate`](docs/cli.md#validate) | check a package compiles, before anything costs money |
| [`graph`](docs/cli.md#graph) | the topology the compiler actually built, as Mermaid text — no network call |
| [`run`](docs/cli.md#run) | ask a package a question |
| [`resume`](docs/cli.md#resume) | answer an approval a run is waiting on |
| [`eval`](docs/cli.md#eval) | score a package against a dataset whose answers you know |
| [`kanban`](docs/cli.md#kanban) | the board, one card at a time — `file`, `triage`, `attend`, `show`, `stage`, `answer`, `release` |
| [`patrol`](docs/cli.md#patrol) | `run` a patrol over your recorded runs and file what it finds |
| [`threads`](docs/cli.md#threads) | read back what a past run *said* |
| [`runs`](docs/cli.md#runs) | read back what your runs *cost* |
| [`knowledge`](docs/cli.md#knowledge) | `build` or `list` a package's second brain |
| [`open`](docs/cli.md#open) | open the editor on the project you are standing in — `openstategraph .` |
| [`serve`](docs/cli.md#serve) | the editor, the chat and the API on one port |
| [`providers`](docs/cli.md#providers) | which providers are installed, which have a credential, and `--check` whether they answer |
| [`env-example`](docs/cli.md#env-example) | print the variable names you need, into your own `.env` |
| [`mcp`](docs/cli.md#mcp) | let your own LLM compose workflows |
| [`export plugin`](docs/cli.md#export-plugin) | hand the package to a different client |

The exit codes are fixed — `0` ok, `1` failure, `2` usage, `3` a missing extra
— so `validate` works as a CI gate. `--json` on `run` prints the whole result
rather than the answer alone. The same thing from Python is
`load_workflow("./workflows/my-thing")` — see
[Using OpenStateGraph in your project](docs/adoption.md).

The lean core is deliberately four dependencies, so a `[ollama]`-only install
prints one warning on every command: the checkpointer fell back to memory
because `langgraph-checkpoint-sqlite` is not installed. That is honest rather
than broken — a run still works, an approval or a follow-up question just will
not survive the process. Add `[sqlite]` (or `[server]`, which includes it) when
you want durable threads.

## Environment variables

None are required to *start* the backend, and a workflow that calls no model
runs without any of them. Calling a model needs one provider's credentials from
the table below. `openstategraph env-example` prints this block for your `.env`;
`openstategraph providers` says which of them this install can actually see.

| Variable | Effect |
| --- | --- |
| `ANTHROPIC_API_KEY` | backend model resolution prefers Anthropic when set |
| `OPENAI_API_KEY` | checked next, if Anthropic's key is absent |
| `OLLAMA_API_KEY` | configures Ollama **cloud** |
| `OLLAMA_HOST` | *instead* of the key: a daemon you run, which owns its own auth. Also the endpoint, ahead of `OLLAMA_ENDPOINT` |
| `OLLAMA_ENDPOINT` | where the cloud is; defaults to `https://ollama.com`, rarely set |
| `OPENSTATEGRAPH_OLLAMA_MODEL` | overrides the Ollama cloud model id (default `ollama:gpt-oss:120b-cloud`) |
| `AZURE_OPENAI_API_KEY` | configures **Azure OpenAI** — a separate provider, not a spelling of OpenAI |
| `AZURE_OPENAI_ENDPOINT` | required with it: your resource's URL |
| `AZURE_OPENAI_API_VERSION` | required with it; `OPENAI_API_VERSION` is read as a fallback |
| `AZURE_OPENAI_DEPLOYMENT` | optional: the deployment to address, if your endpoint needs one named |
| `OPENSTATEGRAPH_LOG_LEVEL` | backend log verbosity — `DEBUG`/`INFO`/`WARNING`/`ERROR` (default `INFO`) |

**Azure OpenAI needs four variables, and three of them are settings rather than
credentials.** `AzureChatOpenAI` cannot be constructed without an endpoint and
an api-version, so this provider reports itself *configured* only when they are
present, and `openstategraph providers` says `needs a setting` and names the
missing one. The three settings are **not** forwardable from a run request — a
request that could name the address could redirect the server's own key to it —
so Azure is configured on the server, never from the editor's dialog.

`OLLAMA_API_KEY` and `OLLAMA_HOST` are alternatives, not a pair: `is_configured`
takes **any** of a provider's `env_vars`. With both set the host wins for
routing and the key rides along as a bearer token. Endpoint precedence is tuple
order — `OLLAMA_HOST`, else `OLLAMA_ENDPOINT`, else `https://ollama.com`.
Anthropic and OpenAI are passed no `base_url` at all; their SDKs already read
`ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL`/`OPENAI_API_BASE`. See
`builtin_specs()` in
[`backend/openstategraph/providers.py`](backend/openstategraph/providers.py).

Keys typed into the editor's own credentials dialog are a **second**,
browser-side path used by the canvas preview. The canonical explanation of the
two model paths, and which credential reaches which, is
[docs/getting-started.md §3](docs/getting-started.md#3-models-and-credentials);
this table is the quick reference for the backend.

## Working on OpenStateGraph itself

Everything above is addressed to somebody *using* OpenStateGraph. If you are
changing it, the repository has its own front door, and this page does not
restate it:

- [**CONTRIBUTING.md**](CONTRIBUTING.md) — the checkout setup (`./start dev`,
  the two-terminal fallback, Docker), the test gate for every pull request, the
  architecture of `src/`, the extension-point table, what had to be rebuilt
  over the open-source JointJS core, and the example workflows this checkout
  carries
- [**CLAUDE.md**](CLAUDE.md) — the architecture contract. Read
  "Non-negotiables" before designing anything; most rejected proposals are
  rejected by a rule already written there
- [**CODE_OF_CONDUCT.md**](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1
- [**SECURITY.md**](SECURITY.md) — a local-first tool with no authentication;
  read the documented trade-offs before exposing it to anything
- [**CHANGELOG.md**](CHANGELOG.md) — what changed, per release
- [**THIRD_PARTY_NOTICES.md**](THIRD_PARTY_NOTICES.md) — MPL-2.0, OFL-1.1 and
  redistributed-data attributions

Issues and pull requests are welcome. The house style is TDD, and `core/` is
pure TypeScript with no excuse for untested logic. Every pull request runs the
same two commands CI does:

```bash
npm run verify      # tsc + eslint + prettier + vitest
python -m pytest    # backend + workflow tests (live-API tests are opt-in: -m live)
```

**Docs note:** LangGraph and LangChain facts in this repo come from the
`docs-langchain` MCP server (<https://docs.langchain.com/mcp>), never from
memory.

## License

MIT — see [`LICENSE`](LICENSE). Third-party components keep their own licences;
the ones with live obligations (JointJS under MPL-2.0, the Inter typeface under
OFL-1.1, and the redistributed Chinook sample database under MIT) are recorded
in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
