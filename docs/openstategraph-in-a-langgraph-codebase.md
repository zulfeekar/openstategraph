# OpenStateGraph in a codebase that already uses LangGraph

You already have `StateGraph`s. `langgraph` is already in your lockfile, your
team already argues about reducers, and nobody here needs to be told what a
node is. The question is narrower and harder: **what does this add, what does
it cost, and where exactly are the seams.**

- [Adding it to a project you already have](adding-openstategraph-to-your-project.md)
  is the walk for the other reader — a service with a chat endpoint and no
  graph. Its §0 is the install line, its §5 is providers and credentials, and
  this page does not repeat either: if you have not installed the distribution
  yet, start there and come back.
- [Export and portability](export-and-portability.md) answers *how much of us
  do I have to carry* — the floor is a `pip install`, not zero.
- [On the canvas](on-the-canvas.md) is the lexicon. **Package**, **instance**,
  **mount**, **template**, **slug**, **step budget** and **replay** all mean
  something specific here, and two of them collide with words you already use.

**Everything below was executed** before it was written down, on 2026-08-30, in
a throwaway project outside any checkout with its own virtualenv, against this
repository's `backend/` installed in editable form. Where a claim was read out
of the source rather than run, the line says so. The versions the walk
resolved:

```
langgraph      1.2.11
langchain      1.3.18
langchain-core 1.6.1
```

`backend/pyproject.toml` is what constrains them, and it is the file to read
rather than this fence, which is a measurement with a date on it.

---

## 1. What a compiled workflow actually is

One function, one object:

```python
from openstategraph import load_workflow

workflow = load_workflow("workflows/stock-desk")
workflow.graph
```

`workflow.graph` is not a wrapper, an adapter or a proxy. Printed from the
process that built it:

```
type: langgraph.graph.state.CompiledStateGraph
mro:  langgraph.graph.state.CompiledStateGraph
      langgraph.pregel.main.Pregel
      langgraph.pregel.protocol.PregelProtocol
      langchain_core.runnables.base.Runnable
      abc.ABC
```

It is a `Pregel` and therefore a `Runnable`, which is the whole answer to *can
I drop this into a graph I already have*: anything you can do with a graph you
compiled yourself, you can do with this one, with no code of ours in the call
stack. The compiler calls the real builder API — `StateGraph()`, `.add_node()`,
`.add_edge()`, conditional edges, `Send` — and hands you the result.

**Its state schema is ours, and it is `RunState`**
(`backend/openstategraph/compile/state.py`), and every channel a second node
type can legitimately write carries a named reducer rather than a bare scalar.
The two that matter to a caller are the ends: **`question` goes in, `answer`
comes out.** The rest — `messages`, `decisions`, `outputs`, `routes`,
`attempts`, `feedback`, `subtasks`, `worker_results` and a dozen more — is how
the document's own machinery talks to itself, and §3 is about which of it you
should ever touch. Read the module rather than a list here; the list is the
kind of thing that goes stale in prose and cannot.

**It arrives with a checkpointer already attached**, which is the first thing
that surprises people. A bare invoke with no thread id does not run:

```
ValueError: Checkpointer requires one or more of the following 'configurable'
keys: thread_id, checkpoint_ns, checkpoint_id
```

That is LangGraph's own message, and it is correct — persistence is on by
default here because a `human.approval` pause and a multi-turn conversation
both need it. Pass a thread id, or pass your own saver (§5).

Besides `.graph`, the object carries the things a document knows and a compiled
graph does not:

| | |
| --- | --- |
| `.warnings` | capabilities the document names that this process could not resolve — a bound tool with no implementation, a `function.*` with no callable, a mount whose package is missing. Empty is healthy; anything here means the graph runs and answers **less well than it looks** |
| `.failure_warnings` | the subset of the above that is a claim the run came out less capable, and the only part that may reach an exit code |
| `.document` | the vendor-neutral document that was compiled |
| `.slug`, `.package_dir` | identity, derived from the directory name |
| `.ask(...)` | the one-line door — seeds the initial state correctly, mints a thread, and returns a `str` subclass carrying `.decisions`, `.outputs`, `.usage`, `.failures` |
| `.mermaid()` | the compiled topology as text, no network call, mounts opened |
| `.as_tool()` | the whole workflow as one LangChain tool (§2) |
| `.close()` | releases the sqlite handles this load opened; also a context manager |

[adoption.md](adoption.md) is the full reference for `.ask()` and its result;
this page uses `.graph` deliberately, because you already have somewhere to put
one.

