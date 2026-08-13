# Rigid runs, a lane for the loop, and points a user can drag

Ticket: `.scratch/skills-and-legibility/tickets/09-orthogonal-routing-and-waypoints.md`
Status: adopted · 2026-08-11
Supersedes the routing half of `edge-legibility.md`; its spacing work stands.

The owner's ask: *"instead of spline would it be possible to have rigid flow
line, which user can add points and drag?"* — with a sketch showing orthogonal
segments and a **dedicated lane for the feedback/revise back-edge**.

## First, the correction

`edge-legibility.md` opened with *"the routers that can [avoid obstacles] are
in the paid tier"*, and closed by recording the remaining card crossing as that
tier's limit. **It is false**, and it had been repeated to the owner in
conversation. Against the installed package:

```
node -e "console.log(Object.keys(require('@joint/core').routers))"
→ [ 'manhattan', 'metro', 'normal', 'oneSide', 'orthogonal', 'rightAngle' ]
```

`manhattan` is the obstacle-avoiding router. `rightAngle` is purpose-built for
port-anchored orthogonal links. Both are in the free `@joint/core`.

The claim is worth this much attention because of what it *did*: it turned a
real, reproducible defect — the grader's `revise` back-edge running across two
cards — into an accepted cost, and it justified a whole document's worth of
"every lever available is therefore a *layout* lever". The correction is
recorded in place at the top of that document rather than edited away, on the
same principle that document already applies to its own earlier mislabelling.

## What was measured, and how

The rig from `edge-legibility.md`, with one refinement. That rig excluded an
intersection within 12px of an endpoint of *both* links, to stop two links
meeting at a port being counted as a crossing. Orthogonal runs merge into a
shared port further out than curves do, so the rule is now **two links that
share an endpoint are a join, never a crossing** — three tool bindings
converging on one bus is one junction, not three collisions. The rule is
applied identically to the before and after figures below.

Both graphs, `Arrange automatically`, fit to screen. Seeded demo
(`src/app/seedDemo.ts`) — the graph a fresh browser opens on, and the one that
contains the revise loop:

| seeded demo | card crossings | edge crossings |
| --- | --- | --- |
| `curve` (before) | **3** | **6** |
| `rightAngle` | 2 | 2 |
| `metro` | 5 | 2 |
| `manhattan`, router alone | **0** | 4 |
| **`manhattan` + back-edge lane (adopted)** | **0** | **2** |

`chinook-assistant`, loaded from the backend and arranged once: **0** card
crossings, **6** edge crossings — see *What is not fixed* below, which
re-measures both figures on the collapsed thirteen-node document. Arranging a
*second* time lands a different arrangement (Data Analyst moves to the bottom
rank) and scores 0 / 10. That variance is not routing: dagre is deterministic
given topology and sizes, and the sizes are what differ — a card measures
itself after React lays it out, so the first Arrange after a load runs against
heights the second one no longer sees. It is a layout matter and it predates
this change; it is recorded here because it is the reason a single number for
this graph would be misleading.

## The router: `manhattan`

**`rightAngle` was the tempting one and it is not enough.** It is designed for
exactly our situation — links anchored to ports, with `sourceDirection` /
`targetDirection` naming the side each end leaves from — and its runs are the
tidiest of the three. But it does not know about obstacles, and it shows: 2
card crossings, both of them a run drawn straight through a card that happened
to be in the way. The whole point of this ticket was the one crossing a
non-routing connector could not fix.

**`metro` is out on the brief.** It is `manhattan` with diagonal steps, and a
diagonal is the one shape the owner's sketch rules out. Measured with the same
single pinned start/end direction per end, it did not even produce diagonals:
it failed to find a route at all and fell through to its `fallbackRouter`
(`orthogonal`, a naive two-segment L with no avoidance), which crossed 5 cards.
A router that silently degrades to a worse one is worse than either.

**`manhattan` clears every card**, on both graphs, with no layout change at
all. Its arguments:

- `step: 12` — the pathfinder's grid, and a divisor of `NODE.portRowHeight`
  (24), so two runs leaving adjacent ports start two grid rows apart instead of
  snapping onto one line. `step: 6` was tried and is **worse** (2 card
  crossings): a grid that fine quadruples the search and pushes long links past
  `maximumLoops`, at which point they fall back to `orthogonal` and cut through
  cards. A finer grid is not a free improvement.
