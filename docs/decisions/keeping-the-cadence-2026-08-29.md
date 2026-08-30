# Keeping the cadence, so a replay does not have to invent one

`memory-and-replay` 47, resolved 2026-08-29. Blocks 52 (the play button), which
inherits from here what a replay may and may not claim. Reads
`docs/decisions/a-frame-says-when-2026-08-29.md` (46), which priced the wire
contract once and made the clock this record is built on free.

## The gap

Of the seven SSE frame kinds, `token` and `progress` are the two that arrive
**while a node is still working** — the only two that can explain a
forty-second stall — and both survived nowhere. The settled message reached the
checkpoint's `messages` channel; the chunks, their order, their `block` and
their `withheld` went with the socket.

So a play button built on the old store had two options and both were
dishonest: re-type a stored paragraph at a uniform rate, which a viewer reads
as duration, or do not offer one. The owner's sentence — *"see the message
appear as it hits the chunk"* — is the acceptance test, and nothing in the
store could meet it.

## The measurement, which is the whole decision

The ticket named three grains and assumed a tradeoff between fidelity and disk:

- **(a)** every chunk with its offset — perfect cadence, most disk;
- **(b)** coalesced bursts — one row per contiguous burst, cadence "to within a
  frame", far less disk;
- **(c)** no chunks — the play button plays steps, not characters.

**Priced against six real `ollama:gpt-oss:120b-cloud` runs** of
`.scratch/stress-2026-08-29/workflows/stress-review` (router, `Send` fan-out,
grader loop, nested mounts) and a private 28-node package, in both
audiences, each package twice. Marginal bytes per run, measured by writing 200
runs' worth of rows into one sqlite file and dividing after a `VACUUM`:

| run | chunks | (a) per-chunk rows | (b) burst rows, span only | **(b+) burst rows, every offset** |
| --- | --- | --- | --- | --- |
| stress-review | 242 | 242 rows, 26.0 KiB | 29 rows, 5.9 KiB | **17 rows, 4.9 KiB** |
| 28-node package | 515 | 515 rows, 53.9 KiB | 15 rows, 4.3 KiB | **10 rows, 4.7 KiB** |
| 28-node package | 1014 | 1014 rows, 107.0 KiB | 18 rows, 8.3 KiB | **8 rows, 8.2 KiB** |

**The tradeoff does not exist.** What a per-chunk row pays for is not the
cadence — it is repeating one node's id, namespace, block and kind 242 to 1014
times. Pay the identity once per burst and carry every chunk's own offset and
length as a delta-varint blob, and the same information costs **5–13× less than
(a)** and, in two of the three runs, **less than the lossy (b)**.

### And (b) as the ticket described it is not good enough anyway

The ticket's (b) — a first offset, a last offset and a character count — asks a
replay to interpolate. Measured on the same runs, inside a single burst:

| | value |
| --- | --- |
| inter-chunk gap | p50 **1–8 ms**, p90 12–22 ms, max **555 ms** |
| error of interpolating across a burst | p50 22 ms, p90 193 ms, **p99 469 ms**, max 545 ms |

Half a second of stall, rendered as smooth typing. A pause threshold that
breaks a burst on a gap bounds this — at 50 ms it costs 23 rows/run for a max
error of 115 ms — but it never reaches zero, and it costs *more* rows than
keeping the offsets outright. So the interpolation was never buying anything.

**Decided: grain (b) at grain (a)'s fidelity.** One row per contiguous burst of
one node's one block, carrying every chunk's own measured offset.
`RunBurst.replay()` returns `[(elapsedMs, text), …]` exactly as it arrived.

### What it costs against what this machine already writes

`checkpoints.sqlite` on this checkout holds 479 conversations in 137 MB —
**279 KiB per conversation**, written by LangGraph on every run, without
complaint. The cadence adds **5–8 KiB per run: 2–3% of that.** Grain (a) would
have been 10–38%.

