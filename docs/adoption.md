# Using OpenStateGraph in your project

On a fine day a developer decides to use this in their project. What do they
actually do?

There are three ways in, and they are genuinely different — different install,
different upgrade story, different thing living in your repository. Pick one
deliberately; mixing them is where confusion starts.

| | (a) Fork / checkout | (b) Artifact | (c) MCP |
| --- | --- | --- | --- |
| You run | the whole stack | nothing of ours in prod | an MCP server process |
| Your workflow lives in | `workflows/<slug>/` **in your fork** | your own repo | your own repo |
| Who authors the graph | you, on the canvas | you, once, anywhere | your own LLM client |
| Upgrading | `git merge upstream` | bump the runtime you vendored | restart the server |
| Maturity | **primary today** | works, packaging still manual | works, no auth layer |

> **One honest framing before any of them.** OpenStateGraph is a *compiler*,
> not a runtime. Whatever route you take, the thing you end up owning is a
> plain LangGraph `StateGraph` and a folder of ordinary files. The editor is an
> authoring tool, not a dependency of what you author.

---

## (a) Fork / checkout — the primary mode today

**The repository is the workspace.** There is no "install OpenStateGraph into
your app" step, because your workflows live inside the checkout, next to the
two shipped examples.

```bash
git clone <your-fork-of-openstategraph> openstategraph
cd openstategraph
npm install
./start dev
```

That gives you two processes, supervised by [`scripts/dev.sh`](../scripts/dev.sh):

- **editor** — the Vite SPA on <http://localhost:5273>
- **runtime** — `uvicorn --reload` on <http://localhost:8000>

Stop with `./start stop`; watch with `scripts/status.sh`. No API key is needed
to get a first answer — the backend defaults to Ollama **cloud** and the canvas
preview defaults to `Mock · Offline`.

### Where your work goes

```bash
python3 scripts/new_workflow.py my-thing      # or scripts/new_team.py
```

That scaffolds `workflows/my-thing/`. From then on you are editing files in
**your** fork:

```
workflows/my-thing/
├── workflow.json      required — the graph, vendor-neutral JSON
├── AGENTS.md          required — what this workflow is, for humans and agents
├── tools/             discovered by convention: BaseTool subclasses
├── functions/         plain callables a function.* node names
├── middlewares/       LangChain middleware contributed by slot name
├── skills/            skill documents an agent's skill port can bind
├── knowledge/         the second brain: index tier + doc tier
├── tests/             pytest — these are real tests, not decoration
└── data/              fixtures, sample databases
```

Nothing here is a proprietary format. `workflow.json` is JSON, the rest is
Python and Markdown. That is the point: **your flow is a file in git**,
reviewable in a pull request and diffable.

### Production shape

```bash
./start          # build + run the Docker image, then http://localhost:8000/
./start logs
```

`./start` builds a multi-stage image — Node compiles the editor, a throwaway
stage builds the Python wheels, and the final layer is Python slim plus the
built `dist/`, `backend/` and `workflows/`. **One container serves the editor,
`/chat` and the API from a single origin on port 8000.** The frontend calls
`http://localhost:8000` absolutely, so map that port as-is. `./workflows` is
bind-mounted, so a workflow saved in the container lands in the repo.

One worker, deliberately: the human-in-the-loop checkpointer is an in-process
`InMemorySaver`. Scaling out needs a persisted checkpointer first.

### Upgrading — the honest part

You forked, so upgrading is a merge:

```bash
git remote add upstream <the-upstream-repo>
git fetch upstream
git merge upstream/main
```

The friction is real and worth stating before you commit to this mode:

- **Your workflows sit in a tracked directory of the upstream tree.** They are
  *your* files with *their* siblings (`chinook-nl-to-sql`, `page-analytics`,
  `concierge`, `workflow-architect`) around them. Adding files rarely
  conflicts; deleting the shipped examples to tidy up guarantees a conflict on
  every upgrade. Leave them, or delete them once in a commit you are willing to
  re-resolve.
- **Any edit you make to `src/`, `backend/` or `scripts/` is a merge you own
  forever.** If you can express the change as a *registration* — a node type, a
  tool, a provider, a validation rule — do that instead; the extension points
  are registries precisely so that a new capability never edits the engine. See
  [Building an atom](building-an-atom.md).
- **`workflow.json` is versioned with a migration chain**, so documents carry
  forward. Package conventions (`tools/`, `knowledge/`) are discovered rather
  than declared, so new conventions arrive additively.
- **There is no `openstategraph upgrade` command.** Merging is the mechanism.

If that friction is the dealbreaker, you want mode (b).

---

## (b) Artifact — you never run the editor in production

Author once, commit the package to **your own** repository, and run the
compiled graph from your own service. The editor's involvement ends at
authoring time.

What you commit is exactly the package layout above — most importantly
`workflow.json`. Loading and running it is ordinary Python:

```python
import json

from langchain.chat_models import init_chat_model
from openstategraph.compile.node_runtime import NodeRuntime, RunState
from openstategraph.compile.workflow_compiler import WorkflowCompiler

document = json.load(open("workflow.json"))["document"]
runtime = NodeRuntime(model=init_chat_model("ollama:gpt-oss:120b-cloud"))
graph = WorkflowCompiler().build(document, RunState, runtime.factory(document))

final = graph.invoke(
    {"question": "...", "attempts": 0, "decisions": {}, "outputs": {}},
    {"recursion_limit": 50},
)
print(final["answer"])
```

`graph` is a compiled LangGraph object. Wrap it in your own FastAPI app, call
it from a script, exercise it with `pytest`, deploy it wherever Python runs.

### Be honest about the install

**There is no PyPI package yet.** You cannot `pip install openstategraph`
today, and this page will not print a command that fails. The runtime is
consumed one of two ways right now:

```bash
# A checkout of the backend, installed into your environment
pip install -e /path/to/openstategraph/backend

# — or, without installing at all —
PYTHONPATH=/path/to/openstategraph/backend python your_service.py
```

The distribution is named `openstategraph-backend`; the import package is
`openstategraph`. The Docker image is the third option — it already contains
the runtime, so a service that shells out to the container needs nothing
installed locally.

> **Recorded next step:** packaging the backend as an installable
> `openstategraph` wheel (published, versioned, `pip install openstategraph`)
> is the change that makes artifact mode a first-class consumption path rather
> than a checkout dependency. Until it lands, mode (b) means vendoring a
> backend checkout or the image.

---

## (c) MCP — your own LLM composes the workflow

You do not open the canvas at all. You point an MCP client (Claude, Cursor, an
in-house agent) at the server, and your own model composes the document while
OpenStateGraph acts as ground truth and artifact factory.

```bash
python -m openstategraph.mcp_server                       # stdio
OPENSTATEGRAPH_MCP_TRANSPORT=streamable-http \
  python -m openstategraph.mcp_server                     # server deployment
OPENSTATEGRAPH_MCP_ALLOW_RUNS=0 ...                       # no model-touching tool
```

The artifacts land in **the client's own repository** — the server writes
nothing in the primary flow. The full worked example, including the client
config JSON and a document that genuinely validates, is
[The MCP layer](mcp.md). The decision record and its honest limits (no
authentication layer, chief among them) are
[`decisions/mcp-layer.md`](decisions/mcp-layer.md).

---

## What artifacts you own

Every one of these is a plain file. None of them is a blob in our database,
because there is no database.

| Artifact | Where | Format | Who writes it |
| --- | --- | --- | --- |
| `workflow.json` | `workflows/<slug>/` | versioned JSON, vendor-neutral | the editor, or your LLM via MCP |
| `AGENTS.md` | `workflows/<slug>/` | Markdown | you |
| `tools/*.py` | `workflows/<slug>/tools/` | Python `BaseTool` subclasses | you |
| `functions/*.py` | `workflows/<slug>/functions/` | plain callables | you |
| `middlewares/*.py` | `workflows/<slug>/middlewares/` | LangChain middleware, contributed by slot name | you |
| `skills/*` | `workflows/<slug>/skills/` | skill documents | you |
| `knowledge/*` | `workflows/<slug>/knowledge/` | Markdown, index tier + doc tier | generated, then owned by you |
| `tests/*.py` | `workflows/<slug>/tests/` | pytest | you |
| `data/*` | `workflows/<slug>/data/` | fixtures, SQLite, CSV | you |

Two properties worth naming, because they are what "you own it" means:

- **Diffable.** A change to a graph shows up in a pull request as a change to
  JSON, not as "someone edited the flow in the UI on Tuesday".
- **Runnable without us.** `tests/` runs under plain `pytest`; the compiled
  graph runs under plain Python. Delete this editor and the package still
  works.

---

## The publish story — draft in the editor, live in `/chat`

Authoring and serving are separated by one deliberate human action.

```
draft on the canvas  ──►  Save  ──►  workflow.json (published: false)
                                          │
                                     a human clicks Publish
                                          ▼
                            published: true  ──►  visible in /chat
```

- **Saving writes a draft.** `published` is `false` until someone flips it.
- **`/chat`** (<http://localhost:8000/chat>) is the customer-facing surface: no
  canvas, just a conversation. A concierge workflow routes the question to
  whichever *published* workflow can answer it and streams the run back token
  by token. Drafts are invisible there.
- **Publishing is never automated.** It is not exposed over MCP, and MCP's
  `save_workflow_draft` refuses to overwrite an already-published workflow.
  That is the trust boundary: a machine may compose and propose; a human looks
  at the graph and decides it may talk to customers.
- `list_workflows(surface="chat")` is the same filter, read-only.

---

## Which mode should you pick?

- **Trying it, or building workflows as your product** → (a). It is the mode
  everything is tested against.
- **Workflows are a component of an existing Python service** → (b), accepting
  the vendored-backend caveat until the wheel lands.
- **Your team already lives inside MCP clients and wants graphs generated from
  a chat** → (c), behind your own reverse proxy.

Next: [Getting started](getting-started.md) for the first run,
[Patterns](patterns.md) for what to build, [The MCP layer](mcp.md) for the
worked MCP example.
