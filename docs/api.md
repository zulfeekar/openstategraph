# The HTTP API — build your own UI

Both shipped surfaces — the canvas editor and `/chat` — are ordinary clients of
the endpoints in [`openapi.json`](openapi.json). There is no private API behind
them: every path either surface calls is in that document, so a third client is
a supported thing to build rather than a reverse-engineering exercise.

**This page is not the path list.** `openapi.json` is, and it carries roughly
three times as many paths as this page walks through — the editor's own writing,
knowledge, provider, MCP-registry, template and example endpoints among them.
What follows is the subset a **custom chat client** needs, in the order it
needs them.

This page is the whole contract in two halves:

| Half | Where | Why there |
| --- | --- | --- |
| Requests, responses, status codes | [`openapi.json`](openapi.json), generated and committed | Machine-readable. Generate a client from it. |
| **The three event streams** | this page, in prose | OpenAPI cannot express them, and they are the part a custom client gets wrong. |

> The API is **Tier 3** on [the stability contract](stability.md) — a surface we
> operate, not a library you build on, and it may change in a patch release.
> That is a statement about *promises*, not about access: it is the same API our
> own two UIs use, and a change to it shows up as a diff in `docs/openapi.json`.
> The Tier 1 promise for embedding a workflow in your own program is
> [`load_workflow`](adoption.md), not HTTP.

---

## 1. The machine-readable half

The document is generated from the running app and **committed**, so an
endpoint changing shape appears in a pull-request diff next to the code that
changed it:

- `docs/openapi.json` — the committed snapshot.
- `/openapi.json` — the same document, served live by any running server.
- `/docs` — Swagger UI, if you would rather click.

Regenerate it after touching an endpoint:

```bash
python3 scripts/generate_openapi.py
```

Two gates keep it from rotting: `backend/tests/test_openapi_contract.py`
compares the committed bytes to a freshly generated document on every test
run, and the `generated-openapi` CI job regenerates and diffs the working
tree. The same suite also fails if an endpoint has no description, or if a
JSON response has no named schema — a contract whose responses are `{}` is a
shrug in JSON.

### What it structurally cannot cover

`POST /api/runs/stream`, `POST /api/runs/resume` and `GET /api/events` are
Server-Sent Event streams. OpenAPI 3.1 can say a response is
`text/event-stream` and stops there: it has no vocabulary for a *sequence* of
frames, for the union of `event:` names that sequence may contain, or for the
guarantee that exactly one of three names is the last frame. Declaring a JSON
body for them would be worse than silence — it would generate a client that
calls `.json()` on an infinite stream and hangs. So the document declares the
media type and points here.

---

## 2. The event streams

### Framing

Every frame is two lines and a blank line:

```
event: <name>
data: <one line of JSON>

```

`data` is always exactly one line — node output containing newlines is escaped
by `json.dumps`, never spread across `data:` lines. Split the byte stream on
`\n\n` and you have frames.

`EventSource` is **not** usable for the run streams: they are `POST` (the
request body carries the workflow document), and `EventSource` only issues
`GET`. Use `fetch` and read `response.body`, as the example below does.
`GET /api/events` *is* an `EventSource`, and should be one — it reconnects by
itself.

### `POST /api/runs/stream` and `POST /api/runs/resume`

Ten event names, and `started` is always the first. A resumed run is not a
different kind of thing from a client's point of view — it is the same stream
picking back up — so both endpoints emit the identical vocabulary and one
parser handles both.

| Event | Meaning | Payload |
| --- | --- | --- |
| `started` | **first** — the run has begun | `threadId`, plus `seq` (always `0`) and `elapsedMs` |
| `update` | a graph step reported | `node`, `namespace`, `taskId`, `internal`, `activeNode`, `interruptible`, `path`, `pathSlugs`, `output`, and `check` with `reason` **only when a grader rejected the candidate without invoking a model**, plus `seq` and `elapsedMs` |
| `token` | a chunk of model (or node) text | `node`, `namespace`, `content`, `block` (`text`/`reasoning`), `usage` (`{inputTokens, outputTokens, totalTokens}` or `null`), `activeNode`, `interruptible`, `path`, `pathSlugs`, `kind` (`ai`/`tool`), `tool` (`{name, callId}`), and `withheld: true` **only when the text was machinery, not the reply**, plus `seq` and `elapsedMs` |
| `progress` | a step said something about itself *while working* | `node`, `namespace`, `message`, `detail` (developer only, else `null`), `current`, `total` (both `int` or `null`), `activeNode`, `interruptible`, `path`, `pathSlugs`, plus `seq` and `elapsedMs` |
| `spawn` | the run created a child worker or subagent | `spawnId`, `kind` (`fanout`/`subagent`/`async`/`subgraph`), `parent`, `label`, `instruction`, `taskId`, `namespace`, plus `seq` and `elapsedMs` |
| `invoked` | a node asked an ordinary tool to do something | `node`, `namespace`, `name`, `callId`, `activeNode`, `path`, `pathSlugs`, and `withheld: true` **only when the tool's identity was withheld**, plus `seq` and `elapsedMs` |
| `settled` | a child the run announced has ended | `spawnId`, `outcome` (`ok`/`error`/`detached`/`unknown`), and `kind`, `parent`, `label`, `taskId`, `namespace` echoed from the `spawn` it closes, plus `seq` and `elapsedMs` |
| `interrupt` | **terminal** — a `human.approval` node paused the run | `threadId`, `node`, `message`, `candidate`, and `verdict` (`pass`/`revise`) with `reason` **only when a grader produced the candidate**, plus `check` when that verdict cost no model call, plus `usage`, `seq` and `elapsedMs` |
| `done` | **terminal** — the run finished | `threadId`, `answer`, `decisions`, `routes`, `outputs`, `nested`, `attempts`, `mermaid`, `publishedRejected`, and `developer` **only for a developer run**, plus `usage`, `seq` and `elapsedMs` |
| `error` | **terminal** — the run failed | `threadId`, `detail`, plus `usage`, `seq` and `elapsedMs` |

#### Every frame says when it happened — `seq` and `elapsedMs`

Two fields on all ten, minted by the server as it builds the frame.

`seq` counts from `0` and is dense, so recorded order is recoverable without
trusting a clock, and a gap is a dropped frame rather than a quiet run.

`elapsedMs` is an integer count of **milliseconds since this run's stream
opened**, taken from a monotonic clock. Three things it deliberately is not:

- **Not the time you received it.** It measures the server producing the
  frame. A client that wants to show what the *user* experienced — a stalled
  network included — must measure arrival itself; the two answer different
  questions and neither substitutes for the other.
- **Not a wall clock.** A run crossing a clock correction would otherwise
  appear to run backwards. The wall time a run belongs to is the run record's
  own ISO stamp, which agrees with the checkpoints; nothing here restates it.
- **Not absolute.** An offset is smaller, is what a scrubber needs, and says
  nothing about *when* the run happened — a recorded stream can be replayed
  without disclosing that.

Both fields are identical for a customer and a developer: a cadence is not a
disclosure.

#### The run opens with `started`, and that is where `threadId` comes from

`started` is the first frame of every stream, always `seq: 0`, and it carries
one thing: the id of the thread this run is happening in.

Take it there rather than waiting for the ending. The three terminal frames
name the thread too, but a client that only reads it from them learns the id at
the same moment it learns there is nothing left to watch — and a client whose
connection drops mid-run never learns it at all, so it cannot reconnect, cannot
`POST /api/runs/resume` into the same conversation, and cannot look the run up
in `GET /api/threads`. The server invents a `thread_id` for a request that
omits one, so the server owes it back at the start.

It carries no separate run id. This runtime identifies a **turn**, not a run,
and a second identifier beside `threadId` would be a second name for one thing.

It is also the origin `elapsedMs` counts from. Before it existed, the offset
every other frame carried was measured from an event no client could observe.

#### `invoked` — a tool was asked for, before its answer comes back

A `token` frame with `kind: "tool"` is a tool's **result**. `invoked` is the
question that produced it, and it arrives when the call is made rather than
when it returns.

That gap is the whole point. Measured on a workflow whose tool takes eight
seconds: the six longest silences of a 91-second run were all the same shape —
a `progress` line, eight seconds of nothing, then a burst of result text.
Nothing on the wire distinguished that from a model still thinking, a network
that had stalled, or a run that had hung.

`callId` is the join. The `token` frame carrying that tool's result repeats it
in `tool.callId`, so a client can pair the two and time the call; there is no
separate closing frame because that one already exists.

Two things it deliberately never carries:

- **The tool's arguments**, in any form. An argument is routinely an internal
  id, a path this platform invented, or a credential.
- **Anything for the four spawning tools.** A `task` or `start_async_task` call
  is announced as a `spawn`, not here — one tool call never appears twice under
  two different words.

**A customer's copy is blanked, not withheld.** `name` and `callId` read `""`
and `withheld: true` rides the frame, exactly as a tool's identity is already
blanked on a customer's `token` frames. A frame that simply did not exist for a
customer would make "this audience does not get it" and "no tool ran" the same
wire shape.

#### `usage` — what the run cost, on every terminal frame

`done`, `interrupt` and `error` all carry `usage`. It is the **whole run's**
cost, not one message's — a separate question from the `usage` on a `token`
frame, which is why it is a separate shape: a list with one row per model.

```json
"usage": [
  { "model": "gpt-oss:120b-cloud", "inputTokens": 1436, "outputTokens": 86, "totalTokens": 1522 }
]
```

