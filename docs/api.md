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
| `update` | a graph step reported | `node`, `namespace`, `taskId`, `internal`, `activeNode`, `output` |
| `token` | a chunk of model (or node) text | `node`, `namespace`, `content` |
| `spawn` | the run created a child worker or subagent | `kind` (`fanout`/`subagent`/`subgraph`), `parent`, `label`, `instruction`, `taskId`, `namespace` |
| `interrupt` | **terminal** — a `human.approval` node paused the run | `threadId`, `node`, `message`, `candidate` |
| `done` | **terminal** — the run finished | `answer`, `decisions`, `outputs`, `attempts`, `mermaid`, `warnings` |
| `error` | **terminal** — the run failed | `detail` |

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

#### Tokens come from every text-producing node

`token` frames are not only the agent's. The input node echoes the question and
the output node re-renders the final answer, each as its own `token` frame.
Key on `data.node` if you want one node's stream.

#### Approvals

An `interrupt` frame carries the `threadId` to resume with. That thread is
**persistent** — the checkpointer is durable by default, so it survives a
restart. Reusing one fixed `thread_id` across conversations will resume the old
one instead of starting a new one; generate a fresh one per conversation, and
pass the one from `interrupt` back verbatim on resume.

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

## 3. The five calls a custom chat needs

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
    "published": true
  }
]
```

`surface=chat` is the customer surface: published **and** not hidden. The
default, `surface=editor`, also returns drafts, each carrying its `published`
flag. `findings` are package-contract complaints (`"error: ..."` /
`"warning: ..."`); a package too broken to read is omitted rather than shown as
rubble.

### 2 — The document: `GET /api/workflows/{slug}`

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

### 3 — Run it: `POST /api/runs/stream`

```json
{
  "workflow": { "...": "the document from call 2" },
  "workflow_slug": "quarterly-brief",
  "question": "How did revenue do this quarter?",
  "thread_id": "chat-8f2a1c"
}
```

`workflow_slug` is optional and additive: it layers the tools that live in that
workflow's own `tools/` folder over the defaults. `thread_id` is optional too —
the server invents one — but a client that wants to answer an approval should
choose it, or read it back off the `interrupt` frame.

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

### 4 — Answer the approval: `POST /api/runs/resume`

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
data: {"answer": "Revenue grew 12% quarter over quarter, driven by the Rock catalogue.", "decisions": {"approve1": "approved"}, "outputs": {"approve1": "…", "out1": "…"}, "attempts": 0, "mermaid": "graph TD;…", "warnings": []}
```

### 5 — The compiled diagram: `GET /api/workflows/{slug}/graph`

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

---

## 4. A whole client, in one file

`docs/examples/minimal-client.html` is a complete chat client — list, load,
stream, approve, done — in about forty lines. Save it, serve it, use it:

```bash
openstategraph serve --port 8000                      # terminal 1
OPENSTATEGRAPH_ALLOWED_ORIGINS=http://localhost:8765 \
  openstategraph serve --port 8000                    # ...or this, see CORS below

cd docs/examples && python3 -m http.server 8765       # terminal 2
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
  let doc = null, slug = null;

  async function load() { // 1 + 2: what is published, and its document
    const [first] = await (await fetch(`${API}/api/workflows?surface=chat`)).json();
    slug = first.slug;
    doc = (await (await fetch(`${API}/api/workflows/${slug}`)).json()).document;
    out.textContent = `ready: ${first.name}\n`;
  }

  async function stream(path, body) { // 3 + 4: POST, then read the frames
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
      question: document.getElementById("q").value, thread_id: `chat-${Date.now()}` });
  };
  load();
</script>
```

Forty-six lines, and it handles all three terminal frames plus the
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

The argument for publishing one is real but small: five calls, four of them a
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
