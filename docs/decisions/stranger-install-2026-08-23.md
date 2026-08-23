# A stranger installs it and asks for a workflow — 2026-08-23

`launch-readiness/12`.

A run of the shipped artifact by somebody with no knowledge of this
repository. The rule of the exercise: read only what a new user can find
(`README.md`, `docs/`, the product's own output, the screen), and when stuck,
**record being stuck first** and only then look up the answer, so the gap
between what a stranger can find and what is true is the deliverable.

Nothing was fixed during the run. Everything below is written up as filed
tickets rather than repaired in place.

## The isolation

`/tmp/stranger`, a fresh `python3 -m venv` on Python 3.13.9. Nothing from this
checkout is on the path; the wheel came from TestPyPI, so what is measured is
the artifact and not the working tree.

## 1 — Install

**The naive command fails, and the README says so first.** The README's own
onramp is annotated *"That upload has not happened yet"*, which is honest, and
it is also the first thing a stranger reads that tells them the three-line
install does not exist yet.

```
$ pip install "openstategraph[server]"
ERROR: Could not find a version that satisfies the requirement
       openstategraph[server] (from versions: none)
```

**TestPyPI alone fails too**, and this is the failure a stranger handed an rc
would actually hit:

```
$ pip install --index-url https://test.pypi.org/simple/ "openstategraph[server]==0.3.0rc2"
ERROR: Could not find a version that satisfies the requirement pydantic<3,>=2.9
       (from openstategraph) (from versions: 1.4a1, 1.5a1)
```

TestPyPI has no `pydantic` 2.x, so `--extra-index-url https://pypi.org/simple/`
is mandatory and is written down nowhere a stranger would find it. The error
names `pydantic`, not the missing index, so the obvious reading is "this
package wants a pydantic that does not exist".

**With the extra index it installs in 13 s**, 46 distributions:

```
$ pip install --index-url https://test.pypi.org/simple/ \
      --extra-index-url https://pypi.org/simple/ "openstategraph[server]==0.3.0rc2"
Successfully installed … openstategraph-0.3.0rc2 … (46 packages, 13s)
```

Later, `[mcp]` on top: a further 15 distributions in 8 s.

## 2 — Getting it running

`openstategraph init my_demo` is the best surface in the product. It states
the missing-provider condition unprompted, names the three fixes, and explains
why it will not write a `.env` for you:

> default model: (none) — no model provider integration is installed, so every
> run will fail — pip install 'openstategraph[anthropic]', pip install
> 'openstategraph[openai]' or pip install 'openstategraph[ollama]', then start
> again
>
> no .env was written — a generated credential file is a committed one waiting
> to happen.

`openstategraph providers` repeats it per provider, and ends with a sentence
that is the rarest kind of honesty in this class of tool:

> "configured" means a credential is present in this environment — not that
> the endpoint is reachable, and not that a request will be answered.

`openstategraph run workflows/starter "hello"` with no provider exits **3**
with the same actionable sentence. Exit codes are as documented.

`openstategraph serve --port 8811` was up in **~4 s**, and proved it serves
the artifact rather than a checkout:

```
INFO:openstategraph.api.editor_assets:editor served from
  /private/tmp/stranger/venv/lib/python3.13/site-packages/openstategraph/api/static/editor
```

`GET /api/health` → `{"ok":true,"editor_stale":null,"model_configured":false}`.

**Measured: `pip install` → both surfaces rendering = 1 min 45 s**
(23:15:13 → 23:16:58), including `init`, `examples copy` and `serve`.

## 3 — Both surfaces render

Editor at `/` renders from the wheel, with the missing-provider warning as an
in-app toast carrying a **"Show me where"** action. Chat at `/chat` renders —
and says **"No workflows are published yet."**

That is the end of the README's own three-line onramp. `init` writes
`workflows/starter` with `published: false`, so the chat URL `serve` prints in
its own startup banner lands on an empty picker with no in-page way out. The
`examples copy` command explains publishing; the chat page does not.

## 4 — Asking the app to build a workflow

**I got stuck here, and the stuck is the finding.**

I looked for a "describe what you want and I'll build it" surface. `+ New`
makes an empty canvas. The **Workflows** panel offers *Start from* with four
scaffolds (`minimal`, `loop`, `routed-qa`, `team`) — copies, not a builder.
The full interactive surface enumerates 44 controls and none of them is an
architect. I could not find one.

**What the answer was:** for a wheel install there is no in-app builder at
all. The "build me a workflow" flow is `docs/mcp.md` §2 — *your own* MCP
client's model composes the document, and this server is the ground truth.

**Where it was hiding:** the README advertises "Two hidden infrastructure
workflows (`concierge`, `workflow-architect`) power the chat gateway and the
build-me-a-workflow flow" without saying **they are checkout-only**. The wheel
carries `prebuilt_architect.py` — the architect's *validation tool* — but
neither workflow package. `find` over `site-packages` returns no
`workflow-architect`, and `/openapi.json` has no architect route. A stranger
reading the README expects a feature that is not in the artifact.

`docs/mcp.md` also still says *"there is no PyPI wheel yet"* in its
configuration example, which is now stale against the rc.

### The MCP loop, exercised

`openstategraph mcp` starts with no provider key and its instructions are
excellent — a numbered loop, `get_node_vocabulary()` mandatory first, compile
after every revision, "a document you have not compiled is a guess". Eight
tools; `run_workflow` correctly absent under
`OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`.

**There is no interview.** The server tells the client's model to compose
directly. That is a defensible design — the interview, if any, happens in the
user's own client — but it means the ticket's "let the built-in skill
interview you" has no referent in the artifact.

**Discovery worked: it offered what already ships.** `get_node_vocabulary()`
returned 36 node types including `tool.sql-list-tables`, `tool.sql-get-schema`,
`tool.sql-query` and `tool.mcp`. Nothing pushed me toward building a new
capability. That is a discovery *success* and should be scored as one.

**But the vocabulary omits the config schema.** Each tool node reports its
ports and a description saying "the *configured* SQL database" — and never
says what key configures it, or that there is a `data` schema at all;
`document_shape` shows `"data": {}`. I guessed `database` from the node's
prose. I was right, but only by luck; the correct value is a path relative to
the workflows root (`sql-qa/data/Chinook_Sqlite.sqlite`), which nothing in the
vocabulary states. A client model composing blind would produce a
tool-less agent that still validates.

### The compile loop reports a false alarm

My six-node document compiled `validated: true`, `findings: []` — and three
warnings:

> No implementation for tool "tool.sql-list-tables" — the agent ran without
> it, so its answer may not be grounded in that data source.

So I compiled the **shipped, working `sql-qa` gallery example** through the
same tool. Identical three warnings. The warning is wrong: `openstategraph
validate workflows/sql-qa` reports `VALID` with
`Tool bindings: {'answer1': ['t-tables','t-schema','t-query']}` and no
warnings at all. `mcp_server.compile_workflow` is stateless and holds no
package root, so the tools cannot resolve there — the same honest limitation
its own docstrings record for mounts, surfaced as a false accusation instead
of a stated limit.

Its tense is wrong too — *"the agent **ran** without it"* — on a call that
compiles and runs nothing. For a loop whose whole design is "loop on evidence,
never on the model's confidence", this is bad evidence: a client model doing
what the instructions say would revise a correct document forever.

Also: `save_workflow_draft(slug=…, document=…)` rejected the argument shape
the compile step's own output suggests, with a raw pydantic traceback —
`name Field required`.

Written to disk as a package, my composed workflow is clean:

```
$ openstategraph validate workflows/chinook-questions
VALID
Topology: 3 graph nodes · entry ['in1'] · exits ['out1']
Tool bindings: {'a1': ['t1', 't2', 't3']}
```

Published, it appears in `/chat` with a live-flow diagram. Placement is
legible — the three tool nodes are bindings, not graph nodes, and the diagram
says `3 graph nodes` consistently. Minor: the output node draws as `out1`
while its neighbours carry titles.

## 5 — The domain question

**Blocked, and blocked twice.**

*First*, on the thing the run was meant to measure. Asked in the chat surface
with no provider configured:

> **How many customers are in the database?**
>
> `Runtime error (500): Internal Server Error`

The server log shows the exception carried a perfect message the whole way:

```
openstategraph.errors.NoProviderInstalled: no model provider integration is
installed, so every run will fail — pip install 'openstategraph[anthropic]' …
  at api/routes/runs.py:409  resolve_model(...)
```

`/api/runs/stream` does not catch `NoProviderInstalled`, so the one surface a
non-technical user is pointed at turns the product's best error message into a
bare 500. The CLI gets the sentence; the chat gets nothing. This is the worst
thing found in the run.

*Added after the measurement, on reading `.scratch/` for the close:* this is
**already an open ticket** — `providers-and-credentials/15`, same file, same
line, filed the same day from the **editor**. The stranger run reproduces it
from the published rc and on `/chat`, where the wording is worse
(`Runtime error (500): Internal Server Error` names HTTP, not the product) and
the audience is less able to recover. Recorded here as corroboration, not as a
new discovery.

*Second*, on the setup step. Reading the repo's `.env` for a key is denied by
this environment's permission settings, via both Bash and the file reader. The
ticket's own instruction is to say so and stop rather than guess, so **no live
model run was performed and no Chinook answer was obtained.**

Ground truth was verified against the wheel's own copy of the database so the
next run does not have to:

```
SELECT COUNT(*) FROM Customer -> 59
SELECT COUNT(*) FROM Invoice  -> 412
SELECT COUNT(*) FROM Track    -> 3503
```

**Time from `pip install` to first answer: not reached.** The measurable
number the run does have is 1 min 45 s to both surfaces rendering, and roughly
seven minutes to a validated, published, composed workflow — with the last
step, the answer, unreachable on a fresh install without a credential and
unreachable here for want of one.

## What a fresh install tells you about credentials

Worth recording as a positive: the no-key state is announced at `init`, at
`providers`, at `serve` startup, in `/api/health`, in the editor as a toast,
and as CLI exit code 3. Six surfaces, all honest. The seventh — the chat — is
the one that fails, and it is the one a stranger reaches first.

## Scored against the owner's list

| | |
| --- | --- |
| Interview | none exists in the artifact; the MCP server instructs, it does not ask |
| Existing vs new | **offered existing** — the SQL and MCP atoms surfaced in the vocabulary unprompted |
| Placement legible | yes; diagram and node counts agree |
| Validates | yes, via the CLI; the MCP path adds three false warnings |
| Runs | not reached — no credential |
| Failed silently | the MCP false warnings, and `data`-schema omission from the vocabulary |
| Failed loudly but uselessly | the chat 500 |