A list rather than one number because a run can use more than one model — a
grader on one provider and an agent on another have two prices, and a single
total hides that. The numbers are the providers' own, metered across the whole
turn, so they include model calls whose chunks produced no `token` frame at
all; a client must not compute this by summing the frames it happened to see.

`error` carries it too, and that is the half most easily skipped: the tokens a
failed run burned are the ones a reader most wants counted.

**Developer only.** A customer's terminal frame reads `usage: null`, exactly as
`usage` is `null` on a customer's `token` frames and as `tokens` is `null` on a
customer's stored run. `[]` is a different answer and a real one — the run
called no model.

#### `spawn.parent` is a hint, not an address

A `spawn` frame's `parent` is the graph step the launch was read off, and that
is **not always a canvas node**. Measured on 2026-08-28: an orchestrator's
`Send` fan-out announces `parent: "lead1"`, which is a card; a deep agent's
`task` or `start_async_task` call is read off the agent's own inner model step,
so the same field says `parent: "model"`, which is not.

The evidence that survives is `namespace`. Its head is `<node id>:<checkpoint
id>`, so the part before the `:` names the node the child was launched from —
the same resolution the server itself does for a `subgraph` spawn. A client
that shows spawned work beside its owner should take `parent` when it names a
node it knows and fall back to the namespace head otherwise; the editor's
`spawnOwner` is that rule.

`taskId` is the child's own identity and joins the frames it produced: a
`fanout` child's `update` frames carry the same id the spawn announced. A
`subagent` and an `async` child produce **no** `update` or `token` frames of
their own — the first reports back as one `ToolMessage`, and the second runs on
a desk outside the run — so an empty account of their *steps* is correct rather
than a gap. Both are still opened and closed; see below.

#### Every spawn is closed — `settled`, and `spawnId` is the join

A bar needs two ends. Every `spawn` frame carries a `spawnId`, unique within
the run, and exactly one `settled` frame carries it back.

**Join on `spawnId`, never on `label` and never on `taskId`.** A fan-out
routinely dispatches three children under one label — measured on a real
supervisor run, three workers all called `impact-analyst` — so a label
identifies a *kind* of child, not a child. `taskId` is the child's own domain
id and is genuinely distinct where it exists, but a `subgraph` spawn has none
(`taskId: null`), so it is the join for three of the four kinds and for the
fourth not at all. `spawnId` is on both halves of every pair.

`outcome` is one of four, and the last two are the honest ones:

| `outcome` | What ended the child |
| --- | --- |
| `ok` | the completion was observed on this stream |
| `error` | observed, and **no worker ran** — the tool rail failed, or a delegation named a subagent that was never declared. A worker reporting bad news reported it successfully, and that is `ok` |
| `detached` | an `async` child, still running outside this run when the stream ended |
| `unknown` | the stream ended with no account of this child |

**One frame with an outcome, rather than two frame kinds.** The `error` frame
in the table above is terminal for the *whole run*; a child failing is not that,
and a second kind that ends one child while the run continues would make the
terminal-frame guarantee a rule with an exception in it.

**A `settled` frame carries no result**, deliberately. What a child produced
already reaches you on the frame that revealed the completion — a `fanout`
worker's own `update.output`, a delegation's `token` frames. A copy here would
be a second spelling of one fact and the only one of the two that could drift
out of step with the audience boundary. So a customer and a developer receive
the identical `settled` frame: *that* a child finished is not a disclosure, any
more than its cadence is.

**What ends each kind, and the one that nothing ends:**

| `kind` | Closed by | `outcome` you will see |
| --- | --- | --- |
| `fanout` | its `taskId` appearing in the dispatcher's results | `ok` |
| `subagent` | the delegation answer bearing its call id | `ok` or `error` |
| `subgraph` | the mounted node reporting as an ordinary step of the parent canvas | `ok` |
| `async` | **nothing** — the parent never waits for it | `detached` |

`async` is the honest gap and it is stated rather than papered over. A
background task is handed an id and left running on a desk outside the run, so
this stream has no moment to report; the `settled` frame it gets when the
stream ends says `detached`, which is a fact about *this run* and not a claim
about the child. Ask the desk for the child's own ending.

**One `subgraph` spawn, one `settled`, even across a revision loop.** A mounted
node is announced once per run however many checkpoints it is given — a
`Send`-dispatched worker gets a fresh one per instance — and it is closed once,
on the first top-level frame the node reports. A grader sending the run back
around does not re-announce it and does not re-close it.

**And an open bar with no `settled` at all is a statement about the
recording.** A stream that dies with the connection cannot emit anything more
(see the terminal-frame guarantee below), so a body that simply stops carries
no closes for whatever was still running. Read that as *the recording ended*,
never as *the child is still working* — the same way a body with no terminal
frame already means a dropped connection rather than a silent success.

#### Audience: what a customer's run cannot carry

**Changed.** `done` used to carry `warnings` unconditionally, and every
client got them. It no longer does, and the reason is a boundary rather than
a tidy-up.

A run declares who it is for:

```json
{ "workflow": {}, "question": "…", "audience": "customer" }
```

`audience` is `"customer"` (the default — omit it and you have it) or
`"developer"`. Only a developer run gets a `developer` object on the `done`
frame, and that object is where everything an editor may see now lives:

| Field | What |
| --- | --- |
| `developer.warnings` | authoring diagnostics — unbound tool types, unresolved functions and subgraphs, mount overrides, capability-discovery failures |
| `developer.suggestion` | the one capability-gap suggestion an agent may offer when it is blocked for want of a tool, as an object (`nodeType`, `attachTo`, `port`, `label`, `reason`) |
| `developer.statements` | **what the run actually executed** — one row per statement, as `{node, tool, statement, result, truncated}` |

The key is **absent**, not empty, on a customer run — so a client cannot read
"there were no findings" out of a frame that was never entitled to carry any.

### `developer.statements` — asking a finished run what it ran

A run used to leave one account of what it executed: **the model's own prose
about what it executed.** That is the account which cannot be trusted on
exactly the runs that need auditing, and two correctness diagnoses paid for it
in one day, reconstructing SQL from an answer and re-deriving it by hand
against the warehouse.

Each row is one statement a tool was actually handed and answered:

```json
{
  "node": "agent1",
  "tool": "mcp_execute_sql",
  "statement": "SELECT port, SUM(barrels) FROM cargoflow_latest GROUP BY port",
  "result": "{\"row_count\": 68, \"rows\": [...]}",
  "truncated": true
}
```

- **`statement`, not `sql`.** The question is *what did this tool actually do*,
  and a SQL-only field would be the wrong shape the first time a tool does
  something else. What stays narrow is what may enter a row: only a call
  argument a recogniser accepted as a statement — today a SQL statement,
  matched by shape and never by tool name, so a tool called `warehouse` reads
  exactly as well as one called `mcp_execute_sql`.
- **`truncated` says whether `result` is whole.** The recorded result is capped;
  the statement never is. A cut payload and a short one would otherwise read
  identically, and a `result` that ends mid-string is evidence to read, not
  something to parse.
- **No credential can appear.** A row carries the one argument recognised as a
  statement and never the tool's argument map, so a `connection_string`,
  `headers` or `token` argument is not recorded at all. On top of that, a
  DSN password, an ODBC `PWD=`, a bearer token or a key-shaped literal found
  *inside* a statement or its result is replaced with `[redacted]` — visibly,
  so nothing is removed silently.
- **Developer only.** It quotes node ids, tool names, table names and literal
  values out of the data. The customer gets the answer.

The same rows come back from `POST /api/runs` on `developer.statements`, and
from the Python door as `RunResult.statements` — which has no audience, since a
caller holding the process holds the run.

### `answer` when a run finished at more than one Output

A document may legitimately have several exits, and a `route.classifier` set to
*Run every match* is the ordinary way to get one: a desk per branch, an Output
per desk, both desks running in the same superstep. **Every exit that finished
is in `answer`**, joined with a newline in the order the document draws them —
which is the same text the workflow produces when both desks are wired into a
*single* Output instead, because that has always been one node's several
producers joined the same way.

Until `launch-readiness/174` it was not: `answer` kept whichever exit the
scheduler settled last, `warnings` was empty, and the other exit's finished
answer sat in `outputs` with nothing pointing at it — so a run that answered
half a two-part question and a run that answered all of it were the same
response. Worse, the two doors disagreed: the same run published the cost desk
on `/api/runs/stream` and the risk desk on `/api/runs`.

A run with several exits carries one **developer-channel** warning naming them,
in the author's own titles. It is a report about how the answer was reached,
never a failure — it does not reach `failures` and does not move
`openstategraph run`'s exit code. Nothing is withheld from the customer
channel, which is why the warning stays on the developer one:
`published_rejected` is on both audiences because a customer handed a rejected
answer has a fact they could not otherwise learn, and a customer handed both
halves has lost nothing.

A single-exit document — every shipped example — is untouched, byte for byte.

Two things follow that a client should not try to work around:

- **`answer` never contains a suggestion fence, for any audience.** The
  runtime splits it out before the frame is built, so the suggestion is
  either an object on the developer channel or nowhere. The same applies to
  every `token` frame and to `update.output`. This is also why a model cannot
  smuggle developer guidance out by writing something fence-shaped into its
  own prose: the channel is the boundary, not the text.