So this does **not** make *nothing sweeps* untenable, and that was the thing to
check rather than assume. The store stays local, unbounded and unswept —
*conversations are gold* — and `openstategraph runs export` stays the answer to
a large file. The one bound added is on **memory during a run**, not on
anything written: `BURST_CAP` is 400 against a measured 6–30 bursts per real
run, reached only by a graph cycling, and the last burst kept says `capped` so
a reader can tell *the recording ends here* from *the run ends here*.

## Where the rows go

**Decided: a second table in `runs.sqlite`, written in the same transaction.**

`run_sinks.py` argues hard that there is one store, and it is right; two tables
in one file is a different claim from two stores. A burst is not a run — there
are 6 to 30 of them per turn — so it cannot be a column, and a separate file
would mean two things to export, two to delete, and a `runs export` that told
half the truth. The checkpointer was rejected outright: it is LangGraph's
schema, not ours, and the saver is swappable.

**Ticket 37 priced a frame table once and concluded it "turned out not to be
needed". That is reversed here, out loud rather than quietly.** 37 built a
profiler, which reads *finished* state, and finished state genuinely holds
everything a profiler asks. Playback asks for cadence, which no finished state
holds at any grain.

**No column is added to `runs`.** The join key is `runs.rowid`, read back from
the insert in the same transaction — exact, and free.

> The reason originally given here was *"this module has no migration machinery
> and `CREATE TABLE IF NOT EXISTS` would leave every existing store unable to
> take a row"*. That was right about this decision and was the whole statement
> of the problem for the next one, which
> `the-boundary-nobody-checked/07` then found: the day either column list gained
> an entry, an installation that had run before lost every row from then on
> behind one WARNING, and `runs list` on it answered with nothing rather than
> with the rows still in the file. `_reconcile` in `run_sinks.py` is now the
> machinery — `PRAGMA table_info` against the one declaration, `ALTER TABLE ADD
> COLUMN` for what is missing, nothing removed — and its docstring names the
> four shapes of change it deliberately does not survive. The decision above is
> unchanged; only its reason has been superseded.

**And the cadence reaches a sink as a field on `RunRecord`, not as a method on
`IRunSink`.** That is this module's own declared asymmetry being used rather
than bent: the Protocol is two members and closed at birth, because a member
added to a `runtime_checkable` Protocol un-satisfies every sink anybody
shipped, in their install rather than ours. A sink written against today's
Protocol receives the cadence with nothing changed, and reads it or ignores it.

## What is deliberately *not* kept, and the argument met head-on

`progress.py:91` says, in as many words, that everything a progress line could
grow — *"timestamps, levels, structured fields"* — **belongs to tracing
instead**. The ticket is right that this correct decision about a progress line
has been standing in for a decision about whether this product has a trace.

**Agreed with, and it stays.** A `progress` frame is a *narration* — a sentence
a node writes for a human watching, `Read 40 of 100`. Storing it would make
this table a log, and a log is the thing `progress.py` refuses to become for
the good reason that it would then need levels, structured fields and a
retention policy, and would be a worse trace than a real one. What a replay
needs from a stall is *when nothing arrived*, and the burst rows already say
that exactly: the gap between one burst's `last_ms` and the next's `first_ms`
is the stall, measured, with the node named on both sides.

`spawn`, `update`'s `taskId`/`internal`/`path`, and `done`'s `mermaid`/
`nested`/`outputs` are also still not kept. They are the *shape* of the run,
which the checkpointer holds and `api/threads.py` already reads back; this
ticket is about the *cadence*, which nothing held. 48's finding is the honest
route for the shape half — `stream_mode="tasks"` emits a per-task start and
finish with a runtime id — and it stays 48's.

## Privacy: inherited, not re-decided

A chunk log is the most complete copy of a customer's data this system holds.
It gets no new rule; it gets `RunRecord.answer`'s, which was already argued:
**the local store keeps it, and a sink that carries rows off the machine writes
a count instead.** `JsonlRunSink` — a file that gets committed, emailed and
pasted into issues — writes `bursts: 21` and no text, exactly as it writes
`answer_chars` and no answer. No network exporter ships, absent rather than
disabled, so there is nowhere else for it to go.