---

## 2. Composition, in both directions

### 2a. Your graph calls a workflow

Three shapes, and they differ in how much of your state the workflow can see.
All three were run.

**As a tool, for an agent you already have.** The zero-restructuring option:

```python
from langchain.agents import create_agent

stock = load_workflow("workflows/stock-desk").as_tool(
    name="stock_desk",
    description="Answers stock questions.",
)
agent = create_agent(model, tools=[stock, ...])
```

What comes back is a `langchain_core.tools.structured.StructuredTool` with a
one-field schema — `question: str` — and calling it runs the workflow:

```
call: SKU-2: 0 in stock
```

The isolation is total and deliberate: the workflow sees the question string
and nothing else, and each call runs on its own thread id, so two calls never
continue each other's conversation. That is the subagent rule, and §3 is where
it is stated properly.

**As a node you write.** The shape to reach for when your state keys are yours
and you would rather they stayed that way:

```python
def call_workflow(state: MyState) -> dict:
    final = workflow.graph.invoke(
        {"question": state["topic"], "attempts": 0, "decisions": {}, "outputs": {}},
        {"configurable": {"thread_id": "…"}},
    )
    return {"summary": final["answer"]}

mine = StateGraph(MyState)
mine.add_node("ask_osg", call_workflow)
```

```
A wrapper node: '# Echo\n\n### in1\nquarterly numbers'
```

The seeded `attempts` / `decisions` / `outputs` are not decoration. A grader
loop reads `None` where it expects a counter if you omit them, and it fails
silently — which is exactly why `.ask()` exists and does this for you. If you
are not doing anything a plain call cannot do, call `.ask()` inside the node
and skip the ceremony.

**As a subgraph, passed straight to `add_node`.** LangGraph accepts a compiled
graph as a node when the parent and child **share state keys**
(`/oss/python/langgraph/use-subgraphs`, confirmed 2026-08-30). Declare the
child's channels on your own state and it works:

```python
class SharedState(TypedDict, total=False):
    question: str
    answer: str
    attempts: int
    decisions: dict
    outputs: dict

direct = StateGraph(SharedState)
direct.add_node("osg", workflow.graph)
```

```
B direct node: '# Echo\n\n### in1\nhello direct'
```

It runs, and the child writes `answer` back into your state. It is also the
option to take last, and the reason is not style: you have just copied five of
our channel names — and their reducer semantics, which a bare `dict`
annotation does not carry — into your schema, where they are now yours to keep
true across our releases. `RunState` is not part of the stability contract that
`workflow.json` is.

| | Your state visible to the workflow | Your schema mentions ours | Thread |
| --- | --- | --- | --- |
| `as_tool()` | nothing but the question | no | a fresh one per call |
| a wrapper node | exactly what you pass | no | yours to choose |
| `add_node(graph)` | the shared keys | yes | the parent's config |

### 2b. A workflow calls code you already have

Three channels, all of them *data in the document, implementation somewhere on
disk*. This is `CLAUDE.md`'s `code → canvas` direction, and each was verified
against a real project rather than read.

**A package `functions/` folder** — the smallest one, and the one that needs no
model at all. A file under `<package>/functions/` contributes
`function.<name>` for every public function it defines, with a deliberately
narrow contract: `fn(text: str) -> str`, a deterministic transform of the
node's upstream text. It gets no access to graph state, because a function
holding raw state would be a second, unserialisable place for control flow to
hide.

```python
# workflows/stock-desk/functions/stock.py
from myapp.inventory import stock_level          # your existing module


def stock_report(text: str) -> str:
    level = stock_level(text.strip())
    return f"{text.strip()}: {level} in stock" if level >= 0 else f"{text.strip()}: unknown SKU"
```

The document names it as a node type, and nothing else changes:

```json
{"id": "f1", "type": "function.stock_report", "data": {}, "position": {"x": 380, "y": 200}}
```

```
warnings: []
'SKU-1: 12 in stock'
'SKU-9: unknown SKU'
```

**A package `tools/` folder** — for something an agent decides to call. A
`BaseTool` subclass with a `name`, a `description`, an `Args` model and an
`_execute`; `node_type` is optional and is what makes it placeable on the
canvas under a stable id.

```python
# workflows/stock-desk/tools/stock.py
class StockTool(BaseTool):
    name = "stock_level"
    node_type = "tool.stock-level"
    side_effecting = False
    description = "How many units of a SKU are in stock."
    Args = StockArgs

    def _execute(self, args: BaseModel) -> ToolResult:
        return ToolResult(content=str(stock_level(args.sku)))
```