- **A deployment can cap the audience.** `OPENSTATEGRAPH_AUDIENCE=customer`
  in the environment makes every run a customer run whatever the request
  says — the setting for a process that serves only the chat surface. Unset
  (the default) leaves the request in charge. Note what this is not: there is
  no per-user authorization here, for the same reason `docs/deploying.md`
  gives about the shared token — it answers "is this stranger allowed in",
  never "who is this".
- **On the MCP run door the same variable does not cap the audience, it
  *is* the audience** (`the-boundary-nobody-checked/08`). `run_workflow` has no
  request to cap: the client filling in its arguments is a model, so the tool
  takes no `audience` field and never will. It reads
  `OPENSTATEGRAPH_AUDIENCE` directly, and **unset means `customer`** rather
  than "the caller decides" — for a door whose caller cannot name an audience,
  the absence of a permission is not a permission. An MCP deployment that is an
  authoring workbench sets `OPENSTATEGRAPH_AUDIENCE=developer`. See
  [The MCP layer](mcp.md) §7.

`mermaid` deliberately stays on both audiences: it is the compiled topology
that a chat page draws its live flow diagram from, and
`GET /api/workflows/{slug}/graph` serves byte-identical text for the same
workflow and audience — one workflow has one shape, whichever door you came
through. On the customer channel it is drawn in the customer's own vocabulary:
no `__start__`, no `__default_error_handler__`, each node under the name its
author gave it, and every mount opened to any depth with the child's own
document supplying the names inside it (`workflow-gallery` 62). `decisions`,
`outputs` and `attempts` stay too — they are facts about the customer's own
turn.

#### `decisions` vs `routes` — which field to believe about a parallel router

**`decisions[router]` is the branch the graph dispatched on. `routes[router]`
is every branch that ran.** A router in `matchMode: "all"` opens a desk per
match in the same superstep, and `decisions` can hold only one label — so a
router that matched one branch and a router that matched three published the
identical row, while both desks' answers sat in `outputs` (`launch-readiness`
175). If you are asking *what did this run do*, read `routes`.

`routes` carries a row for **every** router that ran, whether it matched one
branch or four, so an absent row means *no router* and never *one branch*. The
label the graph dispatched on is always one of the labels in the row: both are
derived together, from the same finished run, by one function. `decisions` is
unchanged and stays a single label on purpose — the compiler's conditional edge
dispatches on that exact key, and a list there would change control flow.

Both are on both audiences: they are facts about the customer's own turn, in
the same voice, and neither is a developer's guidance.

`publishedRejected` stays on both audiences for the same reason
(`launch-readiness` 25): `attempts` alone proves a grader's loop exhausted
itself, but not whether the last candidate passed or was force-published
after rejection, and a customer received the second case indistinguishable
from the first. The grader's *reason* can quote internals and stays inside
`developer.warnings`; that the event happened is a fact, not guidance, and is
`true`/`false` on every run regardless of audience.

#### `outputs`, `decisions` and `nested` — which document a node belongs to

`decisions` and `outputs` hold **the outermost document's own nodes**, keyed by
bare node id.

They used to hold every document the run touched, and a node id is unique only
*within* a document: `concierge` and `chinook-assistant` ship sharing `in1`,
`router1` and `out1`, so the mounted child's values landed on the parent's keys
and the parent's own facts vanished. Captured on a real run,
`"decisions": {"router1": "b-data"}` was the **child's** branch — the parent had
chosen `b-music`, and the frame had no way to say both.

Everything below the top level is in `nested`, keyed by **mount path**:

```json
{
  "decisions": { "router1": "b-music" },
  "outputs":   { "in1": "Which five artists…" },
  "nested": {
    "decisions": { "wf-music/router1": "b-data" },
    "outputs":   { "wf-music/agent-sql": "…", "wf-music/wf-inner/deep": "…" }
  }
}
```

The key is the chain of mount node ids plus the node's own id — the same
vocabulary as a frame's `path` and as `?w=concierge/wf-music` in the editor's
address bar. So two mounts of one package stay apart: `wf-music/agent-sql` and
`wf-other/agent-sql` are different keys where the slug was the same.

`nested` is always present, and empty for a run with no mounts, so a client can
read it without a special case. The change is additive: a client that reads
only the flat pair sees exactly what it saw before, minus the collisions.

`POST /api/runs` (the blocking call) is unaffected and has no `nested`. Its
`outputs` come from the graph's final **state**, and a mounted child is invoked
with its own empty `outputs` and returns only its answer — so that map never
held anyone else's nodes in the first place.

#### The terminal-frame guarantee

> **Every stream ends with a frame that says how it ended.** Exactly one of
> `done`, `interrupt` or `error` is the last frame of every stream that lives
> long enough to send one. `update`, `token`, `progress`, `spawn` and
> `settled` are progress: after any of them, keep waiting.

A client must never tell "still working", "finished" and "died" apart by
waiting and guessing. There is exactly one exception, and it is honest rather
than an oversight: **if the client disconnects or the server dies, no terminal
frame is possible** — there is no socket left to write to. So a body that ends
without one of the three means *the connection dropped*, and an aborted
`fetch` means *you stopped it*. Never a silent success, and never a spinner
that runs forever.

#### When the step budget runs out

A run that laps a cycle until its **step budget** is spent ends as an `error`
frame on the stream, and as a `502` from `POST /api/runs`. Handle it like any
other failure — there is nothing a client can retry that would go differently
— but the sentence is worth showing, because it is the one failure whose cause
is the *drawing* rather than the model or the network:

```
The workflow "review-board" spent its whole step budget of 50 supersteps
without reaching an answer. A step budget counts supersteps, not laps round a
loop: every node on a cycle costs a superstep per lap, and a lap that fans out
costs one for each branch that runs — so a supervisor with three workers and a
grader spends five supersteps a lap, not one. A loop that never settles needs
a grader that can pass it, or an exit its own state can reach, rather than a
bigger number here.
```

`recursion_limit` on the request sets that budget (see `openapi.json` for its
range); the workflow's own `settings.recursionLimit` sets it when the request
does not. A **customer**-audience stream gets the generic failure sentence
instead, like every other error — the wording above names how the workflow is
built, which is a developer's business.

There is no LangGraph vocabulary in any of it, on purpose. The runtime's own
exception advises raising the limit and links its own troubleshooting page;
that advice is usually wrong here — a loop that cannot settle will not settle
with more supersteps — so it is translated at the two places a graph is
driven rather than repeated at four surfaces.

#### `interruptible` — what Stop would actually do

`true` if closing the connection **cancels** the node this frame names;
`false` if it can only walk away from it, leaving the step to finish in the
background with its result discarded. It is a property of the node, not of the
run: in one workflow an agent can be cancellable while the grader after it is
not.

It exists because those two outcomes are otherwise indistinguishable from
outside. The stop itself is instant either way — the connection closes and no
further step is scheduled — so a client that only watches the clock cannot
tell a run that stopped from a run that is still being paid for. Measured on
2026-08-27 against a three-worker fan-out disconnected 12 s in: a cancellable
step ended 0.41–1.08 s after the stop, an uncancellable one 12.65–24.16 s.

Read the last value you saw and use it to word what you tell the person who
pressed Stop. A cancelled step still finishes the provider call it had already
issued, so the honest claim is *"the step was cancelled"*, never *"nothing is
running"*.

An older backend omits the field. Treat a missing value as `false` — that is
the claim every run could always make.

#### `internal` and `activeNode`

`update` frames include steps that are not nodes on the canvas — an agent's
own `model` and `tools` steps inside its compiled loop. Those are tagged
`internal: true` rather than dropped, so a flat activity feed can ignore them
while a trace view nests them under their owner.

`activeNode` is the canvas node a client should show as *running* for this
frame, resolved server-side from the checkpoint namespace. Use it. Both of our
surfaces used to guess ("the last frame that was not internal") and both
guessed wrong the same way: while a mounted team ran, every frame was
internal, so the highlight stayed on the router and the UI claimed the router
was working while a team was.

**`token` frames carry it too, and they are the ones that arrive on time.** An
`update` frame is emitted when a node *completes*, so a highlight fed by
update frames alone can only ever show who last finished. A token frame is the
only frame that arrives while a node is still working. Measured on a real run:
a mounted workflow streamed 100+ token frames over about twenty seconds while
the most recent `update` — and therefore the highlight — still named the
router. Drive your highlight from `activeNode` on **both** frame types.

The field is repeated on every frame rather than sent only when it changes,
because a field whose meaning depends on its presence is two fields. **Compare
it against the node you last highlighted and do nothing when it is unchanged**
— one model turn is a hundred frames that all name the same node.

An older backend omits `activeNode` on `token` frames. Treat a missing value
as "this frame says nothing about where the run is" and leave the highlight
where it was; do **not** fall back to the frame's own `node`, which for a
token is usually an inner step (`model`, `tools`, or a node belonging to a
mounted document) that exists on no canvas.

#### `path` — where the frame is on *every* canvas

`activeNode` answers "where is the run" for **the document you submitted**, and
for most clients that is the whole question. It is not enough if your client
can display a *mounted* document while it runs, because that document contains
neither of the two ids a frame used to offer:

- `activeNode` is the mount's card, which belongs to the **parent**;
- `node` is the runtime's own name for the step — literally `model` or `tools`
  inside an agent's loop, and inside a mounted document the compiler's
  `safe_name`, which replaces every non-alphanumeric character with `_`. A
  child node saved as `agent-sql` therefore arrives as `agent_sql`, matching
  nothing on any canvas.

