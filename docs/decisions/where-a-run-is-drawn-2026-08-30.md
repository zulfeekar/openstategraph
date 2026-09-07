# Where a run is drawn, and what a popover is bounded by

2026-08-30 · `memory-and-replay` 51 and `launch-readiness` 189, resolved in one
session because they share one mechanism.

## The shape, as the owner settled it

The timeline was asked for as *"a section on the top panel"*. The top bar is a
48px strip; a multi-lane chart is not a thing that fits in one. So the request
was for **where the control lives**, not where the pixels live, and it is
resolved that way: a toggle in the toolbar, a dock along the bottom.

Five decisions, and they hang together:

1. **One component, two data sources.** `RunDock` is written against a
   `RunView` snapshot — rows, a question, whether it is still running, and
   where it came from. Live, `AskPanel` publishes into that store frame by
   frame. Finished, the same rows come back off a record. 37 said the same
   thing about replay: *"that view, fed from storage instead of a stream."*
   Two components would mean the second one rediscovering every rule the first
   one learned, which is how `memory-and-replay` 38 happened.

2. **No transport while a run is live.** *"A live run has no end yet; a slider
   that cannot reach its right-hand edge is lying about what it can do."* The
   control that appears once a run has an end is 52's, and this ships without
   one rather than with a disabled one.

3. **Push, not overlay — and at the shell, not the panel.** `.app-shell__stage`
   wraps the top bar, the palette, the canvas and the inspector; the dock is
   its **sibling**. So the canvas is never covered, only shorter. Every other
   panel in this editor overlays when the room runs out, and none of them is a
   time axis you read *while* watching the thing it measures.

4. **`view/`, never a JointJS paper feature.** The canvas is a one-way
   projection of the **model**; a timeline draws a **run**. One surface must
   not project two sources of truth.

5. **Two of the three run surfaces moved; one stayed.** The bars became the
   dock, the trace tree became the detail pane beside them, and `PastRuns`
   stays in the chat panel — it is a list *of runs*, a different job. Export
   trace JSON travelled with the trace it exports.

## No panel registry, and the trigger that would change that

Two panels arriving in one week is the argument for one, and it was taken
seriously. It is still no, for a reason narrower than "two customers is not
enough":

**A registry buys open-for-extension, and `view/` has nobody to extend it.**
The seven `Registry<T>` sites in this codebase each have a contributor outside
the module that owns them — a node type, an executor, a provider, a canvas
feature, a card body. `view/` is the leaf: `core/` imports no React by rule,
so nothing outside `view/` can contribute a panel, and a registry with two
internal entries is a lookup table whose value type is the union of two
component signatures.

**And the thing the two panels actually share is not "being registered".** It
is **geometry** — a width or a height taken out of the shell — which is already
expressed as data in `panelFit.ts`. So this session added the height axis
(`dockFit.ts`) rather than a registry, which is the sharing that was really
being asked for.

The trigger that flips this: a panel contributed from **outside** `view/` — a
plugin — or a third dockable surface wanting the same geometry. Either one, and
the registry is the right move.

## Popover, not panel, for Workflows

The owner named both, and the content decides. The list is used to **switch**
workflows, which is transient. The counter-argument was that `Save current` and
the publish controls live in it too, and those are work — but since
`say-it-on-the-surface` 01 and `ship-it` 39 **Save and the whole publish
cluster are in the top bar**, so what is inside the popover is a duplicate of a
toolbar control and the panel's only unique job is the list.

It closes three ways: an outside pointer press, `Escape` (returning focus to
the button), and opening a workflow, which navigates away from the question the
list was asked.

**Fitting beats centring**, and the centre is computed first and then clamped —
never the other way round. Centring says *this came from that button*; fitting
is what makes the list readable, and the top bar wraps, so the trigger really
does travel to within half a popover of both edges.

## What `launch-readiness` 39's guard was replaced by: nothing, because the collision cannot happen

39 stood the Workflows drawer beside the palette (`left:
var(--layout-palette-width)`) because two `panel--left`s floating at `left: 0`
meant whichever painted last won. A popover is not a `panel--left`, is not in
`app-shell__body`'s flow, and cannot claim `left: 0`. The rule, the
`data-palette-open` attribute, the `workflows` term in `PANEL_WIDTH` and
`leftOverlayWidth`, and the two test cases asserting the resolution are all
**removed with their argument recorded at each site** rather than left
describing code that no longer exists.

## The half that made these one ticket

> *"remember it should move along the container when the timeline lands"*

The dock is a sibling of the stage, so opening or dragging it takes height out
of the stage **while the window does not resize and no `resize` event fires
anywhere**. `useViewportWidth` watches `window` and would report nothing; a
popover clamped to the window would hang over the timeline. So `useFloating`
gained a `bounds` callback, and `observeResize` — a `ResizeObserver` with the
same one-pixel guard `JointGraphAdapter.applyGeometry` uses, because a drag
fires one per frame — supplies its existing "the anchor may have moved"
channel.

Measured at 1440x900, popover open, dock toggled from closed to 260px: height
848 -> 588, top unchanged at 44, bottom 632 against a stage bottom of 640, and
`innerHeight` 900 throughout. Built apart, the popover would have been written
against a container that does not move yet and rewritten the week the dock
landed.

## Numbers, and where they are pinned

| | | |
| --- | --- | --- |
| dock default height | 260 | `dockFit.ts`, `dockFit.test.ts` |
| dock minimum | 140 | the head row, two lanes and the caveat |
| dock maximum | `shellHeight - topbarHeight - MIN_CANVAS_HEIGHT` | not a percentage: a fraction claims to know what the canvas needs |
| `MIN_CANVAS_HEIGHT` | `NODE.minHeight * 4` | the sibling of `MIN_CANVAS_WIDTH` |
| persistence | per viewer, `localStorage` | a height is a fact about a screen, not about a document |
| shortcut | `Mod+Shift+L` | `Mod+Shift+T` is the mnemonic and Chrome owns it |