- `padding: 24` — clearance around every obstacle. Swept against 12: identical
  scores on both graphs. Kept at 24 because it is the visible gap, not because
  it changes a count.
- `maxAllowedDirectionChange: 90` — the pathfinder defaults to 45, which is
  where `metro` gets its diagonals from. 90 makes a diagonal inexpressible
  rather than merely unlikely.

**The tangent knowledge was ported, not discarded.** `edgeDecoration`'s
`linkConnector` pinned each end of a curve to the side its port actually sits
on, because once links attach to **magnets** `LinkView.sourceBBox` is the
port's 10px hit circle rather than the card — so any "which side is this
nearest" rule degenerates to "whichever way the target lies", and a run leaves
a bottom port sideways along the card's own border. That is exactly as true of
a router as of a connector, and `manhattan` expresses it directly:
`startDirections` / `endDirections`, one direction each, taken from
`resolvePortSide`. One direction and never a list, for the same reason the
tangent was pinned and not guessed — a list lets the search leave a dot
backwards to save four pixels of path length.

The connector is now `rounded` with an 8px radius: it reproduces the router's
segments verbatim and only eases the corner, so a bend still reads as a right
angle at fit-zoom without being the one-pixel spike a hairline stroke makes of
a true 90°.

### Frames are not obstacles, and `excludeTypes` cannot say so

`manhattan` builds its obstacle map from every element in the graph. It offers
`excludeTypes` — keyed on the JointJS cell *type*, which every card and every
annotation frame of ours shares. So the stock map walls off frames, and a run
passing behind a labelled region detours round a rectangle that is not there.

The classification already exists and has one owner: a node's `kind`.
`AutoLayout` reads the same field to decide what dagre may rank, and
`edge-legibility` stated the rule in as many words — *frames are not obstacles,
a frame is a background region things sit inside*. So `isPointObstacle` is
supplied from `canvas/links/flowObstacles.ts`, built from the cards only.

Two details that are load-bearing rather than incidental:

- Supplying `isPointObstacle` **replaces the stock map wholesale** — `padding`,
  `excludeEnds` and `excludeTypes` are all ignored once it is set — so the
  padding is re-applied there, and with the *same* number the router expands
  its end boxes by, or the two disagree about where a run may legally start.
- The test is **strictly** inside. The router derives its first and last route
  point *on* the boundary of a padded end box; a boundary counted as blocked
  fails its accessibility check and drops the link to the fallback — a straight
  diagonal, the exact shape this whole change exists to remove.

The rects are read from the **graph**, not the model, so a card that has grown
with its content blocks the space it actually occupies; the model is consulted
only for the one thing the graph does not know, which is card versus frame. The
list is invalidated on `change:position change:size add remove reset` — watched
on the graph rather than the model, because a card measures itself after React
lays it out and reports its height straight onto the cell.

## The back-edge gets a lane, and the router alone does not give it one

`manhattan` clears every card unaided. It does not solve the back-edge; it
relocates it. On the seeded demo the return run from `Grader.revise` to
`AI Agent.feedback` finds the only free corridor between the ranks it crosses —
the 84px band between the agent and its tool shelf — and then cuts across all
three tool bindings on their way into the bus. 0 card crossings, 4 edge
crossings, three of them that one link.

That corridor is not free space. It is the band `bindingLayout` **reserves for
equipment**, and a return path through it reads as if the loop were somehow
about the tools. Widening it (`GRAPH_SPACING.shelf`) would postpone the problem
rather than answer it, because the band would still be the band the router
picks.

So the answer is the sketch: **a lane of its own, outside everything.**
`canvas/layout/backEdgeLane.ts` is pure — rects in, points out — and
`AutoLayout` calls it once positions have settled:

- **A back-edge is one whose target's centre sits behind its source's** in the
  reading axis. Centres, not edges, so a shelf item overlapping its consumer by
  a few pixels is not mistaken for one. Bindings are excluded on the same
  grounds they are excluded from the ranking: equipment sits *across* the
  reading axis, so "against the flow" is not a claim that can be made about it.