So `update` and `token` frames also carry **`path`**: an array of canvas node
ids running from the outermost document inward, one entry per level of nesting.

```
"node": "tools", "activeNode": "wf-music", "path": ["wf-music", "agent-sql"]
```

Walk it **outermost-first** and take the first id the document *you* have open
contains. Every entry shallower than your document belongs to something that
mounts you and cannot be one of your cards, so the first hit is your level. The
ordering is load-bearing rather than incidental: documents share ids freely —
the shipped `concierge` and `chinook-assistant` both have `in1`, `router1` and
`out1` — so walking inward-first would light the *parent's* input node while
the child's input step ran.

`path` is empty when nothing on the frame resolves to a card, and absent on
terminal frames and on any backend that predates it; fall back to `activeNode`
in that case. When both are non-empty, `activeNode` equals `path[0]`.

#### Tokens come from every text-producing node

`token` frames are not only the agent's. The input node echoes the question and
the output node re-renders the final answer, each as its own `token` frame.
Key on `data.node` if you want one node's stream.

**But on a customer run — the default — most of them arrive empty.** The
audience boundary above applies frame by frame: a customer's token stream
carries the reply and nothing that produced it, so the input node's echo of
their own question, a tool payload, a branch name and a grader's verdict all
come through with `content: ""` and `withheld: true` (and `tool` blanked). The
frame is **emptied, not dropped**, deliberately — it is the only frame that
arrives while a node is still working, so it is what keeps a live diagram
honest about where the run is. A developer run gets the text and no `withheld`
key at all.

#### `block` and `usage` — thinking is not the answer, and a turn has a cost

A reasoning model streams its deliberation and its reply in the same content
list. Until now both arrived as the same frame, so a client had two bad
choices: concatenate them and show a model's private thinking as if it were
the answer, or drop the thinking and lose it — while **reasoning effort has
been a per-node field all along**, i.e. you could ask for reasoning and then
never see any of it.

`block` says which one a frame carries:

| `block` | What |
| --- | --- |
| `text` | the reply — the overwhelming majority, and the only kind ever emitted before this field existed |
| `reasoning` | the model thinking out loud |

One chunk can produce **two frames**, reasoning first, because that is the
order it was produced in. `block` is not `kind`: `kind` says *who* produced
the text (`ai` or `tool`), `block` says *what kind of text it is*, so a tool
result is `kind: "tool"` with `block: "text"`.

**Reasoning frames reach a developer run only.** A customer never sees them at
all — not emptied, absent — so a customer's token stream is exactly what it
always was. This is the same rule that keeps a branch name and a grader's
verdict out of an answer: deliberation is what produced the reply, not the
reply.

`usage` carries what the message cost, on the frame that **settles** it:

```
event: token
data: {"node":"agent-sql","content":"","block":"text",
       "usage":{"inputTokens":350,"outputTokens":240,"totalTokens":590}, …}
```

It is `null` on every other frame, so read it unconditionally — and read
"`usage` is not null" as *this message has finished*, which is the only
end-of-message signal on this stream. Note that the settling frame's `content`
is usually empty: that is why usage never reached a client before, since a
frame with no text used to be dropped. `usage` is developer material like a
tool's name, so a customer run always reads `null`. Sum across frames for a
run total; nothing publishes one.

#### `progress` — the frame a slow tool sends

An `update` frame fires when a node **completes**, and a `token` frame only
exists while a model is typing. A tool that spends forty seconds paging an API
does neither, so between two `update` frames the stream goes quiet and the run
reads as stopped. `progress` is what a step sends about itself *while it is
still working*:

```
event: progress
data: {"node":"agent-sql","message":"Read 40 of 100 invoices","current":40,"total":100,
       "activeNode":"agent-sql","path":["agent-sql"],"pathSlugs":["chinook-assistant"],
       "namespace":["agent_sql:7f3c"]}
```

`current` and `total` are `int` or `null` — `null` means "no claim", so render
a spinner rather than a bar. They are never a sentinel and never a non-finite
number, which JSON cannot carry.

`message` is written by the workflow's own developer and is addressed to
whoever is watching, so **it crosses to a customer intact** — unlike a tool's
name or its payload, which do not. A silent forty-second gap is worst for the
audience that cannot open a trace and work out what is happening.

`detail` is the exception, and the only field on this frame a customer never
receives. A finding line is composed so that **no value from a result is ever
spoken** — only integers — which is why a failed query reads `That did not
work.` and nothing more. That is right for a customer and useless for the
person who can fix the workflow, so the tool's own words ride here instead:

```
event: progress
data: {"node":"agent-sql","message":"That did not work.",
       "detail":"internal_error: ('42S22', \"[Microsoft][ODBC Driver 18 for SQL Server]
                 Invalid column name 'loading_time'. (207)\")",
       "current":null,"total":null,"activeNode":"agent-sql", ...}
```

The gate is server-side: on a customer stream the field is `null` on every
frame, whatever the tool said. It is `null` for a developer too on any line
with nothing to explain, which is almost all of them — a field that fires
every time is noise a reader learns to skip. Bounded at 400 characters and
flattened to one line.

**The built-in slow tools already send these.** Web Search says what it is
searching for, Web Fetch names the host it is reading, YouTube Transcript names
the video, and every MCP call announces itself as `Calling <tool> on <server>`
— that one because a call reopens its session, which costs ≈0.8 s before the
server is even asked. So a workflow assembled entirely from the palette
produces progress frames without anybody writing code. (Until production-ready
50 it produced none: the API shipped with no caller but its own docstring's
example. **`openstategraph knowledge build` is deliberately still silent** —
it is not a graph run, so there is no stream for it to write to.)

**A run whose steps say nothing sends no `progress` frames at all**, so a
client that ignores the event behaves exactly as it did before. Beyond the
built-ins, frames come only from steps that ask for them, by calling
`report_progress` from the package's own code:

```python
from openstategraph.abc import report_progress

report_progress("Read 40 of 100 invoices", current=40, total=100)
```

Outside a run that call is a no-op returning `False`, so a tool stays testable
with plain pytest. Under the hood this is LangGraph's `custom` stream mode; the
channel is shared with any other library writing to it, so only payloads
carrying our own envelope become frames and everything else is ignored.

#### A thread is the conversation

> **`POST /api/runs` obeys this too, and did not used to.** It declared
> `thread_id` and built no config at all, so three calls on one thread were
> three unrelated first turns — measured: the follow-up "how did you work that
> out?" classified `general_knowledge` there while the identical conversation
> over `/api/runs/stream` classified it `data_query`. It now passes the same
> block and returns `thread_id` on the response, so the non-streaming endpoint
> can hold a conversation like the streaming one. A workflow that *pauses*
> still cannot run there — it now answers **409** naming this endpoint, where
> before it returned `200` with an empty answer.

**Every terminal frame carries `threadId`** — the thread the run happened in.
Send it back as `thread_id` on the next question and that question is the next
*turn* of the same conversation: the graph's `messages` channel accumulates
there, and it is what a router classifies a follow-up against, what an agent
answers into, and what a mounted child workflow is handed. Omit it and the
server invents a fresh thread, so every send is turn one — "how did you get
that?" arrives with no antecedent for *that*, and is answered as if it were a
new question.

> **This page used to say something narrower**, and the difference caused a
> real defect rather than a documentation nit. It described `thread_id` as the
> thing "a client that wants to answer an approval should choose", and only
> `interrupt` disclosed one. A reader building a chat surface reasonably
> concluded a thread was an approval handle and skipped it — which is exactly
> what the editor's own Ask panel did, and why a follow-up there returned an
> unrelated answer. `done` and `error` now carry `threadId` too, so continuity
> is something a client can take rather than something it had to know to ask
> for in advance.

Nothing about a thread is client-side state you must persist: keep it for as
long as the conversation lasts, drop it to start a new one.

**How long that is, is a product decision, and the two surfaces here answer it
differently on purpose.** `/chat` persists a thread per workflow in
`localStorage`, so a customer's conversation survives a reload. The editor's Ask
panel holds one in memory only, and drops it on a reload or when a different
workflow is opened. The deciding difference is that neither surface persists its
*transcript*: restoring the id alone gives a conversation whose earlier turns
exist on the server and nowhere on screen. A customer asking a published
workflow will usually still recognise the thread they left; a developer who
reloaded after *editing the graph* would be continuing a conversation about a
workflow that no longer exists. See "The Chat panel is a conversation" in
`getting-started.md`.

#### Approvals

An `interrupt` frame carries the same `threadId`, and that is what a resume
targets. The thread is **persistent** — the checkpointer is durable by
default, so it survives a restart. Reusing one fixed `thread_id` across
*separate* conversations will resume the old one instead of starting a new
one; generate a fresh one per conversation, and pass the one from `interrupt`
back verbatim on resume.

Resume posts the **whole workflow document again**, not just the thread id:
the compile seam is one-directional and stateless per call. Nothing
server-side remembers which document a thread belongs to — only LangGraph's
own checkpointed state.

### `GET /api/events` — the catalogue stream

One event name: `workflows.changed`.

```
: connected

event: workflows.changed
data: {"reason": "unpublished", "slug": "quarterly-brief", "surface_visible": false}
```

