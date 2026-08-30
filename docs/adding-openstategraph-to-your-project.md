# Adding OpenStateGraph to a project you already have

You have a Python service. It has an endpoint that answers a message. You want
that answer to come from a workflow you can draw, version and test, instead of
from a prompt string in a handler.

This page is that walk, in order, from `pip install` inside a directory that
already has an app in it, to that app's own endpoint answering through a
workflow. Nothing here assumes a clone, a canvas, or a workflow you already
drew.

- [Getting started](getting-started.md) is the *contributor's* path — it opens
  on `git clone`, and builds the editor from source.
- [Using it in your project](adoption.md) is the reference behind this page:
  the three consumption modes compared, every CLI flag and exit code, the full
  `RunResult`, the publish lifecycle. When this page needs a fact, it links
  there rather than restating it.
- [Wiring a workflow into your app](wiring-it-in.md) is what to read *after*
  this one — streaming, and the identity keys.

**Every command below was executed** before it was written down, in a
throwaway FastAPI project outside any checkout, in its own virtualenv
(`launch-readiness/190`). The install commands were run against the published
distribution; everything after them was run against a wheel built from this
repository, for the reason §0 gives.

## 0. The install line, and the one a stranger tries first

`openstategraph` **is not on PyPI**. A bare `pip install openstategraph` returns
a 404, and a 404 from pip reads like your typo rather than our gap. It *is*
published to **TestPyPI**, which is a real, installable index — the release
train stops there pending an approval nobody has clicked, and
[Releasing](releasing.md) says when that changes.

The obvious next move is to point pip at TestPyPI with `-i` (or its long
spelling, `--index-url`) and nothing else. **That fails**, and this is what it
looks like:

```
ERROR: ResolutionImpossible
Additionally, some packages in these conflicts have no matching distributions
available for your environment:
    pydantic
```

If that is where you are: the missing flag is `--extra-index-url`, and the
command below is the one to use.

**TestPyPI is not a mirror of PyPI.** It carries this distribution and almost
none of its dependencies — no `pydantic` 2.x, no `langgraph`, no `langchain` —
and `--index-url` *replaces* the default index rather than adding to it. pip
then reports the missing dependency and never mentions the index it cannot
reach, so the obvious reading is *this package depends on a pydantic that does
not exist*. Add the second index and it resolves:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            "openstategraph[ollama]==0.3.0rc7"
```

That was run into an empty virtualenv and installs the distribution plus
`langgraph`, `langchain`, `langchain-core`, `pydantic` and the one provider
integration you named. Extras resolve through the same pair —
`[ollama,sqlite]` and `[server,ollama]` were both installed this way — because
every extra's own dependencies come from PyPI like the core's.

The version is pinned because a pinned version is a version a test can check,
and this repository holds every documented pin against
[`backend/pyproject.toml`](../backend/pyproject.toml). It is not, today, what
makes the command work: pip normally excludes pre-releases from an unpinned
requirement, but it falls back to them when no stable version satisfies the
requirement at all, and every published version of this distribution is a
release candidate. Unpinned resolves to the same wheel — until the day a stable
one exists, when it will silently stop meaning the same thing.

After the PyPI gate is approved the whole detour collapses:

```bash
pip install "openstategraph[ollama]"          # once published
```

> **The published pre-release is older than this page, and one of the gaps
> lands on the shape this page recommends.** The pin above is what TestPyPI
> serves; it was uploaded before four changes that reach a reader here. Two are
> behavioural and are called out where they bite — `init` in
> [§2](#2-init-into-the-directory-you-already-have) and error handling in
> [§4](#4-rewiring-your-endpoint), and §4's code is written to be correct on
> both. Two are fixes it does not have: repeated `ask()` in one long-lived
> process — precisely what a service does — returned an empty string on every
> second call until `launch-readiness/171`; and the shipped `chinook-assistant`
> package bound none of its own tools until `every-workflow-green/43`, which
> landed on `main` the day this page was written.
>
> So: **use the index path above to install, and build from a checkout for
> anything you are judging the product by.** `backend/` is the Python project
> root — the repository root has no `pyproject.toml` — so it is `python3 -m
> build backend --outdir <somewhere>`, never a bare `python3 -m build` at the
> root, whose `dist/` is the editor bundle rather than a wheel.
> [adoption.md, *Be honest about the install*](adoption.md#be-honest-about-the-install)
> has the editable form. A later pre-release closes this note; nothing else on
> this page depends on which one you have.

> **Somebody already timed this walk.**
> [`decisions/stranger-install-2026-08-29.md`](decisions/stranger-install-2026-08-29.md)
> is the last measured run — `pip install` to a correct answer in about twenty
> seconds of machine time, with the distribution count, the virtualenv size and
> the CLI verdict. Read it for the numbers; this page does not repeat them. Its
> closing verdict on the *library* door is the exception: the defect it rests on
> (`launch-readiness/171`) was fixed the same day, and this page is written
> after that fix.

## 1. Which shape you are in

Two ways to consume this, and the choice changes what you install.

| | **Embed the compiler** | **Run our server** |
| --- | --- | --- |
| What runs | your process, plus a library | a second process |
| Install | `openstategraph[<your provider>]` | `openstategraph[server,<your provider>]` |
| Your endpoint | calls `load_workflow(...).ask(...)` in-process | makes an HTTP call |

**This page covers the embedded shape end to end**, because it is the one where
your existing endpoint stays yours. For the other, run `openstategraph serve`
and read [the HTTP API](api.md) — note that `[server]` is the web layer only
and contains no provider integration, so name one alongside it or nothing will
answer.

[wiring-it-in.md §1](wiring-it-in.md#1-which-of-the-two-shapes-you-are-in) is
the fuller comparison — who owns the loop, who frames the stream, what each
costs. You are not choosing forever: the package on disk is identical, and a
workflow does not know which door a run came through.

## 2. `init` into the directory you already have

`openstategraph init` with no argument treats the current directory as the
project. It is safe on a directory that already has files in it — it writes
only what is not there, and overwrites nothing:

```bash
cd ~/my-service
openstategraph init
```

```
created ./
  openstategraph.yaml     workflows_dir: workflows
  .gitignore              .env, .openstategraph/
  workflows/starter/      the smallest workflow that runs
