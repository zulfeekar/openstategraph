Type: defect
Status: retracted — not reproducible, environment artifact
Blocked by:

## Question

Originally filed as: *the canvas renders no cells after a page reload, although
the model is fully populated.*

**Retracted. This was over-called, and the product is not defective.**

## What was actually observed

The observation itself was real and sustained, not a misread: `.joint-element`,
`foreignObject` and `.joint-link` all read **0** while `.minimap__node` read 6
and the label read "6 nodes / 4 links", with no console error. It persisted
across several minutes and many separate tool calls, and — the reason it looked
credible — it reproduced identically after `git stash`ing the ticket-17 refactor
and reloading on `6c52505`.

That last point was treated as proof it was a pre-existing product bug. It was
actually the clue that it was **not a code bug at all**: an identical failure in
two different builds of the application points at something outside both.

## Why it is not a defect

It does not reproduce, across every scenario that would matter:

| Scenario | Result |
| --- | --- |
| 6 consecutive clean loads (fresh iframes, 1.2s settle) | 6/6 rendered |
| Cold `vite` start, first load | rendered |
| Warm reload after a cold start | rendered |
| Repeated `navigate` force-reloads | rendered |

Instrumented directly at the source rather than inferred from the DOM: the graph
holds 10 cells (6 elements, 4 links), the paper is **not** frozen, its computed
size is non-zero, and StrictMode's double mount (`mounts: 2`) leaves the second
paper correctly populated.

Two hypotheses were tested and both failed:

- **A premature read against the async paper** (`async: true` batches view
  rendering). Rejected — the tool round-trip is measurably ~7.8s after
  navigation, far past any render batch, and the zeros persisted across
  successive calls.
- **A zero-size paper at mount culling every view.** Rejected — `getComputedSize()`
  is non-zero and no `viewport` culling function is configured on the paper.

## Most likely cause, and the trap worth remembering

The dev server had been killed **while the page was still loaded** (the original
`vite` process was terminated to free port 5273, then a new server was started on
the same port). Vite serves ES modules with optimizer-dependency hashes in the
URL (`?v=…`); a page holding module URLs from the *previous* server against a
*new* optimizer output can end up partially initialized — enough for React, the
palette, the topbar and the minimap to render from the model while the canvas
layer never seeds.

**The trap:** this produces a very convincing false positive. It is silent (no
console error), stable (it does not flicker), and — because it is environmental
— it reproduces across code versions, which is exactly the check normally used
to prove a bug is pre-existing rather than newly introduced.

**Rule for future sessions:** after restarting a dev server, do a **hard reload
of the page** before trusting anything the canvas does or does not show. Do not
conclude "pre-existing" from a stash-and-compare alone when the failure is
silent — confirm on a freshly started server and a fresh page first.

## The one thing worth keeping

The **reload smoke check** proposed in the original filing is still worth having,
and this episode argues for it more strongly rather than less: a one-line
assertion that the canvas has cells after load would have answered the question
in seconds instead of via a stash-and-compare that pointed the wrong way. Belongs
with the canvas harness deferred in ticket 11.

Ticket 11's decision not to jsdom-test the canvas is untouched by this — a fake
paper would have told us nothing here either way.