`reason` is one of `published`, `unpublished`, `saved`, `deleted`. Lines
beginning with `:` are comments — a first one flushes the headers so `onopen`
fires immediately, and later ones are keepalives. `EventSource` ignores both.

The payload is a **hint, not a catalogue**: refetch `/api/workflows` when one
arrives. That way there is exactly one spelling of the catalogue and it cannot
go stale in a cache built from events — which is also how a client recovers
anything it missed while disconnected, since there is no replay.

Two limits, stated rather than discovered: the fan-out is **in-process**, so it
covers one worker (which is the documented deployment ceiling); and only writes
**through this API** emit — a `workflow.json` edited on disk or arriving by
`git pull` produces nothing.

---

## 3. The six calls a custom chat needs

Every request and response below was captured from a running server. The model
was a deterministic fake — this machine has no provider key, and a doc whose
text changes with the model's mood is not a doc — but the HTTP, the SSE bytes
and the interrupt/resume round trip are real.

### 1 — What is published: `GET /api/workflows?surface=chat`

```json
[
  {
    "slug": "quarterly-brief",
    "name": "Quarterly Brief",
    "saved_at": "2026-08-10T09:14:02.511Z",
    "node_count": 4,
    "edge_count": 3,
    "findings": [],
    "published": true,
    "hidden": false
  }
]
```

`surface=chat` is the customer surface: published **and** not hidden — so
`hidden` is always `false` on a `surface=chat` row, and every row is a workflow
a customer may pick.

The default, `surface=editor`, is the *author's* surface and answers a
different question: it returns drafts as well, **and hidden packages, each
carrying `hidden: true`**, so the editor can mark them rather than pretend they
are not there. That is why opening `concierge` in the editor works — a package
the listing omitted but `GET /api/workflows/{slug}` served 200 is what made the
editor announce `This workflow was deleted on disk` over a live file.

`findings` are package-contract complaints (`"error: ..."` / `"warning: ..."`);
a package too broken to read is omitted from `surface=chat` rather than shown
as rubble.

**Neither surface answers existence.** A slug's absence from `surface=chat`
means no customer surface advertises it — it may be `hidden` (the concierge
gateway and the workflow architect both are), or unreadable this instant — and
either way the package is still on disk. Only the endpoint below answers "is it
still there".

### 2 — Does it exist: `GET /api/workflows/{slug}/summary`

```json
{
  "slug": "concierge",
  "name": "Concierge (gateway)",
  "saved_at": "2026-08-08T12:00:00.000000+00:00",
  "node_count": 15,
  "edge_count": 17,
  "findings": [],
  "published": true,
  "hidden": true
}
```

The same row, asked about **one** slug, and the endpoint to use when the
question is whether a workflow is still there: it reports every package the
store can name, hidden ones included, and **404 is the only answer that means
gone**. A package present but unreadable comes back with `findings` and an
empty `saved_at` — damaged, not deleted, which is what a file caught mid-write
looks like. A malformed slug is a 422, never a 404, so a typo cannot be
mistaken for a deletion.

The editor's file watch polls exactly this, for its own slug. Any client that
tracks an open document should do the same rather than scanning the listing.

### 3 — The document: `GET /api/workflows/{slug}`

```json
{
  "slug": "quarterly-brief",
  "name": "Quarterly Brief",
  "document": {
    "version": 2,
    "name": "Quarterly Brief",
    "settings": {},
    "nodes": [
      { "id": "in1", "type": "input.text", "data": {}, "position": { "x": 40, "y": 200 } },
      { "id": "agent1", "type": "agent.llm", "data": {}, "position": { "x": 380, "y": 180 } },
      { "id": "approve1", "type": "human.approval", "data": { "message": "Send this brief to the team?" }, "position": { "x": 720, "y": 180 } },
      { "id": "out1", "type": "output.formatted", "data": {}, "position": { "x": 1060, "y": 200 } }
    ],
    "edges": [
      { "source": { "nodeId": "in1", "portId": "text" }, "target": { "nodeId": "agent1", "portId": "prompt" } },
      { "source": { "nodeId": "agent1", "portId": "result" }, "target": { "nodeId": "approve1", "portId": "candidate" } },
      { "source": { "nodeId": "approve1", "portId": "approved" }, "target": { "nodeId": "out1", "portId": "result" } }
    ]
  }
}
```

You need this because a run takes the document as **input**. The workflow that
executes is the one you can read — which is what makes the compile seam
one-directional and a run reproducible outside this editor.

**This body is what `PUT /api/workflows/{slug}` takes back**, unchanged
(`workflow-gallery` 42). Fetch, edit, put it back:

```bash
curl -s "$BASE/api/workflows/quarterly-brief" \
  | jq '.document.name = "Quarterly Brief v2"' \
  | curl -s -X PUT "$BASE/api/workflows/quarterly-brief" \
        -H 'content-type: application/json' -d @-
```

Until 42 that one-liner could not be written: the read shape was
`{slug, document}` and the write shape `{name, document}` with
`additionalProperties: false`, so the same body was rejected twice over —
once for the `name` the read shape did not carry, once for the `slug` it did.
The envelope's `name` closed the first half. The second half is the narrow
part and is worth reading before you rely on it: `PUT` tolerates `slug`
**only when it agrees with the path**, and answers `422` when it does not,
because a body naming another workflow is a confused client rather than an
instruction to cross-write. Nothing else was relaxed — a misspelt field is
still `422` rather than a silent no-op, and `POST /api/workflows` still
refuses `slug` outright, because minting an identity is the server's job
(ticket 20, below).

#### One mount of it: `GET /api/workflows/{root}/mounts/{path}`

A workflow package is a **class**. A `workflow.subgraph` node that references
it is an **instance**, and that node's `data.overrides`
are the instance's own — merged onto a copy of the package at compile time and
never written back (`docs/decisions/mount-overrides.md`).

So two mounts of one package run two different documents, and the call above
cannot express which. This one can:

```
GET /api/workflows/concierge/mounts/wf-music
```

```json
{
  "root": "concierge",
  "slug": "chinook-assistant",
  "mount_path": ["wf-music"],
  "document": { "…": "the package, with this mount's overrides applied" },
  "warnings": []
}
```

- `root` is the document the address is rooted in; `mount_path` is the chain of
  **mount node ids** that identifies which instance. Node ids, not slugs — a
  slug names the class, so `concierge/wf-other` is a different instance of the
  same `chinook-assistant`.
- `slug` is the **class**, and it is not redundant: capabilities, knowledge and
  the SQL schema all belong to the package, so those calls still take it.
- Add a segment per level of nesting —
  `/mounts/wf-music/wf-inner` for a grandchild. Each level's overrides are
  applied before the next is resolved, so a grandparent can override a
  grandchild through the parent's own `overrides` field.
- `warnings` is loud-but-not-fatal: an override naming a child node that no
  longer exists runs the package default and says so, rather than refusing to
  open.

`404` covers both "no such workflow" and "that path names nothing" — a stale
link and a deleted mount read the same way to a client. `422` is reserved for
an address that could not be a request at all.

The package on disk is never written by this call.

### 4 — Run it: `POST /api/runs/stream`

```json
{
  "workflow": { "...": "the document from call 3" },
  "workflow_slug": "quarterly-brief",
  "question": "How did revenue do this quarter?",
  "thread_id": "chat-8f2a1c"
}
```

No `audience` here, and that is the point: a chat client omits it and gets
`"customer"`, which is the surface that may not be shown authoring guidance.
See "Audience" above for what a `"developer"` run additionally receives.

`workflow_slug` is optional and additive: it layers the tools that live in that
workflow's own `tools/` folder over the defaults. It must be a **slug this
deployment has**, though — it also names the workflow's memory namespace and,
for a document with `settings.checkpointer: "sqlite"`, its checkpoint file. A
value that is not a slug is a `422` (the pattern is published in
`openapi.json`); a slug naming no installed workflow is a `404`, which is the
answer to "did my package install?" and not something to work around by
omitting the field. `thread_id` is optional too —
the server invents one and reports it back on the terminal frame — but a
client that sends a *second* question should pass the first one's `threadId`,
or the second question opens its own conversation and cannot refer back to the
first. See "A thread is the conversation" above.

The response, with the twenty token frames elided:

```
event: token
data: {"node": "in1", "namespace": [], "content": "How did revenue do this quarter?"}

event: update
data: {"node": "in1", "namespace": [], "taskId": "__turn_reset__", "internal": false, "activeNode": "in1", "output": "How did revenue do this quarter?"}

event: spawn
data: {"kind": "subgraph", "parent": "in1", "label": "agent1", "instruction": "", "taskId": null, "namespace": ["agent1:d03d731c-…"]}

event: token
data: {"node": "model", "namespace": ["agent1:d03d731c-…"], "content": "Revenue"}

event: update
data: {"node": "model", "namespace": ["agent1:d03d731c-…"], "taskId": null, "internal": true, "activeNode": "agent1", "output": null}

event: update
data: {"node": "agent1", "namespace": [], "taskId": null, "internal": false, "activeNode": "agent1", "output": "Revenue grew 12% quarter over quarter, driven by the Rock catalogue."}

event: interrupt
data: {"threadId": "chat-8f2a1c", "node": "approve1", "message": "Send this brief to the team?", "candidate": "Revenue grew 12% quarter over quarter, driven by the Rock catalogue."}
```

The stream ended on `interrupt`, so the run is paused and waiting — not
finished, and not broken.

#### When a grader judged the candidate