Discovery gives it two names — a qualified id from where it lives, and the
`node_type` it claimed:

```
ToolCapability(id='stock-desk/tools.StockTool', name='stock_level', …,
               node_type='tool.stock-level')
```

and a document binding it to an agent validates clean:

```
$ openstategraph validate workflows/stock-agent
VALID
Tool bindings: {'a1': ['t1']}
```

**An installed distribution** — for a capability that belongs to your platform
rather than to one package. A stanza in **your** `pyproject.toml`:

```toml
[project.entry-points."openstategraph.tools"]
acme = "acme_osg_tools:TOOLS"
```

`pip install`ed into the same virtualenv, that is enough. The discovery
reports the type and who supplied it:

```
values:  ['tool.acme-ping']
sources: {'tool.acme-ping': 'acme-osg-tools'}
```

and a document naming `tool.acme-ping` with no `tools/` folder of its own
validates. Flip the switch and the same document tells you what it lost, which
is the point of the switch:

```
$ OPENSTATEGRAPH_DISABLE_PLUGINS=1 openstategraph validate workflows/ping-desk
- No implementation for tool "tool.acme-ping" — the agent ran without it, so
  its answer may not be grounded in that data source.
```

Precedence is **built-in < installed distribution < the package's own
`tools/`**, so an unrelated `pip install` can never outrank a package author's
own tool. `openstategraph.functions` is deliberately **not** an entry-point
group: a `function.<name>` binds by the bare name written in the document, so a
distribution that could inject one would change what a package's node resolves
to with nowhere in the document to see it. [Building an atom](building-an-atom.md)
is the full reference for both folders and the entry-point groups.

> **One thing to know before your `tools/` imports your application.** Both
> examples above import `myapp.inventory` — the code the project already had —
> and that works in-process, because the interpreter that runs your service has
> the project root on `sys.path`. **The CLI does not.** The same package that
> loads clean from a script fails under `openstategraph validate`:
>
> ```
> Tool module stock.py could not be imported (ModuleNotFoundError: No module
> named 'myapp') — every tool it defines is missing from this run.
> ```
>
> The report is honest about the consequence and wrong about the cause: it
> advises copying the `tools/` folder next to `workflow.json`, which is already
> where it is. `PYTHONPATH=. openstategraph validate workflows/…` is the fix,
> and it returns `VALID` with the binding intact. Filed as
> `launch-readiness/195`; until it closes, put `PYTHONPATH` in front of any
> CLI invocation over a package whose code imports your own.

---

## 3. State: what crosses the boundary, and what does not

Your graph has a state schema. A compiled workflow has `RunState`. **They are
two schemas and nothing merges them for you** — the only way a key crosses is
that you put it there, which is the third row of §2a's table and the reason the
other two rows exist.

Inside a workflow, the isolation rules are stricter than most people expect,
and they are structural rather than conventional:

- **A subagent gets a task and returns a result.** It is invoked as a tool; its
  answer comes back as a `ToolMessage`. It never sees the parent's message
  history or graph state. `as_tool()` puts *you* on the parent side of exactly
  that boundary: the workflow sees the question string, and if it needs to know
  something else, that something has to be in the question.
- **A `Send` payload replaces rather than merges.** When an
  `orchestrate.supervisor` fans out, each `orchestrate.worker` instance
  receives exactly `task_id` and `task_instruction` and nothing else — no
  question, no upstream output — unless the orchestrator packed it into the
  subtask. Verified against the installed library and recorded at the call site
  (`compile/workflow_compiler.py`, `_fan_out_router`). This is *stricter* than the
  tool-subagent case, which at least carries the whole task description.
- **A mount is a closure, not a LangGraph subgraph.** A `workflow.subgraph`
  node compiles to a closure over the child's `invoke()` — task in, answer out,
  its own state, its own thread. So `xray=True` on LangGraph's own drawing
  expands nothing here; `CompiledWorkflow.mermaid()` opens mounts because *we*
  recorded what the compiler built, not because the library can see inside a
  function.

The practical consequence for a reader with an existing graph: **do not plan on
sharing state with a drawn workflow.** Pass a question, take an answer, and
keep your channels. If you genuinely need shared channels, take §2a's third
shape, and give every shared key a reducer — LangGraph is explicit that a
subgraph writing a key the parent also declares needs one
(`/oss/python/langgraph/use-graph-api`, confirmed 2026-08-30), and this
codebase has already paid for the version of that lesson where a fan-out
scheduled two writers of a bare scalar in one superstep.

