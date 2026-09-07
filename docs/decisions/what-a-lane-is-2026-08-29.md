# What a lane is

`memory-and-replay` 50, resolved 2026-08-29. Blocked on 54 (a spawn is
announced and never closed) and reading 46 (a frame says when it happened).
Constrains 51 (where a timeline lives) and 52 (what the play button does),
which own the drawing and are not decided here.

## The lie the panel was telling

`stress-review` was run for 55.4 s against `ollama:gpt-oss:120b-cloud` and
every frame recorded (`src/view/ask/recordedFanOutRun.json`). Its supervisor
fanned out twice, and what the run itself says happened is in the
`spawn`/`settled` pairs:

```
task-1     5 060 -> 20 947        task-1-1   27 564 -> 41 376
task-2     5 060 -> 17 728        task-1-2   27 564 -> 40 122
```

Two pairs of children, each pair beginning on the *same millisecond*,
overlapping for twelve seconds, all four labelled `impact-analyst`.

What the timeline drew:

```
 7  impact-analyst  start 13 332  dur  4 396  visit 1  task-2
 8  impact-analyst  start 17 728  dur  3 219  visit 2  task-1
12  impact-analyst  start 27 564  dur 12 558  visit 3  task-1-2
13  impact-analyst  start 40 122  dur  1 254  visit 4  task-1-1
```

Four bars laid end to end in a column read top to bottom, numbered `visit
1..4` — which is that panel's badge for *a revise lap*. Two false claims at
once: that four simultaneous workers ran one after another, and that they were
one worker running four times. It also began the first of them eight seconds
after it began, and gave the longest-running child (15.9 s) the shortest bar
(3.2 s), because a span between whichever frames arrived is not a duration.

A caption cannot retract any of that, which is why `timeline.ts`'s own
admission — *"the UI must not claim otherwise"* — was never enough.

## The decisions

### 1. A lane is a spawn, keyed on `spawnId`

Four candidates live in the data and only one is the axis.

- **`taskId`** is the join *within* a lane, not the lane. 54 already settled
  that it is honest for three spawn kinds and absent for the fourth, and a
  join for three of four is not a join.
- **A checkpoint namespace** is a mount, and a mount is not a lane — §3.
- **A canvas node** is what a lane's *bars* are drawn from, not the lane: one
  `worker` node wore four concurrent children in the recorded run.
- **A spawn** is the only thing in the data that is announced, closed, and
  free to overlap its siblings. `spawnId` is minted by `SpawnWatcher`, is
  present on both halves of every pair, and is unique where the label is not.

Kinds `fanout`, `subagent` and `async` get lanes. Everything else — every
top-level step, every revise lap, every mount — stays on **the run's own
lane**, where sequence is the truth.

### 2. A lane's name is the one the run announced

From the `label` on the `spawn` frame and from nowhere else: the
orchestrator's chosen archetype for a `fanout` child, the `subagent_type` the
model asked for for the other two.

Answered against the two tickets this map already paid for:

- **39** (a lane named by the compiler): the label never passes through
  `safe_name`. It is minted where the run resolved it, so nothing is reversed
  and nothing is guessed.
- **40** (a lane called `1`): where the run has no name to give, the fallback
  is the child's own subtask id — the string that appears in `worker_results`,
  on the card's chip and in the trace. A reader can act on it. An invocation
  counter names nothing, and no counter is ever minted here.

**And a name is not an identity**, which is the half a fan-out breaks. The
lane is *keyed* on `spawnId` and *named* by the label; overlapping namesakes
carry `sibling: {index, of}` — "the 2nd of 2 `impact-analyst`s".

That is deliberately **not** `visit`. `visit` counts laps of one node and
means *sequence*; `sibling` counts children and means *simultaneity*. They had
rendered identically, which is how the recorded fan-out came out as a fourfold
revise loop. For the same reason `visit` is renumbered **within** a lane: a
lap is a lap of this lane or it is nothing.

### 3. Fan-out, mount and revise loop, told apart in the data

Three things that look identical on a chart, so the discriminator is never the
shape:

| | what says so |
| --- | --- |
| a fan-out child | a `spawn` frame with `kind: "fanout"`, minted from an entry in the orchestrator's own `subtasks` plan. Siblings arrive on one frame carrying one `elapsedMs`, so their overlap is **recorded** rather than inferred |
| a mounted workflow | a `spawn` frame with `kind: "subgraph"`, minted from a checkpoint namespace appearing for the first time. **Not a lane**: it is one node on the canvas and its parent blocks inside it, so it folds into the parent's bar exactly as `buildTimeline`'s rule 2 already folds it |
| a revise lap | **no spawn frame at all** — the same top-level node reporting again, keeping its `visit` counter and its place in the run's lane |

That also answers the ticket's collapse question without a knob. The mount
rule is about what a mount *is*, not about how deep a reader can bear to look,
so `nested-mounts` — three documents, three levels — yields one lane. The
mermaid preview opens mounts to any depth because a diagram of structure
should; a timeline of *time* should not, because the parent is waiting the
whole time and the child's bars would be the parent's bar drawn again.

### 4. Concurrency is drawn, not admitted as unknown — and only for a lane

The ticket left this open against 48, and 54 closed it instead: a child lane's
bar is a **measured** start and end, two dated frames (`spawn` and `settled`,
46's clock on both). That is a stronger claim than any bar in the run's lane
can make — those are still spans between whichever frames arrived — and the
model keeps the difference visible rather than flattening it.

**A child that never ended does not draw a bar that did.** `endMs: null`,
`durationMs: null`, `openEnded: true`, and `ending` says which kind of open it
is: `detached` for a background child still working outside this run,
`unknown` for a recording that ended owing an account, `null` for a child that
simply has not finished yet. None of them is given a number, because the run
measured none — `launch-readiness` 108's rule, one level up. `totalMs` tells a
renderer where the recording stopped, which is where an open bar should reach
and be marked.

### 5. It is a partition, not a second fold

`buildLanes` partitions `buildTimeline`'s bars; it never re-derives them.
Every bar the old fold produced lands on exactly one lane, so the two cannot
come to disagree about what ran, and the sequential fold's own tests still
describe the sequential case.

## What this does not model

**Two top-level branches running in parallel.** In the recorded run the router
opened both desks in one superstep, so the `deep` mount ran alongside the
whole supervisor branch — and neither carries a frame saying they are
concurrent *with each other*, because a branch is not a child. They stay bars
in the run's lane, span-attributed, under the caveat that lane already
carries. Filed as `memory-and-replay` 57 rather than left for a reader to
discover.

## Where it lives

`src/view/ask/timeline.ts` — pure, framework-free, no dependency added, which
is `docs/decisions/no-library-draws-a-run.md` still holding. Tested in
`src/view/ask/runLanes.test.ts` against the recorded run rather than against
frames written by hand.
