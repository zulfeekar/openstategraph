# Wiring a workflow into your app

You drew a flow, you ran it until it was right, and now it has to live inside
something you already own — a FastAPI service, an Express backend, a chat panel
in your product. This page is the seam:

> `input → [workflow] → output`, streamed, with the username, the thread and
> the session carried through.

[The HTTP API](api.md) answers it for a frontend talking to **our** server.
[Using it in your project](adoption.md) answers it for a service that loads a
package **in-process**. Neither one shows a stream reaching a browser from the
embedded shape, and neither collects the identity keys in one place. Both are
here.

## 1. Which of the two shapes you are in

Answer this first, because every later answer differs.

| | **Host our server** | **Embed the library** |
| --- | --- | --- |
| What you run | `openstategraph` serves HTTP; your app is a client | your own process; `load_workflow()` in it |
| Who owns the loop | we do | you do |
| Who frames the stream | we do — SSE, documented event vocabulary | you do — you translate LangGraph events into whatever your frontend speaks |
| The checkpointer | ours, shared by every transport | yours to pass, or ours by default |
| Where to read on | [api.md §3, the six calls a custom chat needs](api.md#3-the-six-calls-a-custom-chat-needs) | §2 and §3 below |
| Costs you | running a second service | writing the ~30 lines in §3 |

Two things that are **not** a difference: the package on disk is identical, and
the identity vocabulary in §4 is identical. A workflow does not know which door
it came through.

If your frontend is a browser and you are happy to run our server, stop here
and go to `api.md` — it has the SSE framing, the terminal-frame guarantee, the
resume call and a whole working client in one file. Nothing on this page
replaces it.

## 2. `input → workflow → output`, blocking

The smallest complete answer, for a request/response endpoint that does not
stream:

```python
from openstategraph import load_workflow

workflow = load_workflow("workflows/my-thing")

result = workflow.ask(
    "How many invoices are there?",
    thread_id="conversation-42",
    user_email="ada@example.com",
    session_id="browser-tab-7",
)

result            # the answer — a str subclass
result.decisions  # node id -> the branch a router or grader chose
result.failures   # the half that means "this run broke"; gate on this, not .warnings
result.usage      # model name -> tokens it reported; {} means unknown, not free
```

`ask()` seeds the graph's initial state, builds `configurable`, resolves the
step budget from the document, meters the run, and folds the compile findings
together with the run's own health. That is the ceremony §3 has to reproduce by
hand, which is the honest cost of streaming today.

Everything about `RunResult` — all seven attributes, the `.warnings` /
`.failures` split, `.failed_nodes` — is in
[adoption.md, *What `.ask()` gives you back*](adoption.md#what-ask-gives-you-back).
It is not repeated here.

## 3. The same thing, streamed

`ask()` is blocking on purpose. To stream you drop to `.graph`, which is a
plain compiled LangGraph object — `.astream_events()` is right there. The one
thing no page showed is what to seed it with and what to do with the events.

<!-- executed verbatim by backend/tests/test_wiring_page_streams.py -->

```python
from typing import Any, AsyncIterator


async def stream_answer(
    workflow: Any,
    question: str,
    *,
    thread_id: str,
    user_email: str = "",
    session_id: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Yield one dict per thing worth telling a frontend."""
    # A node's LangGraph name is its document id, and nothing in the event
    # itself says which names are nodes — so ask the document.
    node_ids = {n["id"] for n in workflow.document.get("nodes", [])}
    initial = {"question": question, "attempts": 0, "decisions": {}, "outputs": {}}
    config = {
        "recursion_limit": 50,
        "configurable": {
            "thread_id": thread_id,
            "user_email": user_email,
            "session_id": session_id,
            "workflow_slug": workflow.slug,
        },
    }

    async for event in workflow.graph.astream_events(initial, config, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            text = getattr(event["data"]["chunk"], "content", "")
            if text:
                yield {"type": "token", "text": text}

        elif kind == "on_chain_start" and event.get("name") in node_ids:
            yield {"type": "node", "node": event["name"]}

        elif kind == "on_chain_end" and event.get("name") == "LangGraph":
            final = event["data"]["output"]
            yield {
                "type": "answer",
                "answer": final.get("answer") or "",
                "decisions": final.get("decisions") or {},
                "outputs": final.get("outputs") or {},
            }
```

Three details that are the whole reason this is not obvious:

- **`version="v2"` is not optional.** `astream_events` has two event schemas
  and the shapes above are v2's.
- **`name == "LangGraph"` is the root graph's own `on_chain_end`**, and it is
  the only event carrying the finished state. Every node emits an
  `on_chain_end` of its own under its node id, so matching on the event kind
  alone gives you one "answer" frame per node.
- **A node's LangGraph name is its document id.** That is why `node_ids` is
  built from `workflow.document` — the event carries a name and no way to tell
  a node from a middleware step or a model call.

Wiring that into an SSE endpoint is your framework's job and is three lines in
any of them — a `text/event-stream` response whose body is
`f"data: {json.dumps(frame)}\n\n"` for each frame. The browser half is
[`docs/examples/minimal-client.html`](examples/minimal-client.html), which is
written against our server's framing; if you frame your own, frame it the same
way and that client works unchanged.

### What you give up by streaming, and how to get each back

`ask()` does four things the loop above does not. None is unrecoverable, and
all four are silent if you do not know to ask.

| Lost | How to get it back |
| --- | --- |
| **The step budget from the document** | `resolve_step_budget(None, workflow.document)` from `openstategraph.step_budget` — the hardcoded `50` above ignores `settings.recursionLimit`, which the editor can set |
| **Token accounting** | wrap the loop in `langchain_core.callbacks.get_usage_metadata_callback()` and read `usage.usage_metadata` *inside* the block — the manager clears it on exit |
| **Run health** — a node that produced nothing, a grader that ran out of attempts | `run_health_from_state(final)` from `openstategraph.compile.workflow_compiler`; `.failures` is the gate-able half |
| **The compile findings** | `workflow.warnings` / `workflow.failure_warnings`, already on the object before the run |

`run_health_from_state` is a **tier 2, provisional** symbol
([stability.md](stability.md)) — importable and documented, and it may change
in a minor release with a changelog note. The other three are tier 1.

### What is *not* lost

Streaming does not cost you identity, memory, checkpointing or mounts. The
config in §3 carries the same four keys `ask()` builds, and a mounted child
receives them untouched — see §4.

### The initial state, and an honest note about it

`{"question", "attempts": 0, "decisions": {}, "outputs": {}}` is what `ask()`
seeds, and copying it is the safe thing to do. **`question` is the only key
that is load-bearing today**: every reader of the other three defaults
(`state.get("attempts", 0)`), and the grader budget has since moved to its own
per-grader counter. Seed them anyway — the cost is three dict literals, the
alternative depends on a default that is not part of any contract, and a
document with two writers to one key is exactly the case those reducers exist
for.

## 4. Identity — one table, both shapes

Four keys, all of them under `configurable`, all of them spelled the same
whichever door a run came through.

| Key | What it scopes | Set it by, hosting our server | Set it by, embedding |
| --- | --- | --- | --- |
| `thread_id` | the **checkpointer** — conversation continuity, and what a `human.approval` resume addresses | `threadId` on the run request | `ask(thread_id=…)`, or `configurable` |
| `user_email` | **long-term user memory**, namespace `("memories", <email>)` | **you may not send it** — the server determines it, and a request that carries it is a 422 | `ask(user_email=…)`, or `configurable`. Here *you are* the server |
| `session_id` | thread listing and filtering. **No runtime behaviour** | `sessionId` on the run request | `ask(session_id=…)`, or `configurable` |
| `workflow_slug` | **workflow memory**, namespace `("workflow-memory", <slug>)`, and the provenance stamp on an app-scope deposit | sent with the run | **needs no argument** — `ask()` takes it from the package, and the §3 loop takes it from `workflow.slug` |

The asymmetry on `user_email` is deliberate and is the only one: over HTTP the
identity of the person is the server's to establish, so accepting it from a
client would let any client claim to be anyone. In the embedded shape the
server is your process, so it is yours to supply — and supplying it is what
turns per-person memory on.

**Omitting `user_email` does not fall back to a shared namespace.** User-scoped
memory simply does not bind, and `save_memory(scope="user")` says so. That is a
correction of earlier behaviour, where every unidentified person shared one
namespace and could read each other's remembered facts.

### Across a mount

A workflow mounted inside another gets the parent's `configurable` with
**exactly one key overridden**: `workflow_slug` becomes the child's own, so the
child's workflow memory belongs to the child. `thread_id`, `user_email` and
`session_id` cross untouched — the person and the conversation are the same on
both sides of a mount. You do nothing to make this happen.

## 5. Memory, which is the same question asked twice

"How do I pass the username" and "how is memory scoped" have one answer:
**`user_email` is the namespace.** Four kinds, and the words matter because two
of them were mislabelled here for a while:

| Kind | What it is | Where it lives | You set it up by |
| --- | --- | --- | --- |
| **Short-term** (this project's tables call it *context*) | the conversation — thread history, a paused approval | the **checkpointer**, one sqlite file under the workflows root | nothing. Durable by default. `OPENSTATEGRAPH_CHECKPOINT_PATH` moves it, `=memory` opts out loudly; a package can claim its own file with `settings.checkpointer: "sqlite"`; or pass `load_workflow(…, checkpointer=…)` |
| **Semantic** — long-term *facts* | what to remember about a person, a workflow, or the app | a **Store**, namespaced `("memories", <user_email>)`, `("workflow-memory", <slug>)`, `("app-memory",)` | nothing. Durable by default, injected at compile. `OPENSTATEGRAPH_MEMORY_PATH` moves it or opts out; or pass `load_workflow(…, store=…)` |
| **Episodic** — past runs replayed as examples | **absent, deliberately** | — | nothing to set up. We hold the raw material and no mechanism that turns a past run into a prompt-time example; building one is a runtime concern, and we are a compiler |
| **Procedural** — instructions | skills, and Store-held instructions | the middleware slot table, authored in git | drawing a skill onto an agent |

**`thread_id` and `session_id` never appear in a Store namespace.** They scope
the checkpointer and the thread listing respectively, and nothing else.

The two memory tools (`save_memory`, `search_memory`) bind to **any** agent in
**any** workflow with zero per-workflow code — they reach the running graph's
store through LangGraph's `get_store()`. There is nothing per-workflow to
write; there is only an identity to pass, which is §4.

The argument behind all of this — the spine rule, the sharing matrix, why a
mounted workflow's memory belongs to the class and not the instance, the
durability and retention model, and the antipatterns each pinned by a test —
is [`decisions/memory-architecture.md`](decisions/memory-architecture.md). This
section is the consumer's half only.

## 6. Things that are true today and will not stay true silently

- **`RunResult.usage` and `.total_tokens` are library-and-CLI only.** The HTTP
  and MCP doors do not carry them yet. `.total_tokens` is `None` when nothing
  reported — never `0`, because a run nobody metered did not cost nothing.
- **There is no zero-dependency pure-LangGraph export.** The wiring on this
  page is what replaces that promise rather than a placeholder for it; see
  [export and portability](export-and-portability.md). `openstategraph export
  plugin <package>` produces a bundle whose README names its own install line
  and what did not travel.
- **`recursion_limit` counts supersteps, not iterations.** One lap of a loop
  that fans out costs several, so a number chosen as "max attempts" is several
  times too small. It is the document's `settings.recursionLimit`, settable in
  the editor.
- **Publish is a lifecycle action.** It neither saves nor validates; it gates
  who sees a workflow in the chat app. It has no bearing on either shape on
  this page — an embedded `load_workflow()` reads the package on disk whether
  or not it was ever published.
