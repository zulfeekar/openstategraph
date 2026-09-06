# A branch is not a lane

`memory-and-replay` 57, resolved 2026-08-29. The sequel to
[`what-a-lane-is-2026-08-29.md`](what-a-lane-is-2026-08-29.md), which gave a
dispatched child a lane and named the case it could not take.

## The claim that had to go

50 fixed a fan-out and left a third source of concurrency in the same
recording. `stress-review`'s classifier router is a `matchMode: "all"` router —
opening more than one branch in one superstep is its whole purpose — and in the
captured run it opened both desks. What the panel drew
(`src/view/ask/recordedFanOutRun.json`, 55.4 s of `stress-review` against
`ollama:gpt-oss:120b-cloud`):

```
 3  deep    start  2 775  dur 2 285  visit 1
 4  lead    start  5 060  dur     0  visit 1
 5  deep    start  5 060  dur 8 257  visit 2
```

`lead`'s completion frame landed in the middle of the `deep` mount, so the
mount came out as two bars, the second badged `×2`. That badge means *a revise
lap*. A mount that ran once was drawn as a node that ran twice — the same
collision 50 removed for children, arriving by a different road, and worse than
a false sequence because it invents an event that never happened.

## What was already on the wire

The first question this ticket had to answer was whether the fix is a contract
change or a rendering one, because the two have very different costs. Two leads
were named, and both were checked before anything was written.

**`routes` is on the wire and is not the answer.** `launch-readiness` 175 made
it public and `api/streaming.py` publishes it — but only in the terminal `done`
frame, with no clock, keyed by route key rather than by target node. It can say
*that* a router matched two branches; it cannot say when either ran, and
mapping a route key to a bar needs the document's edges, which this fold does
not have and should not acquire. It is a fact about the decision, not about the
time.

**`stream_mode="tasks"` is the answer to the half that remains, and is not
ours to ship.** 48 established the payload against the installed LangGraph and
deliberately did not put it on the wire: a fourth mode is a new frame kind — a
Pydantic model, a regenerated `docs/openapi.json`, the hand-written mirror in
`RuntimeClient.ts` and `contractDrift.test.ts` — and 46 priced that change once
so 47 and 48 would not each re-argue it.

**What was on the wire and unread is the mount's own pair.** A mounted workflow
is announced by a `spawn` frame of kind `subgraph` and closed by a `settled`,
both dated by 46, joined by 54's `spawnId` — the *identical* pair 50 built a
child lane's bar from. `deep` carries `spawn-0: 2 775 -> 13 317`. The fold read
that pair for its *name* (rule 4) and threw the rest away, then reconstructed
the mount's time from the gaps around it. So for the mount half this was a
rendering defect, not a missing contract.

## A branch is not a lane, and that is the decision

50's lane model is the wrong shape for a branch, and saying so is the finding
rather than a shortfall.

A dispatched child is an **actor**: announced, closed, owned, with a beginning
and an end that belong to it and to nothing else. A row is what that shape
wants. A branch is a **path through this same graph** — the nodes on it are
this graph's own nodes, drawn on this canvas, belonging to this run. Giving
`deep` a row and `lead` a row would say the workflow had two actors in it,
which is a claim about the *document* rather than about the run, and it would
be made afresh for every branching classifier. It would also need a name, and
50 paid for 39 and 40 establishing that a name nobody minted is the defect —
a branch has no label on any frame, so the fallback would be a counter, which
is exactly `a lane called 1`.

So a branch stays bars in the run's lane, and what a bar owes a reader is an
honest **position**, not a row of its own.

## What shipped

`src/view/ask/timeline.ts`, pure and framework-free as before — no dependency
added, `no-library-draws-a-run.md` still holding.

- **Rule 6.** A mount is bound to its bar from its `spawn` frame until its
  `settled`, so a sibling branch reporting in the middle cannot split it; and
  the bar takes its start and length from that pair rather than from the spans
  charged to it. One bar, in the right place, at its real length.
- **`TimelineStep.measured`.** Per bar, rather than a caveat said about all of
  them at once. A mount's bar is a measured start and end; every other bar in
  the run's lane is still a span between arrivals and says so. `RunTimeline`'s
  line under the bars changes with it, because a flat *"not a measured start
  and end"* became false about part of the chart the moment rule 6 landed.
- **`TimelineStep.concurrent`.** The keys of the bars this bar's window
  overlaps. Its doc comment states the shape of the claim: two span-attributed
  bars are laid end to end by construction, so they can never be *found* to
  overlap even when they did. It is a floor on the concurrency in a run and
  never a ceiling — "these definitely overlapped", never "everything else
  definitely did not".

Before and after, on the recording:

```
before                                        after
 3  deep   start  2 775  dur 2 285  visit 1    3  deep  start  2 775  dur 10 542  measured  with lead
 4  lead   start  5 060  dur     0  visit 1    4  lead  start  5 060  dur      0            with deep
 5  deep   start  5 060  dur 8 257  visit 2
```

`audit` — a mount too, and the only thing running at 44 647 ms — is measured
and names nobody, so the flag is not a synonym for "concurrent". The four
child lanes 50 built are byte-for-byte unchanged.

## What is still missing, precisely

**A start for an ordinary node.** A branch made only of plain agent nodes
carries no pair, so its bars remain spans laid end to end and two of them can
never be found to overlap. In the recorded run that is `lead`, whose bar reads
`0 ms` because the span it would have claimed was spent inside a mount running
beside it. The bar says `measured: false`, which is the honest version of that,
and nothing here infers a start — inventing one from arrival order is the guess
46 exists to stop.

The fix is 48's `tasks` mode reaching the wire, and it is a frame-contract
change. It belongs with 53/55/56, not here.

## Where it lives

`src/view/ask/timeline.ts` (rules and fields), `src/view/ask/RunTimeline.tsx`
(`caveatFor`, the tooltip), `src/view/ask/parallelBranches.test.ts` — proved
against the captured run rather than against frames written by hand, the same
choice `runLanes.test.ts` made.