Grade-then-gate — the machine checks it, then a person decides — is the natural
shape for anything a person signs off. Where the node that produced the
candidate is a grader, the frame carries what that grader thought, so the
reviewer is not asked to stand behind a draft while the only existing machine
opinion of it stays in state:

```
event: interrupt
data: {"threadId": "smoke-triage-2", "node": "gate1",
       "message": "This reply goes to a customer under your name.",
       "candidate": "I'm sorry your invoice contains an error. …",
       "verdict": "revise",
       "reason": "'if appropriate' is a hedge and the rubric forbids holding phrases."}
```

Three things about those two fields:

- **They travel together or not at all.** A gate whose candidate came from an
  agent, a router or another gate carries neither key. Absence is a value: it
  says no machine opinion exists, not that the machine had nothing to say.
- **`verdict` is what the grader thought, not the branch it took.** A grader at
  its attempt cap writes `pass` to `decisions` — the compiler dispatches on
  that label — for an answer it rejected. This frame reports `revise` in that
  case, which is the whole reason a person is being asked.
- **The grader is the candidate's immediate producer.** Where several graders
  sit upstream along a chain, no walk is made further back: a judgement of some
  earlier text captioning this text would be a confident wrong statement rather
  than a missing one.

A third key, `check`, joins them when the grader reached that verdict **without
invoking a model** (`production-ready` 92). `BaseGrader.grade` runs
`deterministic_checks` first — an empty candidate, or one beginning
`Error`/`Traceback`/`Exception` — and returns before `self.model.invoke`, at
0.021 ms against 719-2024 ms for a judged verdict on a live run. Its value
names the check that fired (`empty`, `error`, and whatever a subclass overriding
`deterministic_checks` adds), so it is an **open set**: read its presence, never
look its value up in a table. The sentence to show a reader is `reason`, which
the grader wrote for exactly that.

(Until 2026-08-21 this sentence also said "the built-in `Grader` adds
`no_figure`". It does not and never has — `Grader` overrides `revise_payload`
and nothing else, which is the demonstration that a working grader is a
sentence of criteria rather than a new class. A check name stated in prose has
no way to fail; the ones below are named by the tests that produce them.)