- **The lane sits past the far edge of the whole arrangement** — under it in
  horizontal flow, beside it in vertical. That is the only space no rank and no
  shelf has a claim on; everything else is somebody's.
- **Two points, not one.** A single mid-lane point leaves the router free to
  approach it obliquely and rejoin early; pinning both ends of the lane run
  makes the long leg *be* the lane.
- **Longest outermost**, so two nested loops cannot cross. With one back-edge —
  every graph shipped today — the sort is a no-op that costs nothing and stops
  the two-loop case from being a surprise later.

The lane is expressed as **waypoints**, which is what makes it cost nothing
extra: the same field a user drags, stored the same way, undone in the same
step. The layout seeds a good default for the one shape that needs one, and a
user who disagrees moves it.

Seeded demo, after: **0 card crossings, 2 edge crossings.**

## Waypoints

`EdgeModel` held `id`, `source`, `target`, `label` and nothing else, and
`AutoLayout` set `setVertices: false` with the comment *"Vertices would be
written onto links, which the model has no place to store"*. It now has one.

- `IEdgeModel.vertices` / `SerializedEdge.vertices`, omitted when empty so every
  document written before this round-trips to the same bytes.
- `WorkflowModel.setEdgeVertices` + an `edge:vertices` event, mirroring the
  label pair exactly.
- `SetEdgeVerticesCommand`, coalesced per edge. One command for add, drag and
  remove, because to the document they are the same edit: the list is replaced.
- `EdgeEditor.setVertices` on `IEdgeEditor`.
- `JointGraphAdapter.applyVertices` projects them, skipping the write when both
  sides already agree — `linkTools.Vertices` writes to the cell as the user
  drags, and the echo would fight the pointer.
- `WaypointCommitFeature` commits the user's gesture back through the command.

**The UI already existed.** `LinkToolsFeature` has always attached
`linkTools.Vertices`, so clicking a link to add a point, dragging it and
double-clicking to remove it all worked — the points simply had nowhere to
live, so the next re-projection swept them away and nothing ever reached the
file. The missing half was the commit, not the gesture.

Verified in the running editor: a point added and dragged onto
`AI Agent.result → Grader.candidate` appears in the saved document as
`"vertices": [{"x": 1384, "y": 72}]`, and the run still passes through it after
a reload.

### Points are data, so portability is untouched

The guardrail is that expressions are a JSON AST and never host-language code.
A waypoint is a pair of numbers. Nothing here is a function, and nothing here
reaches the compiler: `test_workflow_compiler.py` pins that a document carrying
`vertices` compiles to byte-identical plan edges.

`EdgeModel` filters any point that is not a **finite** pair on the way in, from
the constructor and from the setter both. `Infinity` and `NaN` are not
representable in JSON, so one of them anywhere in a link would make the whole
document unwritable — the standing rule, enforced at the one door they can come
through, including a hand-edited file.

### The schema version does **not** move

`backend/openstategraph/schema.py` states the policy in as many words:

> **Do not bump:** adding an optional field with a safe default; … anything
> additive that an older build ignores harmlessly.

`vertices` is exactly that. An older build ignores it and draws the router's
own run, which is what it drew before. A bump would push every user's document
through a two-sided change to gain nothing, and would burn a migration slot on
a no-op.

**Two corrections since.** This section used to add that `SCHEMA_VERSION == 2`
was asserted in the same test that pins the compiler's indifference to
`vertices`. That assertion no longer exists, and the number no longer reads 2:
`SCHEMA_VERSION` is **3**, bumped by production-ready ticket 16 when
`team.workflow` was removed — a node type id disappearing, which is squarely
on the *do bump* list. Neither fact disturbs the decision above. `vertices` is
still additive, still ignored by an older build, and still costs no migration
slot; `MIGRATIONS[2]` transforms node types and does not touch edges. The
version pin now lives with the migration it belongs to
(`backend/tests/test_schema_v3_team_collapse.py`).

### What happens to hand-placed points when Arrange re-runs

**Arrange replaces them. All of them.** Then it seeds the back-edge lanes.

The argument: a hand-placed point is a position in document space, chosen
against where the cards were. Once every card has moved it is no longer the
route the user drew — it is a point in space nobody chose, and a run detouring
through it is a defect a reader cannot account for. Keeping stale points is the
worse failure because it is *silent*; discarding them is not.

