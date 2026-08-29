# A frame says when it happened

`memory-and-replay` 46, resolved 2026-08-29. Blocks 52 (the play button); read
by 47 (keeping the chunks) and 48 (the `tasks` stream mode), which is why the
contract cost at the end is priced once here instead of three times.

## The gap

`api/streaming.py` emitted seven frame kinds and not one of them carried a time
or a sequence number. `RunRecord.at` was the only clock in the run seam — one
stamp for a whole turn — so every duration the editor showed was measured in
the browser, on arrival, by `ExecutionEngine`'s `performance.now()`. That
measurement lives in the tab that was watching: reload, and the run's shape
survives in the checkpointer while its cadence does not.

Playback is a function of cadence. Without stamps a play button has two
options, and both are dishonest: tick uniformly, which a viewer reads as
duration, or do not offer one.

## The five decisions

### 1. Server clock, and the surface says which it is

**Decided: the stamp is minted where the frame is built, in `_sse`.** It
measures the backend producing the frame.

The two clocks answer different questions and neither substitutes for the
other. *"How long did the run take"* is a question about the server; *"how long
did I wait"* is a question about the network and the tab, and a stalled reader
is invisible to the first and dominant in the second. A profiler wants the
server's. So the browser's arrival clock is **not removed** — `ExecutionEngine`
still measures it and `timeline.ts` still says in its own header that its bars
are arrival gaps. What changes is that a surface now *can* claim the other one,
and `RunFrameStamp`'s doc comment is where the difference is written down so a
future consumer cannot mix them by accident.

### 2. Monotonic cadence, wall anchor — the dilemma dissolves once they are separated

**Decided: `elapsedMs` from `time.monotonic()`; no wall stamp on the wire.**

A run crossing an NTP correction must not appear to run backwards, which rules
out a wall clock for the *cadence*. But `PastRunStep` already chose ISO wall
time to agree with the checkpoints, and a second, disagreeing vocabulary on the
wire would be worse than no clock at all.

Both are satisfied by not restating anything: the frames carry a monotonic
offset, and the wall anchor a reader needs to line a run up against a log file
is the run record's own ISO stamp, written by the same `run_turn` that wraps
the stream. Nothing on the wire can disagree with the checkpoints because
nothing on the wire repeats them.

### 3. Relative

**Decided: an offset from the stream's own opening.**

It is smaller, it is exactly what a scrubber consumes, and it says nothing
about *when* the run happened — so a recorded stream can be replayed, shared or
attached to a bug report without disclosing that. The absolute correlation an
operator wants for a log line is the run record, per decision 2.

The cost, stated so nobody rediscovers it: two frames from two different runs
cannot be interleaved on one axis from the wire alone. They should not be — a
timeline is per run — and a caller that genuinely wants it has the two run
records to anchor with.

### 4. `seq` too, and it was the cheaper half

**Decided: yes, both.** They are not the same question. Two frames can share a
millisecond, so a clock does not settle order; and a dense counter from `0`
makes a *dropped* frame visible as a gap, which no timestamp can do.

Deciding it here rather than in 52 is the point of the ticket: adding it later
would be a second pass over the same five files.

### 5. The contract cost, priced once

A field on every frame is a **five-file change, by design**, and this is the
walkthrough so 47 and 48 do not each re-derive it:

| File | What it needs | Automatic? |
| --- | --- | --- |
| `api/streaming.py` | the field in `_PAYLOAD_FIELDS` (one frame) or in `FRAME_CLOCK_FIELDS` (every frame) | — |
| `docs/api.md` | the field named in that frame's payload cell | no — `test_the_frame_fields_are_published` fails until it is |
| `docs/openapi.json` | `python3 scripts/generate_openapi.py` | yes, but committing it is not |
| `src/core/runtime/RuntimeClient.ts` | the field actually read off the payload | no — `contractDrift.test.ts` fails until it is |
| `src/core/runtime/contractDrift.test.ts` | nothing | yes — it reads the published artifact |

**The marginal cost of the clock to a future ticket is zero, and that is the
part worth carrying forward.** `_sse` mints it and `FRAME_FIELDS` composes it
in:

```python
FRAME_FIELDS = {
    name: fields + FRAME_CLOCK_FIELDS for name, fields in _PAYLOAD_FIELDS.items()
}
```

So a **new frame kind** — 48 may want one — is dated the moment it is
declared, and pays only for its own fields. A **new field on an existing
frame** — 47 wants several — pays the table above and nothing extra.

## The audience boundary

A cadence is not a disclosure, and the implementation keeps it that way: `seq`
and `elapsedMs` are minted in `_sse`, which knows nothing about the audience,
and are byte-identical for a customer and a developer. There is nothing in
either field but a count and an offset — no host clock, no absolute time, no
node identity, no server load. `test_a_frame_says_when_it_happened.py` pins
both halves: that a customer's frames are numbered exactly as a developer's,
and that no value in either is large enough to be a wall clock in disguise.

## What was deliberately not done

- **`timeline.ts` still measures arrival.** Switching its bars to the server
  clock is a change to what the UI *claims*, and belongs with the play button
  (52) that will make the claim visible. The wire now supports it; the header
  comment there is still accurate about what it does today.
- **The catalogue stream (`GET /api/events`) is not stamped.** It opens no
  frame clock. It is not a run, its frames are not run frames, and it publishes
  no field list to widen — the same reason `test_the_frame_fields_are_published`
  asserts it publishes none.
