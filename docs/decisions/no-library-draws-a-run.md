# No library draws a run — and the protocol that names the events is worth borrowing from anyway

**Status: in force from 2026-08-29.** Resolves `memory-and-replay` ticket 49.
Survey conducted 2026-08-29; the AG-UI reading is dated below because a
protocol's event list moves and this document's claims should be re-checkable
against a date.

## The question, and why it was asked in this order

The instruction was about **method**, not about a shopping list: *look first
for an out-of-the-box, well-maintained, free library; only then build.* The
thing being built is a run timeline you can play — a lane per concurrent step,
a real time axis, a scrubber, and the message re-appearing at the cadence it
actually arrived.

The decisive question for every candidate turned out not to be features,
maintenance or licence. It is **what shape of input the thing consumes.** A
run here is a stream of *domain* events — this node started, this chunk
arrived, this tool was asked for, this grader said revise. Almost every mature
"replay" or "timeline" package consumes something else, and a library that
consumes the wrong shape is not a component you configure, it is an adapter you
write and then maintain forever.

## Build. Here is what was rejected and why

### Wrong shape of input

| Candidate | What it actually renders | Why it loses |
| --- | --- | --- |
| **rrweb** (MIT, maintained under Sentry) | **DOM mutations** — it replays the *browser*, from a full initial snapshot plus deltas | Wrong shape twice. It can only replay what was on screen, so a step nobody scrolled to never happened; and a full-DOM recorder captures the user's entire workflow document as a blob, acquiring a storage and privacy problem for free |
| **Perfetto UI** (Apache-2.0) | spans on a timeline, backed by a WASM trace processor | Right *look*, wrong input, wrong cost. Self-hosting ships the trace processor beside our wheel; embedding the hosted build shows viewers a third-party consent prompt, which is the never-send-a-user's-graph rule with extra steps |
| **Jaeger UI** (Apache-2.0) | OTLP spans, served by a Jaeger backend | Adding a *service* to draw a picture. Spans carry start plus duration; they cannot carry chunk cadence, which is the half the owner asked for |
| **Langfuse** (MIT core), **Arize Phoenix** (Elastic License 2.0 — source-available, not OSI) | whole self-hostable observability applications with their own datastores | Not components. Neither publishes an embeddable trace-view package. Phoenix's licence is a question we would be answering on behalf of everyone who installs our wheel |
| **LangSmith trace view** | exactly the right picture | **Disqualified by rule, not configured off.** `CLAUDE.md`: never send a user's graph to a third party |
| **@xyflow** | a node graph | Not a timeline; `core/` may import neither React nor JointJS; and we already own a canvas |
| **react-chrono** (MIT) | a presentational *story* timeline with a slideshow | No lanes, no real time axis, no scrubber over measured offsets. Content, not telemetry |
| **assistant-ui** (MIT, maintained) | a **chat** runtime and message list | Adopting it means rewriting the Ask panel and our SSE contract to acquire a chat we already have, and it draws no timeline |

### The one honest candidate, and why it still loses

**vis-timeline** (dual Apache-2.0/MIT, maintained) is genuinely the right
shape: items and ranges on a real time axis, with **groups** — lanes, which is
what `memory-and-replay` 50 needs — and zoom.

Against it:

- It draws a **Gantt, not a playback.** No transport, no scrubber, no
  playhead. The part the owner actually asked for is the part it does not have.
- It is imperative DOM with its own stylesheet, and `design/` owns tokens and
  primitives. Every visual decision becomes an override.
- **This exact trade was already refused, in writing, in this tree.**
  `src/view/ask/RunTimeline.tsx`'s header says so: no chart library, several
  hundred kilobytes to draw a rectangle, and its own colours arriving in a
  design system that already has some. The twelve runtime dependencies in
  `package.json` are a deliberate number.
- The thing it would replace is a small amount of **pure, framework-free,
  unit-tested folding logic** (`src/view/ask/timeline.ts`) plus a thin
  renderer. Swapping tested logic for a dependency *and* an adapter is a larger
  diff, not a smaller one.

### So: build, and the build is small because most of it exists

`timeline.ts` already folds frames into bars with rules for internal frames,
namespace lanes and revise-loop visits. `traceTree.tsx` already nests machinery
under the node that owned it. `pastRunView.ts` already turns a stored run into
lines. Nothing in the survey replaces any of that.

What is genuinely new is two things, and neither is a library's job: a
**transport** (play, pause, scrub, speed) over a list of events, and a **lane
model** for concurrency. Both are small, both are pure, and both belong in
`core/`, where they can be tested without a DOM — which is where the existing
fold already is.

## The part that changed something: AG-UI