The bar the ticket set is that the discard must be undoable in one step, and it
is: the cleared waypoints go into the **same** `history.transact('Auto layout')`
as the moves and the container re-fits, so one Cmd-Z restores the positions and
the hand-routing together, and the Undo tooltip says "Auto layout" while it can.
Pinned in `controller/autoLayoutTransaction.test.ts` and confirmed live —
Arrange dropped a hand-placed point from the document, one Undo brought it back.

The rejected alternative was to distinguish layout-placed points from
user-placed ones with a flag. That is a new field in the public document schema,
carrying provenance rather than geometry, to preserve points that have just been
invalidated anyway. It is the sort of key that is easy to add and impossible to
remove.

## `GRAPH_SPACING` was re-checked and is unchanged

The rank/node gaps were derived against curves (¾ of a card width between
ranks, half that within one), so they were worth re-deriving. They are kept, on
two grounds:

1. **The reason for the ratio survived the change.** It was chosen against the
   *label* rhythm as much as against crossings — `edgeDecoration` puts a
   five-way router's last branch label 50 + 4 × 26 = 154px along its link, so a
   shorter rank gap guarantees a label printed on the downstream card. The
   label rhythm is untouched by this ticket, so the constraint is unchanged.
2. **The residual crossings are not spacing.** They are inside a router's own
   branch fan, between ports 24px apart on one card and their targets (below).
   That is a topology, and moving the ranks further apart moves the crossing
   without removing it.

What *did* need a number is the routing grid, and it is derived the same way:
`step: 12` is `NODE.portRowHeight / 2`, so adjacent ports cannot share a lane.
It lives in `edgeDecoration` beside `LABEL_CLEARANCE` rather than in
`GRAPH_SPACING`, because it is a fact about drawing a line, not about placing a
card.

## What is not fixed

> **Re-measured on the collapsed document (one-chinook ticket 10).** The
> figures in this section were taken on the eight-node `chinook-assistant`,
> which mounted a second package on its data branch. That document is now
> thirteen nodes with the analyst's agent, tool bus and grader loop inline,
> and the same measurement — every link path sampled and intersected
> pairwise, at fit zoom, in the running editor — gives **0 card crossings and
> 14 edge crossings**.
>
> The bar is unchanged and still met: *no line crosses a card*. The edge count
> rose because the graph roughly doubled and gained a retry loop, and the
> causes are the two this section already names — several links converging on
> one `prompt` port must cross near it, and the grader's `revise` back-edge
> runs against the flow across the tool bus. No new cause appeared, and no new
> routing work is proposed here.

**`chinook-assistant` kept 6 edge crossings** at eight nodes (0 card
crossings), all of them one link against three. `Intent` fans five branches from ports stacked 24px
apart; `greeting`, `off_topic` and `general_knowledge` all rise in the same
column into `Front Desk.prompt`, and `web_lookup` — the port below them — runs
right underneath to `Web Researcher.prompt` and therefore crosses all three
risers.

This is a real regression against the curve measurement for that one graph,
which was 0/0, and it is stated rather than buried. It is also inherent to
routing each link independently: a human would drop `web_lookup` below the fan
before turning, and `manhattan` will not, because that route is longer. The
honest fixes are a bus router that plans sibling branches together, or edge
ordering that assigns each branch its own corridor — both larger than this
ticket, and both cheaper to do now that waypoints exist as a place to put the
answer. Casing (`HtmlNode`'s `casing` path) renders each of these as an
over/under rather than a junction, which is what keeps them readable.

The trade taken is deliberate: the owner asked for rigid lines by name, the
graph a new user opens on went from 3 card crossings to none, and the loop that
defeated three previous attempts now has the lane the sketch asked for.

**`jumpover` has become available and was not taken.** `HtmlNode`'s casing
comment used to justify itself by saying jumpover needs straight polyline
segments, which curves are not. Runs are orthogonal now, so that premise is
gone. Casing is kept anyway: a hop is a mark the reader has to decode and a
break is not, and jumpover recomputes every intersection on every render where
casing is one extra path and the graph's own z-order.
