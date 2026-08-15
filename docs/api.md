# The HTTP API — build your own UI

Both shipped surfaces — the canvas editor and `/chat` — are ordinary clients of
the endpoints on this page. There is no private API behind them, so a third
client is a supported thing to build rather than a reverse-engineering
exercise.

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

Six event names. A resumed run is not a different kind of thing from a
client's point of view — it is the same stream picking back up — so both
endpoints emit the identical vocabulary and one parser handles both.

| Event | Meaning | Payload |
| --- | --- | --- |
| `update` | a graph step reported | `node`, `namespace`, `taskId`, `internal`, `activeNode`, `path`, `output` |
| `token` | a chunk of model (or node) text | `node`, `namespace`, `content`, `activeNode`, `path` |
| `spawn` | the run created a child worker or subagent | `kind` (`fanout`/`subagent`/`subgraph`), `parent`, `label`, `instruction`, `taskId`, `namespace` |
| `interrupt` | **terminal** — a `human.approval` node paused the run | `threadId`, `node`, `message`, `candidate` |
| `done` | **terminal** — the run finished | `threadId`, `answer`, `decisions`, `outputs`, `nested`, `attempts`, `mermaid`, and `developer` **only for a developer run** |
| `error` | **terminal** — the run failed | `threadId`, `detail` |

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

The key is **absent**, not empty, on a customer run — so a client cannot read
"there were no findings" out of a frame that was never entitled to carry any.

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

`mermaid` deliberately stays on both audiences: it is the compiled topology
that a chat page draws its live flow diagram from, and
`GET /api/workflows/{slug}/graph` already serves the same text. `decisions`,
`outputs` and `attempts` stay too — they are facts about the customer's own
turn.

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
> long enough to send one. `update`, `token` and `spawn` are progress: after
> any of them, keep waiting.

A client must never tell "still working", "finished" and "died" apart by
waiting and guessing. There is exactly one exception, and it is honest rather
than an oversight: **if the client disconnects or the server dies, no terminal
frame is possible** — there is no socket left to write to. So a body that ends
without one of the three means *the connection dropped*, and an aborted
`fetch` means *you stopped it*. Never a silent success, and never a spinner
that runs forever.

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
data: {"threadId": "chat-8f2a1c", "answer": "Revenue grew 12% quarter over quarter, driven by the Rock catalogue.", "decisions": {"approve1": "approved"}, "outputs": {"approve1": "…", "out1": "…"}, "attempts": 0, "mermaid": "graph TD;…"}
```

### 6 — The compiled diagram: `GET /api/workflows/{slug}/graph`

```json
{
  "mermaid": "---\nconfig:\n  flowchart:\n    curve: linear\n---\ngraph TD;\n\t__start__(<p>__start__</p>)\n\tagent1(agent1)\n\tapprove1(approve1)\n\tin1(in1)\n\tout1(out1)\n\t__start__ --> in1;\n\tagent1 --> approve1;\n\tapprove1 -. &nbsp;approved&nbsp; .-> out1;\n\tin1 --> agent1;\n\tout1 --> __end__;\n"
}
```

This is what the **compiler actually produced**, not a redrawing of the canvas:
subgraphs are expanded, so a mounted team or a routed child shows its insides.
Mermaid *text*, never a PNG — LangGraph's `draw_mermaid_png()` posts the graph
to a third-party API, and a user's graph is not ours to send anywhere. Render
it client-side.

A sixth call is optional and worth it: `GET /api/events`, above, so a picker
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
first workflow of a name keeps the clean slug; a colliding one gets a short
random disambiguator, and the response's `slug` is the answer — never something
to recompute. Suffixing only on collision keeps the common URL clean, and the
suffix is random rather than a `-2` counter because two clients creating the
same name at the same moment would both compute `-2` and one would still lose.

`PUT /api/workflows/{slug}` **addresses a package you already hold a slug for**
and overwrites its document. It still creates one at a free slug — that is how
the CLI and a test write a package they intend to own — but a client with no
slug yet must `POST`. This is not a style preference: until ticket 20 the
editor slugified the name in the browser and PUT to the result, so a second
"My Workflow" landed on the first one's directory and overwrote it, 200 OK,
no prompt, no trace.

The slug is **frozen at creation**. Renaming a workflow changes the display
name inside `workflow.json` and never the directory, so every link, mount and
line of git history keeps resolving.

### Copying — `POST /api/workflows/{slug}/duplicate`

```
POST /api/workflows/chinook-assistant/duplicate   {}
  → 200 {"slug": "chinook-assistant-copy-k7m3qp",
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

```json
{
  "threads": [
    {
      "thread_id": "chat-8f2a1c", "workflow_slug": "chinook-assistant",
      "session_id": "", "user_email": "", "updated_at": "2026-08-11T09:12:04Z",
      "steps": 6, "question": "Which genre earns the most revenue?",
      "answer": "Rock, $826.65.", "status": "finished"
    }
  ]
}
```

Both are **reads**. Nothing re-executes, no model is called, and neither
endpoint can start or change a run — a `paused` thread is continued through
`POST /api/runs/resume` (call 5) and nowhere else. Values are capped
server-side and private channels are omitted, so a thread carrying a long
message history does not become a multi-megabyte response.

They are honest about their limits: a deployment with no checkpointer, or a
custom saver that cannot enumerate, returns an empty list rather than an
error — the truthful answer from a store that cannot say is silence. The
editor's own **History** toggle in the Chat panel is built on exactly these two
calls and nothing else.

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
three endpoints that matter most, and the forty-line example above is a more
useful answer than a wrapper that stops exactly where the difficulty starts.

If you want types for the frames, they are six small interfaces — copy them out
of the table in §2 and own them, rather than depending on us to version them.

**If you are embedding a workflow in a Python program, do not use HTTP at all.**
`load_workflow()` is Tier 1, stable, and skips the server entirely — see
[adoption](adoption.md).