```

> **On the release TestPyPI serves today, that refuses.** A non-empty
> directory was a hard stop, and the refusal points at `--force`:
>
> ```
> ./ already exists and has 2 files in it. Nothing was written.
>   use it anyway:      openstategraph init . --force
> ```
>
> Take it — `--force` waives that one precondition and, as its own message
> says, "overwrites nothing that is already there". Newer builds warn and
> proceed instead, which is why the block above has no such line. What
> `--force` does **not** waive, in either build, is an existing `workflows/`
> that OpenStateGraph did not create: it refuses, and names both
> `--workflows-dir` and the `mv`, because it would otherwise scan a directory
> somebody else owns. Run `init` before you make any workflow of your own and
> you will not meet that one.

Three things now exist beside your app:

| | |
| --- | --- |
| `openstategraph.yaml` | committed, no secrets, and it is what makes the next section work from anywhere in the tree. Found by walking **up** from wherever a command runs. |
| `workflows/` | the **workflows root** — the directory holding `<slug>/workflow.json`. `workflows_dir:` in the config renames it; `OPENSTATEGRAPH_WORKFLOWS_ROOT` overrides both, because the file is shared and the environment is the machine in front of you. |
| `workflows/starter/` | one **package** — a workflow, its `tests/`, and room for its own `tools/`. `--empty` skips it. |

> **If you already had a `.gitignore`, check it before you make a `.env`.**
> `init` leaves an existing one alone — correctly, it is yours — but the run
> still prints *".gitignore already covers it"*, which in that case it does
> not. Add `.env` and `**/.openstategraph/` yourself
> (`launch-readiness/191`).

Nothing writes a `.env`. `openstategraph env-example` prints the variable
names; the values are yours to put there.

## 3. A first workflow

Two ways, and the second is worth doing once even if you intend to use the
first.

**From a template or a worked example**, which is the fast path:

```bash
openstategraph new my-thing            # scaffold from a template
openstategraph examples copy sql-qa    # or a worked example, shipped in the wheel
```

A template produces a package and stops existing; there is no link back to it
afterwards. `adoption.md` lists which templates and which examples.

**By hand**, which is the path that shows you what a package *is*. This is the
smallest workflow that answers a question with no model call at all — three
nodes, an input, a formatter, an output — and it is the one to start with,
because it proves your wiring before a credential can be the suspect:

```json
{
  "version": 1,
  "name": "Echo",
  "published": true,
  "document": {
    "version": 3,
    "name": "Echo",
    "settings": {},
    "nodes": [
      {"id": "in1",  "type": "input.text",            "data": {}, "position": {"x":  40, "y": 200}},
      {"id": "fmt1", "type": "function.format_report", "data": {"reportTitle": "Echo"}, "position": {"x": 380, "y": 200}},
      {"id": "out1", "type": "output.formatted",       "data": {}, "position": {"x": 720, "y": 200}}
    ],
    "edges": [
      {"source": {"nodeId": "in1",  "portId": "text"},   "target": {"nodeId": "fmt1", "portId": "candidate"}},
      {"source": {"nodeId": "fmt1", "portId": "report"}, "target": {"nodeId": "out1", "portId": "result"}}
    ]
  }
}
```

Save it as `workflows/echo/workflow.json` and run it from the command line
before any of it reaches your app:

```bash
openstategraph validate workflows/echo
openstategraph run workflows/echo "hello"
```

```
VALID