**AG-UI** ([docs.ag-ui.com](https://docs.ag-ui.com), MIT) is not a dependency
question. It is a **vocabulary** question — an event-based protocol for exactly
our seam, agent to frontend over SSE, with a published event enum. Read
2026-08-29 from `docs.ag-ui.com/concepts/events` and the JS and Python core SDK
event pages.

It is not being adopted. `src/core/runtime/RuntimeClient.ts` is a hand-written
client pinned by a drift test, and `docs/decisions/typescript-runtime-types.md`
already records why a generator was refused; nothing here reopens that. The
question was narrower and had a deadline: **does a protocol designed for this
problem name an event we do not emit** — *before* tickets 46 and 47 freeze a
shape into `docs/openapi.json`?

The answer is yes, four times.

### Their events beside ours

Ours is the seven-name vocabulary in `FRAME_FIELDS`
(`backend/openstategraph/api/streaming.py`) and `docs/api.md` § *The event
streams*.

| AG-UI event | Ours | Reading |
| --- | --- | --- |
| `RUN_STARTED` (`threadId`, `runId`, `parentRunId`) | — | **Missing.** We emit nothing when a run begins; `threadId` first reaches the client on a *terminal* frame. A reader who disconnects mid-run never learns the id of the thread they were watching |
| `RUN_FINISHED` (`threadId`, `runId`, `result`, `usage`) | `done` | Synonym — **except `usage`.** Ours carries no run-level cost |
| `RUN_ERROR` (`message`, `code`, `usage`) | `error` (`threadId`, `detail`) | Synonym. They add a machine-readable `code` and, again, the cost of the failed run |
| `STEP_STARTED` (`stepName`) | — | **Missing**, and independently found by `memory-and-replay` 48 reading LangGraph's `tasks` stream mode. Two sources, one gap |
| `STEP_FINISHED` | `update` | Synonym. Ours is far richer — `namespace`, `taskId`, `internal`, `activeNode`, `path`, `pathSlugs`, `output` |
| `TEXT_MESSAGE_START` / `TEXT_MESSAGE_END` (`messageId`, `role`) | — | **Missing.** Our `token` frames stream with no message boundary; a consumer infers one from a change of `node`. That inference is exactly what 47's chunk-coalescing would otherwise have to invent |
| `TEXT_MESSAGE_CONTENT` (`messageId`, `delta`) | `token`, `block: "text"` | Synonym. Theirs keys by `messageId`; ours by `node` + `namespace` |
| `TEXT_MESSAGE_CHUNK` | — | Convenience sugar for start-content-end. Not applicable |
| `TOOL_CALL_START` (`toolCallId`, `toolCallName`) | `spawn`, but only for four tools | **Near-miss, and the near part is the problem.** `_SPAWNING_TOOLS` produces a `spawn` for `fanout` / `subagent` / `async` / `subgraph` only. An ordinary tool — a SQL query, an HTTP call — gets **no invocation frame at all**. Its *output* arrives later as `token` with `kind: "tool"`. So we have a tool-result vocabulary and no tool-invocation vocabulary, which is precisely the shape of a forty-second stall nothing on the wire explains |
| `TOOL_CALL_ARGS` (`delta`) | — | Missing. Deliberate-adjacent: `spawn.instruction` carries a snippet for the four spawning tools. Streaming arguments as deltas is a feature we have not wanted |
| `TOOL_CALL_END` | — | Missing, and follows `TOOL_CALL_START` |
| `TOOL_CALL_RESULT` (`toolCallId`, `content`) | `token` with `kind: "tool"`, `tool: {name, callId}` | Half-synonym. Ours is a *chunk of text*, theirs is a *result object*. Ours carries the call id, so the join exists |
| `STATE_SNAPSHOT` | `done.outputs` | Terminal only |
| `STATE_DELTA` (RFC 6902 JSON Patch) | `update.output` | Synonym at the job, different at the encoding. Theirs patches one shared state document; ours is one node's contribution, which is the shape LangGraph reducers actually produce |
| `MESSAGES_SNAPSHOT` | `GET /api/threads/{id}` | We do it out of band, on purpose |
| `ACTIVITY_SNAPSHOT` / `ACTIVITY_DELTA` (`activityType`, `content`, `replace`) | `progress` | **Synonym, and a good one** — "what the agent is doing right now, while it works". Theirs distinguishes replace-me from append-to-me; ours is append-only lines with `current` / `total` |
| `REASONING_*` — seven events | `token` with `block: "reasoning"` | Synonym. One field of ours against a sub-family of theirs; the extra granularity buys nothing we surface |
| `REASONING_ENCRYPTED_VALUE` | — | Missing, and correctly so *today*: it exists for providers returning opaque reasoning blobs that must be echoed back on the next turn. If we ever carry one, this is the name |
| `SUBAGENT_STARTED` (`subagentRunId`, `name`, `description`) | `spawn` (`kind`, `parent`, `label`, `instruction`, `taskId`) | **Synonym, field for field.** Reassuring: an independent protocol arrived at the same five things |
| `SUBAGENT_FINISHED` / `SUBAGENT_ERROR` (`subagentRunId`, `result`, `outcome`) | — | **Missing, and this is the expensive one.** We announce a spawn and never announce its close. A bar on a timeline needs both ends; today the only account of what a child produced is terminal, in `done.nested` and `done.attempts` |
| `RAW`, `CUSTOM` | — | Escape hatches. We have none, by temperament: every new thing here is a new frame kind or a new field, gated by a contract test. That is a cost we choose |

### What we have that they do not

Three, and each is a thing this installation knows rather than a hole in theirs.

- **`interrupt` as a terminal frame.** AG-UI has no pause. Its human-in-the-loop
  story is a frontend-executed tool: the run *finishes*, the browser does
  something, a new run starts. Ours pauses a real LangGraph checkpoint and
  resumes into the same thread, which is why `interrupt` is terminal on the
  wire and not on the graph. A borrowed vocabulary must not flatten that.
- **The audience boundary** — `withheld`, `detail: null`, `developer` only on a
  developer run. AG-UI has no notion that two readers of the same run are owed
  different frames. Ours is load-bearing (`api/audience.py`) and there is
  nothing to borrow.
- **`interruptible`, and `path` / `pathSlugs` / `namespace`.** AG-UI's
  `parentRunId` / `subagentRunId` describe a *run* tree. Ours describe a
  *document* tree — where the node sits on every canvas, across mounts. Their
  fields cannot express a mount path, and nothing in their enum answers "would
  Stop cancel this, or merely walk away from it".

## The decisions

1. **Build the timeline. Do not take a dependency.** Recorded above; the next
   person asking "is there a library for this?" should read this section rather
   than repeat the survey.
2. **Do not adopt AG-UI.** Not as a dependency, not as a wire format. Our seven
   frames carry things its twenty-nine cannot, and the seam is already pinned by
   `docs/openapi.json` plus `src/core/runtime/contractDrift.test.ts`.
3. **Borrow the vocabulary where it is free**, and name new things what AG-UI
   names them, for the reason this repository has now learned three times —
   `loop`, `template`, and `taskId` caught mid-flight by ticket 48. A word that
   already means something to a reader is not ours to redefine.
4. **The four genuine gaps are filed, not built here** — see the tickets below.

### For ticket 46, which is open right now

`46` is adding a clock field to every frame. Three findings apply to it
directly, and one of them is a naming decision that costs nothing today and a
contract change later:

- AG-UI puts `timestamp` on **`BaseEvent`** — one optional field on every event
  type, not a per-event-type addition. That is the same move 46 is making, and
  it is a point in its favour.
- **There is no sequence number anywhere in AG-UI.** Ordering is stream order.
  A protocol designed for this problem looked at the question and declined to
  add one. If 46 adds both a stamp and a sequence, it should say why it is
  buying something AG-UI decided against.
- Their `timestamp` is **absolute** (epoch integer). 46 is weighing a
  relative offset-from-run-start, which has real arguments behind it. If we go
  relative, **the field must not be called `timestamp`** — a reader arriving
  from any AG-UI client would read a relative number as an absolute one and be
  wrong by decades. Call it `offsetMs` and the ambiguity cannot arise.

## The tickets this produced

Filed on the `memory-and-replay` map rather than built here.

- **53 — a run says nothing when it starts.** `RUN_STARTED`. `threadId` first
  reaches a client on a terminal frame.
- **54 — a spawn is announced and never closed.** `SUBAGENT_FINISHED` /
  `SUBAGENT_ERROR`. Blocks 50, which needs both ends of a bar.
- **55 — an ordinary tool call has no invocation frame.** `TOOL_CALL_START`.
  Only the four spawning tools announce themselves.
- **56 — what the run cost is nowhere on the wire.** `RUN_FINISHED.usage` and
  `RUN_ERROR.usage`. Per-token `usage` exists and is developer-only; no total
  survives, and a failed run's cost is lost entirely.

`STEP_STARTED` is deliberately **not** a fifth ticket: `memory-and-replay` 48
already owns it, from the other direction — LangGraph's `tasks` stream mode
emits task start and finish events and this installation does not subscribe. Two
independent readings landing on one gap is the strongest signal in this
document, and it should be resolved once.