One check does **not** come from `deterministic_checks`, and the difference is
worth knowing rather than hiding. `unrun_query` (`production-ready` 95) rejects
an answer that presents a SQL statement and figures when the run's own
`tool_use` says the query was never sent to anything. That is a fact about the
*run*, and a `BaseGrader` sees only a candidate string — so the grader **node**
decides it and dresses it as an ordinary rejection, which is why it prints like
every other rule-based verdict. Four conditions must hold together, and the
narrowness is the point: a SQL statement (not the English word "select"), two
or more figures (so an honest decline showing the query you *would* need is
untouched), a node that ran at least one tool and left one bound tool unused
(a node that ran *nothing* is a capability report and belongs to the developer
channel's `capability_gap`), and no node anywhere in the run having handed a
query to a tool. The last of those reads `tool_use[node]["queried"]`, which
names tools by what they were *given* rather than by what they are called.

`queried` names **the tools a query was actually handed to and whose body ran
with it**, and the second half is not decoration. The call arguments alone are
only a claim that a query was *written*: a name nothing binds carries its
arguments like any other (`production-ready` 98), and so does a real, bound
tool whose arguments failed their own schema, which LangGraph rejects before it
invokes the tool at all (`production-ready` 100). Both leave the database
untouched, and because any `queried` anywhere clears this check for the whole
run, either one would silently disarm it. A tool that ran a query and *then*
errored still counts — "errored" and "never executed" are different things, and
that query did leave the building.

The same pair rides an `update` frame, which is what a trace is built from. A
grader row that returned instantly used to have one available explanation and
it was the wrong one — three such rows are why `production-ready/84` was filed
as a broken timer, and the timer was right.

```
event: update
data: {"node": "grader-sql", "namespace": [], "taskId": null, "internal": false,
       "activeNode": "grader-sql", "path": ["grader-sql"], "pathSlugs": ["chinook-assistant"],
       "output": "Error: no such table: Track",
       "check": "error",
       "reason": "The step failed: Error: no such table: Track"}
```

Absence carries the same meaning it does on the interrupt frame, and it is the
one worth stating twice: no `check` means **no deterministic check fired**,
which covers an ordinary pass *and* a model's own rejection. Only its presence
is a claim.

### 5 — Answer the approval: `POST /api/runs/resume`

```json
{
  "workflow": { "...": "the same document" },
  "workflow_slug": "quarterly-brief",
  "thread_id": "chat-8f2a1c",
  "decision": "approve"
}
```

`decision` is `approve` or `reject`; `feedback` is an optional string handed to
the node that gets the rejection. The stream that comes back is the same
vocabulary again:

```
event: update
data: {"node": "approve1", "namespace": [], "taskId": null, "internal": false, "activeNode": "approve1", "output": "Revenue grew 12% quarter over quarter, driven by the Rock catalogue."}

event: token
data: {"node": "out1", "namespace": [], "content": "Revenue grew 12% quarter over quarter, driven by the Rock catalogue."}

event: done
data: {"threadId": "chat-8f2a1c", "answer": "Revenue grew 12% quarter over quarter, driven by the Rock catalogue.", "decisions": {"approve1": "approved"}, "outputs": {"in1": "…", "agent1": "…", "approve1": "…", "out1": "…"}, "nested": {}, "attempts": 1, "mermaid": "graph TD;…"}
```

**The `done` frame of a resumed run reports the whole run, not the segment you
just watched.** `in1` and `agent1` ran before the pause and are in `outputs`
anyway, and `attempts` counts the agent invocations of both halves — the same
values `GET /api/threads/{id}` and `openstategraph threads show` report for
that thread, and the same values `POST /api/runs` would return for the run.

The `update` and `token` frames above are the opposite, and deliberately: they
are per-segment, because a client watching a resume is watching this half
happen and must not be re-sent the first half's tokens. The rule is that a
*progress* frame reports the segment and the *terminal* frame reports the run
(`workflow-gallery` 25 — until it was fixed, a resumed approval reported
`attempts: 0` and an `outputs` map with the drafting node missing from it,
while `POST /api/runs` reported both).

### 6 — The compiled diagram: `GET /api/workflows/{slug}/graph`

```json
{
  "mermaid": "---\nconfig:\n  flowchart:\n    curve: linear\n---\ngraph TD;\n\t__start__(<p>__start__</p>)\n\tagent1(agent1)\n\tapprove1(approve1)\n\tin1(in1)\n\tout1(out1)\n\t__start__ --> in1;\n\tagent1 --> approve1;\n\tapprove1 -. &nbsp;approved&nbsp; .-> out1;\n\tin1 --> agent1;\n\tout1 --> __end__;\n"
}
```

This is what the **compiler actually produced**, not a redrawing of the canvas.
It is asked for with `xray=True`, which today expands **nothing**: this
compiler emits no LangGraph subgraph — a mount is a closure over the child's
`invoke()` and an agent is built lazily inside its node's closure, and neither
is a node LangGraph can open. So a mounted child shows as one box, and
`backend/tests/test_behind_the_scenes.py` fails the day that stops being true.
Mermaid *text*, never a PNG — LangGraph's `draw_mermaid_png()` posts the graph
to a third-party API, and a user's graph is not ours to send anywhere. Render
it client-side.

A seventh call is optional and worth it: `GET /api/events`, above, so a picker
built from call 1 does not go stale the moment somebody publishes.

### Writing — `POST /api/workflows` mints the slug, `PUT` overwrites one

A chat client never writes; an editor does, and the two calls are deliberately
different questions.

```
POST /api/workflows            {"name": "My Workflow", "document": {...}}
  → 201 {"slug": "my-workflow", "document": {...}}

POST /api/workflows            {"name": "My Workflow", "document": {...}}
  → 201 {"slug": "my-workflow-k7m3qp", "document": {...}}
```

**A name is not an identity, so a client must not derive a slug from one.** The
first workflow of a name keeps the clean slug; a colliding one gets an
ordinal — `my-workflow-2`, `my-workflow-3` — and the response's `slug` is the
answer, never something to recompute. Suffixing only on collision keeps the
common URL clean.

(This paragraph said the suffix was *random*, and argued that a counter would
make two simultaneous clients both compute `-2`. That is true of a counter
which queries, and `_candidate_slugs` does not: it yields a sequence and
`create` adjudicates each by `mkdir(exist_ok=False)`, so the loser of a race
takes `-3` on its next turn and neither can overwrite the other. The random
token was reverted because the drawer showed no slug at all, leaving two rows
named "AI Workflow" told apart only by `…/?w=ai-workflow-tsi934` — six
characters nobody can read, remember or repeat over a call.)

`PUT /api/workflows/{slug}` **addresses a package you already hold a slug for**
and overwrites its document. It still creates one at a free slug — that is how
the CLI and a test write a package they intend to own — but a client with no
slug yet must `POST`. This is not a style preference: until ticket 20 the
editor slugified the name in the browser and PUT to the result, so a second
"My Workflow" landed on the first one's directory and overwrote it, 200 OK,
no prompt, no trace.

**Unless you send `must_exist: true`**, which turns a free slug into a `404`
instead of a create. That is for the caller the create is wrong for: a client
that already holds a package and is *editing* it. Without it, an editor tab
whose workflow another tab had deleted re-created the package on its next
keystroke — `workflow.json` and `AGENTS.md` and nothing else, with the
package's `tools/`, `functions/`, `tests/`, `skills/`, `middlewares/` and
`data/` gone for good and `published` reset to `false`, reported as a
successful save (`launch-readiness` 147). The editor now sets it on every save
it makes. A script that intends to own a directory simply omits it, and the
behaviour above is unchanged.

The slug is **frozen at creation**. Renaming a workflow changes the display
name inside `workflow.json` and never the directory, so every link, mount and
line of git history keeps resolving.

**A save that changed nothing writes nothing** (`production-ready` 67). If the
stored envelope already matches what you sent — same document, same name, same
lifecycle flags — the file is left untouched, `mtime` included, and the
response is still `200`. So **`saved_at` does not advance on every `PUT`**, and
a client must not treat an unchanged `saved_at` as a failed save; the response
status is what reports success. This exists because `saved_at` is a wall clock
and `workflow.json` is meant to be reviewed as source: without the guard,
pressing Save with nothing edited produced a real diff containing only a new
timestamp, in a directory an adopter tracks in git by design. Only the
timestamp is excluded from the comparison — a rename or a publish is a change
and is written.

**And a node's `size` is what somebody set, not what the browser measured**
(`production-ready` 69). Card heights are measured off the rendered HTML on
every layout, so while they were written back, a change to card styling
rewrote every stored workflow the next time it was opened and saved — five
heights moved in `chinook-assistant` with nobody having touched a node. The
editor now keeps the two apart: the rendered size drives the canvas, and the
document carries only sizes an authoring gesture produced — a container frame
dragged by its grip, a frame `Arrange` refitted, the size an assembly gave a
node it created. `size` is optional in a document you write by hand; leave it
out and the node takes its type's default, which is what the examples above
do.

Those authoring gestures **autosave like any other edit** (`production-ready`
70). Until they did, a frame you dragged by its grip was written only if you
also pressed Save: the editor's autosave ignored `size` entirely, because a
measurement must never be able to rewrite a package on a loop. It still
ignores measured sizes — every card but a container's frame — and now compares
the one size nothing measures.

### Copying — `POST /api/workflows/{slug}/duplicate`

```
POST /api/workflows/chinook-assistant/duplicate   {}
  → 200 {"slug": "chinook-assistant-copy",
         "name": "Chinook Assistant (copy)",
         "source": "chinook-assistant"}

POST /api/workflows/chinook-assistant/duplicate   {"name": "Chinook Experiment"}
  → 200 {"slug": "chinook-experiment", ...}
```

**Copies the whole package** — `workflow.json` plus `tools/`, `functions/`,
`skills/`, `tests/`, `data/`, `knowledge/`, whatever else the directory has
grown. That is why this is a server call and not something a client assembles
from `GET` + `POST`: the client-side version copies the document alone, and the
copy's nodes then bind to tools that are not there — a failure that surfaces
when somebody runs it, not when they copy it.

Three things the copy does not inherit, each deliberate:

- **The slug.** Minted the same way `POST /api/workflows` mints one, and
  returned for the same reason: it is the part you cannot predict.
- **`published`.** A copy is always a draft. Publishing is a decision about a
  specific package, and inheriting it puts something on `/chat` nobody chose to
  put there.
- **`AGENTS.md`**, which names its own slug and is rewritten for the copy
  rather than carried over pointing at the original.

Mounts inside the copied document are left alone: they reference *other*
packages by slug, and the copy legitimately shares them.

`name` is optional. Omitted, the copy is `<original> (copy)` — defaulted here
because the default depends on the original's name, which the server already
has and a client would have to fetch first.

404 if the source does not exist, 422 if the slug cannot name a directory.
Announces `saved` for the **copy** on `GET /api/events`; the original did not
change.

### Checking before writing — `POST /api/workflows/validate`

```
POST /api/workflows/validate   {"workflow": {...}}
  → 200 {"valid": false, "findings": ["unknown node type 'agent.react' on 'a1'"]}
```

Plans the posted document in memory and throws it away, so it reaches no
provider and needs no credential — a developer can call it long before a key
is configured. `findings` is a list of single lines, one per problem, empty
when valid.

**A `false` verdict is not a refusal to run.** The run endpoints report an
unknown node type on the developer channel and continue, because a canvas
mid-edit is invalid most of the time and `errors.py`'s rule for this case is
"degrade loud, never silent". The MCP door does refuse, because an LLM client
can act on the findings and a run that cannot produce a meaningful answer
wastes a model call. One validator, two policies.

This existed only as an MCP tool until 0.3.0, which is why an unregistered node
type could reach a run: the skipped node forwards its input unchanged, so the
run answered with the user's own question and looked like it worked.

### Optional — past runs: `GET /api/threads` and `GET /api/threads/{id}`

What the checkpointer already stored, read back. `GET /api/threads` lists runs
newest first, filterable by `workflow_slug`, `user_email` (case-folded, like
the memory namespace) and `session_id`; `GET /api/threads/{id}` returns one run
checkpoint by checkpoint.

`session_id` groups the threads of one **sitting** — the editor mints one per
browser tab and sends it on every run, so it spans the several conversations a
person has in one visit. It is empty for a run that had no tab behind it (an
MCP call, a script), and an empty filter value is not a filter: it lists
everything.

```json
{
  "threads": [
    {
      "thread_id": "chat-8f2a1c", "workflow_slug": "chinook-assistant",
      "session_id": "", "user_email": "", "updated_at": "2026-08-11T09:12:04Z",
      "steps": 6, "question": "Which genre earns the most revenue?",
      "answer": "Rock, $826.65.", "status": "finished", "failed": false
    }
  ]
}
```

Both are **reads**. Nothing re-executes, no model is called, and neither
endpoint can start or change a run — a `paused` thread is continued through
`POST /api/runs/resume` (call 5) and nowhere else. Values are capped
server-side and private channels are omitted, so a thread carrying a long
message history does not become a multi-megabyte response.

#### A stored run has an audience too

`GET /api/threads/{id}` takes `?audience=customer|developer`, the same
parameter a run takes on its body and capped by the same
`OPENSTATEGRAPH_AUDIENCE` ceiling. **It defaults to `customer`**, so a client
that does not ask reads a customer's history.

A customer's history is the same shape as a customer's live run, which is the
whole rule — a fact refused on the wire must not be readable afterwards:

| On a customer read | |
| --- | --- |
| `tool_calls` | **`[]`** — no tool name, no arguments, no result. The step is still listed and still timed |
| `tokens` | **`null`**, always, exactly as `usage` is on a customer's stream |
| `values` / `wrote` | only the channels a customer's own `done` frame carries — `question`, `answer`, `decisions`, `routes`, `outputs`, `nested_outputs`, `attempts`. The machinery channels (`messages`, `tool_use`, `redactions`, a grader's `verdicts`, a deep agent's files) are absent |
| `duration_ms` | unchanged — elapsed time is a property of the deployment, not of the content (see `seq` and `elapsedMs` above) |

`values` is filtered by a declaration the state channel itself carries, not by
a list this endpoint keeps, so a channel added to the runtime tomorrow is
withheld from a customer until somebody marks it otherwise. The examples below
are a **developer** read.

Until `the-boundary-nobody-checked/02` this endpoint had no audience at all
and answered every caller with the developer view: the tool's name, the
statement it was sent, the rows that came back, the usage, and the whole
`tool_use` channel. No shipped client called it that way, which is why this is
a correction and not an incident.

`status` and `failed` answer two different questions and must not be
conflated. `status` is `paused` (stopped at an `interrupt()`, resumable) or
`finished` (nothing pending) — a failed run is `finished`, not a third status
value, because a failed run is not waiting on anyone. `failed` is `true` when
a node wrote the failure sentinel (`[<node> failed after retries: …]`) into
`outputs` — the same signal `node_failure_warnings` reports on a live run —
read back from the stored checkpoint. It is **not** derived from an empty
`answer`: a workflow may legitimately answer with nothing, which is a
different, separately-reported case (`silent_node_warnings`). Before this,
`threads list`/`threads show` and both endpoints reported every non-paused
run as `finished` with no way to tell a completed answer from a run that
produced nothing and exited 1 (production-ready/78).

A `paused` thread carries `pause: {"message": …, "candidate": …}` — the same
node-authored payload `POST /api/runs`, `POST /api/runs/stream` and
`openstategraph run` report when a run stops at the gate, read back here off
the pending `__interrupt__` write rather than a second store. `finished`
threads carry `pause: null`. Before this it was reachable only from the
process that started the run: `threads` printed `status: "paused"` and
nothing about what the gate was asking, so a client rebuilding an approval UI
from `GET /api/threads` alone had no payload to show (`workflow-gallery` 76).
`openstategraph threads show` also prints the exact `resume` command for a
paused thread — the CLI knows the package path a JSON client would have to
resolve itself from `workflow_slug`.

A step says **which graph it belongs to**, which is what makes a run with any
fan-out readable:

```json
{
  "checkpoint_id": "1f0…", "step": 3, "at": "2026-08-20T06:33:06Z",
  "source": "loop",
  "namespace": ["worker_web"], "node": "worker_web",
  "wrote": ["outputs", "worker_results"],
  "tool_calls": [
    { "name": "web_fetch", "arguments": "{\"url\": \"https://example.com\"}",
      "result": "Error: web_fetch is not a valid tool, try one of […]." }
  ],
  "duration_ms": 1791,
  "tokens": { "input_tokens": 1436, "output_tokens": 86, "total_tokens": 1522 },
  "values": { "answer": "…" }
}
```

One thread holds the workflow's own checkpoints **and** those of every agent
subgraph it ran, and each numbers its supersteps from `-1`. Flat, a run with
three parallel workers therefore prints `Step 0 · loop` once per graph, as
though one graph had repeated itself. `namespace` is the workflow's graph path,
outermost first — `[]` is the workflow itself — read exactly like a stream
frame's `path`; `node` is its innermost entry; `wrote` names the channels that
superstep wrote, where `values` is what the state *was*.

A node dispatched twice appears under one `node` with two runs of steps: the
instance is not part of the namespace, because for identity two dispatches are
one worker. Group by `namespace` and start a new group when `step` returns to
`-1`.

`tool_calls` are the calls **this** superstep asked for, with their arguments
and what came back — never the contents of the message channel, which is
cumulative and holds the whole history at every checkpoint. The request and its
answer land in different supersteps, and the server pairs them onto the one
that asked. `arguments` is `""` when the request is no longer in the stored
history, and `result` is `""` when no answer was stored — which means the run
ended or was stopped before one arrived, not that the tool returned nothing.

`duration_ms` and `tokens` are **how long this superstep took and what it
cost** — the two numbers a profiler exists for, and both read straight out of
the checkpoints. A checkpoint is written after its superstep runs, so the gap
between consecutive `ts` values *within one namespace* is that superstep's
elapsed time; token counts ride on the `AIMessage` in `usage_metadata` for
every provider that reports usage. Neither needed a new store.

**Both are `null` rather than `0` when they are not known, and a client must
not coalesce them.** `duration_ms` is `null` for the first step of a graph,
for an unreadable timestamp, and for a `source: "input"` step — that one
records what was handed in rather than running anything, so on a second turn
its gap from the previous turn measures how long the *person* took to type.
`tokens` is `null` on a superstep that called no model. Zero is the claim
*this was instant* or *this was free*, and none of those cases support it.

Read `duration_ms` for what it is: a parent superstep that dispatched workers
spans their whole run, because it did. What is genuinely **not** recoverable,
and is not published rather than guessed, is the split of one superstep between
model time and tool time.

They are honest about their limits: a deployment with no checkpointer, or a
custom saver that cannot enumerate, returns an empty list rather than an
error — the truthful answer from a store that cannot say is silence. The
editor's own **History** toggle in the Chat panel is built on exactly these two
calls and nothing else, and it draws one lane per graph from these fields.

`namespace` and `node` are **compiled** names: the compiler rewrites every
non-alphanumeric character of a canvas node id so LangGraph will accept it, so
the node a document calls `worker-web` is stored here as `worker_web`. Read
that back **forward** — mangle the ids of the document you have open the same
way and look the stored name up in the result. Do not try to reverse it: the
mangling is not injective (`worker-web`, `worker.web` and `worker_web` all
land on `worker_web`), and a label that quietly names the wrong node is worse
than one that looks technical. A name your document does not account for
belongs to some other document — a mounted package's node — and should be
shown as stored. The editor does exactly this in
`src/core/runtime/graphName.ts`.

---

## 4. A whole client, in one file

A complete chat client — list, load, stream, approve, done — in about sixty
lines. **The whole file is printed below**, because a reader who installed the
wheel has these docs and not this repository; in a checkout it is also
`docs/examples/minimal-client.html`. Save it, serve it, use it:

```bash
openstategraph serve --port 8000                      # terminal 1
OPENSTATEGRAPH_ALLOWED_ORIGINS=http://localhost:8765 \
  openstategraph serve --port 8000                    # ...or this, see CORS below

# terminal 2 — from wherever you saved it (in a checkout: cd docs/examples)
python3 -m http.server 8765
open http://localhost:8765/minimal-client.html
```

`?api=http://host:port` points it at a server somewhere else.

```html
<!doctype html>
<meta charset="utf-8" />
<title>Minimal OpenStateGraph client</title>
<input id="q" size="48" value="How did revenue do this quarter?" /><button id="go">Ask</button>
<pre id="out">loading…</pre>
<script>
  // Where your server is. `?api=http://host:port` overrides it.
  const API = new URLSearchParams(location.search).get("api") ?? "http://127.0.0.1:8000";
  const out = document.getElementById("out");
  // `thread` is the conversation — held across asks; null it to start a new one.
  let doc = null, slug = null, thread = null;

  async function load() { // 1 + 2: what is published, and its document
    const [first] = await (await fetch(`${API}/api/workflows?surface=chat`)).json();
    slug = first.slug;
    doc = (await (await fetch(`${API}/api/workflows/${slug}`)).json()).document;
    out.textContent = `ready: ${first.name}\n`;
  }

  async function stream(path, body) { // 4 + 5: POST, then read the frames
    const res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return void (out.textContent += "\n[connection dropped]\n"); // no terminal frame
      buffer += value;
      const frames = buffer.split("\n\n");
      buffer = frames.pop();
      for (const frame of frames) {
        const name = frame.match(/^event: (.*)$/m)?.[1];
        const data = JSON.parse(frame.match(/^data: (.*)$/m)?.[1] ?? "{}");
        // Every text-producing node emits tokens — the input node echoes your
        // question, the output node re-renders the answer. Key on data.node.
        if (name === "token") out.textContent += data.content;
        // Every terminal frame names its thread. Remember it, or the next ask
        // opens a fresh conversation and every follow-up loses its antecedent.
        if (data.threadId) thread = data.threadId;
        if (name === "done") return void (out.textContent += `\n\n${data.answer}\n`);
        if (name === "error") return void (out.textContent += `\n[error] ${data.detail}\n`);
        if (name === "interrupt") {
          if (!confirm(data.message)) return;
          return stream("/api/runs/resume", { workflow: doc, workflow_slug: slug,
            thread_id: data.threadId, decision: "approve" });
        }
      }
    }
  }

  document.getElementById("go").onclick = () => {
    out.textContent = "";
    stream("/api/runs/stream", { workflow: doc, workflow_slug: slug,
      question: document.getElementById("q").value, thread_id: thread ?? undefined });
  };
  load();