Topology: 3 graph nodes · entry ['in1'] · exits ['out1']

# Echo

### in1
hello
```

`position` is where the node sits on the canvas and nothing else — the compiler
ignores it, and the editor needs it. `published` is a lifecycle flag that gates
who sees the workflow in our chat surface; an embedded `load_workflow` reads
the package whether or not it was ever published.

## 4. Rewiring your endpoint

Here is the endpoint before — the stub every project has a version of:

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, str]:
    return {"reply": f"(stub) you said: {req.message}"}
```

And after. This is the whole integration:

```python
from fastapi import FastAPI
from pydantic import BaseModel

from openstategraph import OpenStateGraphError, Workflows

app = FastAPI()
catalog = Workflows()


class ChatRequest(BaseModel):
    message: str
    thread_id: str = "anonymous"


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, object]:
    try:
        workflow = catalog.load("echo")
        result = workflow.ask(req.message, thread_id=req.thread_id)
    except OpenStateGraphError as exc:
        return {"reply": "", "error": str(exc)}
    if result.failures:
        return {"reply": str(result), "failures": result.failures}
    return {"reply": str(result), "usage": result.usage}
```

```
POST /chat  {"message": "hello"}
200         {"reply": "# Echo\n\n### in1\nhello", "usage": {}}
```

Four details, each of which is the reason this is not three lines:

- **`Workflows()` takes no argument, deliberately.** It resolves the workflows
  root once, at construction, through `openstategraph.yaml` — so it is right
  from a subdirectory, right after a `chdir`, and right under a process manager
  that starts you somewhere you did not choose. A literal
  `Workflows("workflows")` is relative to the working directory and is the
  first thing that breaks in a container. For a single package,
  `load_workflow(path)` is the other spelling; the catalogue is what a service
  with more than one wants, and it lists without compiling.
- **Construct the catalogue at import, load inside the handler.** The
  catalogue is a lookup and is cheap; `load()` compiles — it imports LangGraph,
  builds a model and executes the package's own `tools/*.py`. Hold the compiled
  object in a module-level cache once you have more than a demo.
- **A run that produces nothing arrives two different ways, so gate on both.**
  Newer builds *raise* — `RunProducedNothing`, carrying the whole run on its
  `.result` — where the release TestPyPI serves today *returns* an empty
  `RunResult` with `.failures` set. The commonest first failure of all, an
  unconfigured provider, comes back through whichever of the two your build
  does. Catching `OpenStateGraphError` and then checking `result.failures`
  handles both and needs no version check: it is the base class of every error
  this package raises, `PackageNotFound` and `RunProducedNothing` included, and
  both builds export it. The handler above was run against both.