There is no new opt-out either, and that is a decision: `OPENSTATEGRAPH_RUN_STORE_PATH=memory`
already switches the whole local store off, and the answer text is already in
the run row, so a switch for the cadence alone would protect nothing that is
not already exposed. A second convention for one file would be a second thing
to explain.

## The audience boundary, held structurally

`38` found a replay door letting customer-audience content cross once. It
cannot recur here, and the reason is placement rather than a filter somebody
has to maintain: **the recorder reads the wire.** `_stream_run` hands it each
frame it is about to yield, and `_token_frame` has already emptied a withheld
frame's content before the frame exists. On a customer's stream there is no
withheld text to record; on a developer's there are no withheld frames at all.
The recorder never holds the bytes.

The flag is still stored, for the reason the frame keeps it: a withheld burst
still says a node was working, so a customer's replay shows the stall instead
of a hole. And each burst carries the **audience its run was streamed to**,
because a developer run's cadence carries developer content and a reader
serving a customer has to be able to refuse it.

## Async-first: what the token loop pays

A chunk is a list append and an integer addition. **The disk is touched once,
at the end of the turn, by the sink that was already writing the run's row.**

Measured (`asyncio`, 2000 token frames per stream, median of five, against a
baseline that already runs `_frame_interruptible` on every frame):

| concurrency | recorder off | recorder on |
| --- | --- | --- |
| 1 | 15.7 µs/frame | 20.5 µs/frame |
| 8 | 4.5 µs/frame | 7.7 µs/frame |
| 32 | 3.2 µs/frame | 6.2 µs/frame |

**~3 µs of CPU per token frame**, and the cost is the `json.loads` — the frame
is parsed off the wire rather than threaded out of the fold, which is the same
choice `_frame_interruptible` makes for the same stated reason. On the largest
real run measured (1014 chunks over 40 s) that is **~5 ms, once, against 40 000**.

## What a replay may claim — the fact 52 inherits

**May:**
- that every offset in `RunBurst.replay()` is a **measurement**, taken
  server-side where the frame was built, in milliseconds from the stream
  opening;
- that a gap between two bursts is a real stall, with the node named on both
  sides of it;
- that `first_seq`/`last_seq` are the wire's own dense counter, so a gap there
  is a dropped frame.

**May not:**
- claim any absolute time. `elapsedMs` is relative by 46's decision; the wall
  anchor is the run row's `at` and nothing here restates it;
- claim to be what the **user** experienced. This is the server's clock; a
  stalled network is invisible to it and dominant in `ExecutionEngine`'s
  browser-side one. A surface showing one must not label it as the other;
- draw a run with **no** bursts as an instant. No cadence is an absence — an
  old row, a workflow of function nodes, a store from before this ticket — and
  `PastRunStep.durationMs`'s discipline applies at the level of the whole
  transport: `null`, never `0`, because a renderer must be able to tell instant
  from unknown;
- show a burst past a `capped` one. The recording ended there; the run did not.

## What is not built here, and whose it is

The **reader is Python-level only** — `read_run_bursts` beside `read_runs`.
There is no HTTP route and no viewer: that is 50 (a fan-out has no single
timeline), 51 (where a timeline lives) and 52 (the play button). This ticket
built the capture and the store, which is what those three were blocked on.

> **Superseded on 2026-08-30, in the part that is a state and not a decision**
> (`memory-and-replay` 72 and 73). There is an HTTP route —
> `GET /api/runs/recorded` and `GET /api/runs/recorded/{thread_id}` — and there
> is a viewer: the **Stored runs** popover in the top bar, which puts a stored
> recording on the run dock's own timeline. The sentence is left standing
> rather than edited because everything above it is the argument for the
> grain, and that argument is unchanged; what has moved is only who can read
> the rows. The cadence **blob** is still not published, and `60` — the answer
> re-typed at the rate it arrived — is still open.
>
> One thing the record above did not anticipate: a burst did not carry
> `activeNode`, so the store knew *when* every chunk arrived and not *whose
> work it was*. `74` added the column. Inside `create_agent` the recorded
> `node` is LangGraph's own `model` and `tools`, so eight of a real nine-burst
> `chinook-assistant` recording named no canvas node at all.