</script>
```

Sixty lines, and it handles all three terminal frames plus the
no-terminal-frame case. That is the whole shape of a client; everything else is
presentation.

---

## 5. CORS, and what a browser client must do about it

**The allowlist is explicit and there is no wildcard.** This process holds
provider API keys, so `Access-Control-Allow-Origin: *` is off the table
permanently — a wildcard on a credential-holding API is how one key becomes
everyone's.

Out of the box exactly two origins are allowed, and they are the editor's Vite
dev server:

```
http://localhost:5273
http://127.0.0.1:5273
```

A page served from anywhere else has three options:

1. **Be same-origin.** A server started with the built editor serves `/`,
   `/chat` and `/api/*` from one origin, and a same-origin page needs no CORS
   at all. This is the best answer for anything you deploy.
2. **Name your origin.** `OPENSTATEGRAPH_ALLOWED_ORIGINS` takes a
   comma-separated list, **added** to the two above (so letting your page in
   never locks the editor out):

   ```bash
   OPENSTATEGRAPH_ALLOWED_ORIGINS=http://localhost:8765,https://app.example.com \
     openstategraph serve
   ```

   `*` is refused, loudly, at startup rather than quietly dropped — a silently
   ignored wildcard leaves you believing your client is allowed until the
   browser says otherwise.
3. **Put a reverse proxy in front** that serves your page and the API under one
   hostname. Then you are back to option 1.

Credentials are not sent cross-origin (`allow_credentials` is off), so a
cookie-authenticated browser client wants option 1 or 3.

**Authentication is separate and off by default.** If the server was started
with `OPENSTATEGRAPH_API_TOKEN` set, every request needs
`Authorization: Bearer <token>`; without it, anyone who can reach the port has
full access. Do not put the token in a public page — a browser client on a
shared network wants the proxy, not the shared secret. See
[deploying](deploying.md).

---

## 6. Is there a typed client? No — and here is what to use instead

**Decision: we ship the schema, not a package.** There is no
`@openstategraph/client` on npm and none is planned.

The argument for publishing one is real but small: six calls, five of them a
single `fetch`. The argument against is that a package is a *version* — its own
release train, its own changelog, its own semver relationship to a Tier 3 API
that may change in a patch, and its own bug reports for a bug in the API. It
would also be a JavaScript-shaped answer to a question people ask in Python and
Go, and the thing that actually helps every one of them is the schema.

What you get instead, which costs us nothing to keep correct:

```bash
npx openapi-typescript docs/openapi.json -o api.d.ts   # or point it at http://localhost:8000/openapi.json
```

That gives you request and response types for every endpoint in this document,
generated from the same bytes CI diffs — so they cannot drift from the server.
Any [OpenAPI generator](https://openapi-generator.tech/) works the same way for
other languages.

The streams are the part no generator can produce, which is the other half of
the reasoning: a typed client would still hand you an untyped `fetch` for the
three endpoints that matter most, and the whole-file example above is a more
useful answer than a wrapper that stops exactly where the difficulty starts.

If you want types for the frames, they are six small interfaces — copy them out
of the table in §2 and own them, rather than depending on us to version them.

**If you are embedding a workflow in a Python program, do not use HTTP at all.**
`load_workflow()` is Tier 1, stable, and skips the server entirely — see
[adoption](adoption.md).