- **`result` is a `str` subclass.** `str(result)` is the answer;
  `.failures`, `.warnings`, `.decisions` and `.usage` ride along on it.
  [adoption.md, *What `.ask()` gives you back*](adoption.md#what-ask-gives-you-back)
  is the full list and the `.warnings` / `.failures` split.

`thread_id` is the conversation. Pass a stable one per conversation and the
checkpointer carries history across calls; pass a per-user identity as
`user_email` and long-term memory binds to that person.
[wiring-it-in.md §4](wiring-it-in.md#4-identity--one-table-both-shapes) is the
one table of all four identity keys, and §3 there is the same handler
streaming.

## 5. Giving it a model

Everything above ran with no credential because no node drove a model. The
moment one does, a provider has to be both **installed** and **configured**,
and they are separate failures.

**Installed** is the extra you named at install time — one provider per extra,
because `init_chat_model` resolves exactly the one your `model` string names
and installing three to use one was pure cost.
[`backend/pyproject.toml`](../backend/pyproject.toml) is the list, and it
carries the argument for each.

**Configured** is a variable in your environment. Ask, and be told:

```bash
openstategraph providers
```

```
config file: /path/to/your/project/openstategraph.yaml
default:     ollama:gpt-oss:120b-cloud — the only provider integration installed; set
             OLLAMA_API_KEY or OLLAMA_HOST to use it

anthropic    needs its extra anthropic:claude-haiku-4-5
             reads ANTHROPIC_API_KEY; it is not set
             extra 'openstategraph[anthropic]'
...
```

"Configured" means a credential is present, not that the endpoint is reachable.
`openstategraph providers --check` makes one real, billable request per
configured provider and tells you which of those two you have.

Two things worth knowing before you pick:

- **A provider integration you installed becomes your default.** With nothing
  written down, the project inherits whichever extra is present — which is what
  makes `pip install "openstategraph[anthropic]"` mean *Anthropic is my
  default*. Uncomment `default_model:` in `openstategraph.yaml` to state it
  instead; a written statement outranks a credential that happens to be
  exported on somebody's machine.
- **`ollama:` means Ollama *cloud*.** It is reached with `OLLAMA_API_KEY`
  against `https://ollama.com`, not through a daemon on your laptop. Set
  `OLLAMA_HOST` only if you are deliberately running your own — and never judge
  a workflow by a small local model, which turns a wiring bug and a capability
  gap into the same symptom.

> **Testing the endpoint without spending model calls.** `Workflows(model=…)`
> and `load_workflow(…, model=…)` take a model *object*, not only a string, so
> your own test suite can pass a fake one and exercise the whole handler —
> compile, run, answer, error paths — with no network and no credential. The
> model is one of several collaborators you can substitute;
> [adoption.md, *It is an SDK: what you can substitute*](adoption.md#it-is-an-sdk-what-you-can-substitute)
> is the list.

## 6. Durability

Out of the box the conversation memory is in-process, and it says so, on every
run:

```
the default checkpointer asked for durable threads, but langgraph-checkpoint-sqlite
is not installed — falling back to an IN-MEMORY saver, so approvals and
conversations will NOT survive a restart. Install it with: pip install 'openstategraph[sqlite]'
```

That is deliberate noise, not a bug — the alternative is a `thread_id` that
silently forgets across a deploy. One extra ends it:

```bash
pip install "openstategraph[ollama,sqlite]"          # once published
```

The file lands under the workflows root, in `.openstategraph/`, which the
generated `.gitignore` already names.
`OPENSTATEGRAPH_CHECKPOINT_PATH` moves it, and `=memory` opts out loudly rather
than by omission. For a database an operations team already backs up, there is
a `postgres` extra; [deploying](deploying.md) is where that conversation
belongs.

## 7. What "it worked" looks like, and the three ways it does not

Working:

```
$ openstategraph run workflows/echo "hello"
# Echo

### in1
hello
$ echo $?
0
```

`openstategraph run` exits non-zero when a run does not produce an answer, so
it is usable in CI as-is. The exit codes are fixed and enumerated in
[the stability contract](stability.md).

**No credential.** The commonest first failure, and it names the variable:

```
error: Node "agent1" failed and produced no result. Provider "ollama" has no
credential — set OLLAMA_API_KEY or OLLAMA_HOST in .env (see `openstategraph env-example`).
```

Embedded, this is the failure §4's two gates exist for. `.env` is
read from the project; `openstategraph providers` is the faster way to confirm
it before you run anything.

**Wrong directory.** `PackageNotFound: no workflow.json in
/somewhere/workflows/echo — is that a workflow package?` The path in the
message is what `Workflows()` resolved, so read it: if it is not where your
packages are, either the process started outside the tree containing
`openstategraph.yaml`, or something set `OPENSTATEGRAPH_WORKFLOWS_ROOT`. This
is the failure a literal `Workflows("workflows")` produces under a process
manager, and the reason the handler above passes no argument.

**A tool or function that did not load.** A package whose `tools/*.py` will not
import does not refuse to run — it runs without them, lands the reason on
`result.warnings`, and logs a WARNING, because the alternative is a workflow
that answers confidently with nothing behind it. Read `.warnings` in
development; gate on `.failures`.

## Where to go next

| | |
| --- | --- |
| Stream tokens to a browser instead of blocking | [wiring-it-in.md §3](wiring-it-in.md#3-the-same-thing-streamed) — the `.astream_events()` loop, and the four things `ask()` does that it does not |
| Draw the next workflow instead of typing JSON | `openstategraph serve --open`, with the `[server]` extra — the canvas at `/`, over this same workflows root |
| Understand what you are drawing | [On the canvas](on-the-canvas.md) |
| Know what we may take away | [The stability contract](stability.md) |
| Know how far a package travels without us | [Export and portability](export-and-portability.md) |
| Put it in a codebase that *already* has `StateGraph`s in it | [OpenStateGraph in a LangGraph codebase](openstategraph-in-a-langgraph-codebase.md) — the same install, a different reader: composition in both directions, the state boundary, and what stays easier hand-written |
