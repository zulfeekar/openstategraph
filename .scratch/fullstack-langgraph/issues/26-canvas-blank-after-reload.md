Type: defect
Status: open
Blocked by:

## Question

**The canvas renders no cells after a page reload, although the model is fully populated.**

Found while verifying ticket 17 in the browser. Reproduced on commit `6c52505`
(before the controller decomposition) as well as after it, by stashing the
refactor and reloading — **so it is pre-existing and not caused by ticket 17.**

### Symptom

| | First load after `vite` starts | Any subsequent reload |
| --- | --- | --- |
| `.joint-element` | 6 | **0** |
| `foreignObject` (React portals) | 6 | **0** |
| `.joint-link` | 4 | **0** |
| `.minimap__node` | 6 | 6 |
| "6 nodes / 4 links" label | yes | yes |

So the **model is correct** — the minimap and the inspector's counts both read
it and both agree. Only the JointJS paper is empty. The palette, topbar,
inspector and minimap all render normally, and **there is not a single console
error or warning**, which is what makes it easy to miss.

### Why it matters more than it looks

The app appears completely broken to anyone who refreshes the page — which is
the first thing a developer does. It is only invisible because a fresh `vite`
start happens to work, so it hides during normal `npm run dev` usage and appears
the moment you hit reload.

### Where to look

This is the same family as two phase-1 defects, both recorded in the map:

- `paper.remove()` deleting React's own node under StrictMode, fixed by giving
  JointJS its own inner `.canvas-surface` div.
- `rebuild()` adding links before `resetCells()` had added elements, so every
  `createLink` returned null.

Both were **ordering/lifecycle** bugs between the paper, the adapter and React's
double-mount. A warm reload differs from a cold start in exactly one way that
matters here: module state and the React mount sequence are already warm, so a
first-load-only success strongly suggests the adapter's initial `rebuild()` is
racing the paper's readiness, or is running against a paper that a StrictMode
double-mount has since replaced.

Start at `PaperController` construction and `JointGraphAdapter`'s initial sync,
and check whether the adapter subscribes *before* it seeds, and whether the
second StrictMode mount reseeds.

### Note on testability

This is precisely the class of bug ticket 11 decided **not** to cover with
tests, and the decision still looks right — jsdom would not reproduce a
JointJS/React mount race faithfully, and a test that passed against a fake
paper would have given false confidence here. What was missing is not a unit
test but a **smoke check that the canvas actually has cells after a reload**,
which is cheap and would have caught this. Add that with the canvas harness
deferred in ticket 11.