---

## 4. What you gain, and what you give up

The trade is not subtle and it should not be sold as free. **A drawn workflow
is a serialisable document with a compiler between it and the runtime.**
Hand-written LangGraph is Python, and Python does whatever you type.

**What is easier hand-written**, measured against the node vocabulary this
build ships — `compile/port_specs.json` is the generated inventory, and every
claim below was checked against it rather than remembered:

- **A branch that is not a model call.** Every branching node type in the
  format — `route.classifier`, `route.grader`, `orchestrate.supervisor`,
  `orchestrate.worker` — drives a model (`drives_model: true` in
  `compile/port_specs.json`). `if state["status"] == "paid"` is one line of
  Python and is not expressible as a drawn route.
- **A node that reads state.** `function.<name>` is `fn(text) -> str` by
  contract. Anything wanting several channels, or wanting to write one the
  format does not have, is a node you write.
- **`Command(goto=…)`, `Command.PARENT`, dynamic destinations.** The compiler
  owns edge assembly; a node cannot redirect the graph.
- **Your own channels and reducers.** `RunState` is fixed. A workflow cannot
  carry a key you invented.
- **Type checking your own state.** Your `TypedDict` is checked by your type
  checker. A document is checked by `openstategraph validate`, which is a
  different moment and a different tool.

**What you get for that**, and none of it is available for a graph in a `.py`
file:

- **The document is the artifact.** `workflow.json` is vendor-neutral, diffable
  and reviewable by somebody who does not read Python, and it is the thing this
  project makes a version promise about.
- **A capability report before a run costs anything.** `.warnings` and
  `openstategraph validate` name a bound tool with no implementation, a mount
  that will not resolve, a function that will never be called. A hand-written
  graph binds `tools=[]` in silence.
- **Surfaces you did not write.** A canvas, an HTTP API with three SSE streams,
  an MCP server, a CLI with fixed exit codes, `openstategraph eval` over a
  committed dataset — all over the same document. [The HTTP API](api.md) and
  [Evaluation](evaluation.md) are the references.
- **Composition by reference.** A package mounted into another package is one
  definition and many instances; change the definition and every instance
  changes. Copy a graph module and you have two.
- **The diagram is generated from what compiled**, so it cannot drift from what
  runs.

The honest summary: this earns its place where the *arrangement* is the thing
that changes often and the *steps* are ordinary — routing, grading, revision
loops, fan-out, approval gates, several agents over a tool bus. It does not
earn its place around a graph whose interesting part is a piece of Python.
Those coexist in one process: keep the Python graph, and mount the drawn one
as a tool or a node.

---

## 5. LangGraph's own capabilities, from a compiled workflow

We inherit these rather than reimplementing them — that is what *we are a
compiler, not a runtime* means in practice. Each row below was reached from a
compiled workflow and run, except where noted.

**Checkpointing.** Durable by default, into `.openstategraph/` under the
workflows root. You already have a saver, so pass it:

```python
workflow = load_workflow("workflows/stock-desk", checkpointer=my_saver)
```

Two things to know, both measured. Your saver **is** the one being written to
— `my_saver.get_tuple(config)` finds the thread after a run. But
`workflow.graph.checkpointer is my_saver` is `False`: it is wrapped in an
async-capable adapter, because LangGraph's async loop calls `aget_tuple` /
`aput` and the installed sqlite saver raises `NotImplementedError` on those.
Assert on the writes, not on the identity.

**Time travel and state inspection.** Ordinary `Pregel` surface:

```
get_state next: () answer: 'SKU-1: 12 in stock'
history len: 5
```

Note the vocabulary collision, because it is a real one: **replay** in this
product's UI is a *profiler* over a recording and spends nothing.
LangGraph's own replay re-executes nodes and fires the model calls again.

**`interrupt()`.** A `human.approval` node compiles to LangGraph's own
`interrupt()`, so the pause is a checkpointed thread and nothing of ours is
holding it:

```
paused at: ('g1',)
interrupt value: {'message': 'Send this to the customer?', 'candidate': 'SKU-1: 12 in stock'}
```

Resume it the way you resume any interrupt — `graph.invoke(Command(resume=…),
config)` on the same thread id — and the run finishes. `workflow.pause(thread_id)`
is a read-only convenience returning the same payload; reading a pause resumes
nothing.

**Streaming.** `.astream_events()` on `.graph`, which is where token streaming
comes from:

```
astream_events kinds: ['on_chain_end', 'on_chain_start', 'on_chain_stream']
```

(That run had no model in it, so no `on_chat_model_stream` — the event kinds
are the graph's own.) [wiring-it-in.md §3](wiring-it-in.md#3-the-same-thing-streamed)
is the runnable SSE loop and the four things `.ask()` does that a raw stream
does not; it is not repeated here.

**`Send` fan-out.** `orchestrate.supervisor` compiles to a conditional edge
returning a list of `Send`s, one per subtask, dispatched by archetype. **Read
from the source, not executed here** — driving it needs a real model, and
`CLAUDE.md`'s standing rule forbids judging one against a small local model.
[Patterns](patterns.md) is where the arrangement is explained.

**The step budget.** `recursion_limit`, a standalone `config` key, counting
**supersteps** — with fan-out, one lap of a revision loop costs several. Ours
is `50`, and a compiled workflow will tell you the number it will use,
including what its mounts add:

```
composition_step_budget: 50
```

Never label it "max iterations" anywhere a user reads.

---

## 6. Reporting a defect or a gap

If you — or a coding assistant working on your behalf — find something wrong
here, this is the shape that can be acted on. It is derived from the tickets
this project actually resolves, not invented for the occasion.

**The shape.** A ticket here is one file with a header line and four parts:

- **A title that states the defect, not the area.** *"`init` says '.gitignore
  already covers it', and in an existing project it does not"* — not *".gitignore
  handling"*. If the title cannot be falsified, it is a topic and not a report.
- **Reproduce.** The commands, in order, from a state somebody else can reach,
  with the real output pasted rather than described. A reproduction that starts
  *"in our environment"* is not one.
- **The defect.** What happened, beside what was expected. Both values, not one
  of them plus an adjective.
- **Why it matters.** The consequence, concretely. The `.gitignore` ticket
  above is a one-line copy fix that is filed as a defect because the sentence
  tells a reader it is safe to put an API key in a tracked file.
- **Done when.** Something checkable. *"a case where `.gitignore` exists
  without `.env` in it must not produce the string 'already covers it'"* — a
  sentence that can be turned into a test by somebody who was not there.

Include the **version** (`openstategraph --version`, or the commit if you are
on a checkout) and, if a capability is involved, whether the report is
in-process or through the CLI — §2b is one example of those two answering
differently.

**If your headline is a number, say how it was measured.** This project learned
that one the expensive way and the same day this page was written: two reports
of a wrong money figure in `chinook-assistant` circulated with the figure and
no denominator, and the first diagnosis of the cause was wrong. The ticket that
finally landed it (`every-workflow-green/45`) says *forty-two times more money
than exists in it* and then says where both numbers came from — the run record
and the shipped database's own total. A number without its measurement is a
claim nobody can check, which means nobody can disagree with it either.

**Where to send it — and the honest answer is that there is no public channel
today.** Checked on 2026-08-30, anonymously:

| | |
| --- | --- |
| The repository the distribution advertises as its Homepage, Repository, Changelog and Documentation | **404 for anyone who is not a collaborator.** It is a private repository |
| `SECURITY.md`'s two routes — GitHub private vulnerability reporting, and the maintainer's address on the commits | both need access to that repository |
| PyPI | the project page exists; the distribution does not |

So *"open an issue"* would be pointing you at a door you cannot reach, and this
page will not print it. What to do instead, in order:

1. **Write the report anyway, in the shape above**, as a Markdown file. It is
   the artifact that gets acted on regardless of how it arrives, and writing it
   is what forces the reproduction and the two values.
2. **Send it to whoever gave you the distribution.** For a pre-release with no
   public index, that person exists — it is how you got it.
3. **If it is a security issue, do not put it in a group chat or a public
   forum.** `SECURITY.md` explains why an issue is public from the moment it is
   filed; the same is true of anywhere else convenient. Send it privately to
   the same person, with the version and the reproduction.

When the repository is public this section gets one line and a link.
[Releasing](releasing.md) is where that state is tracked.

---

## Where to go next

| | |
| --- | --- |
| The install line, and a first workflow from nothing | [Adding it to a project you already have](adding-openstategraph-to-your-project.md) |
| The streaming loop, and the identity keys | [Wiring a workflow into your app](wiring-it-in.md) |
| What a `tools/`, `functions/` or plugin module has to look like | [Building an atom](building-an-atom.md) |
| Which arrangement to draw | [Patterns](patterns.md) |
| What we may take away from you | [The stability contract](stability.md) |
