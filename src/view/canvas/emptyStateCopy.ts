/**
 * What the empty canvas says (production-ready ticket 22).
 *
 * Ticket 41 made the fresh canvas honestly empty — it no longer seeds a
 * document nobody asked for. That left the other half of the problem exposed:
 * an empty canvas beside a palette of about twenty node types, with nothing
 * saying which one comes first. The owner's decision is that the taught
 * starting shape is **Input → Agent → Output**.
 *
 * ## It teaches a convention, and it must never state a rule
 *
 * There is no rule. `plan.entry` and `plan.exits` are computed from in-degree
 * and out-degree and never from a node type; `has-output` is a **warning** that
 * asks whether *anything* is terminal, and its own notes record that checking
 * for an `output.formatted` node made every agent-ended workflow a false
 * positive. The one hard requirement nearby is a **port's**, not a shape's —
 * `agent.llm.prompt` is `required`, and it accepts `result` as readily as
 * `text`, so a Worker or a mounted Workflow satisfies it exactly as an Input
 * does. So the wording here is "most flows", never "must" — and
 * `emptyStateCopy.test.ts` holds it to that, because the fastest way to make
 * an editor feel wrong is to tell a beginner something the validator will
 * later contradict.
 *
 * Strings, in a module, so they can be tested and so the canvas component
 * stays a projection of them.
 */

import { EXAMPLES_ROUTE } from '@view/workflow/examplesJourney';

/** The one line that teaches the shape. */
export const EMPTY_CANVAS_TITLE = 'Start with Input → Agent → Output';

/**
 * What each of the three is for. The hedge in the last clause is the honest
 * part and is not decoration: most flows are shaped like this; none has to be.
 */
export const EMPTY_CANVAS_PATTERN =
  'The Input holds the question, the Agent does the thinking, the Output is the answer. Most flows start and end that way.';

/**
 * How to get there in one gesture — naming the palette entry exactly, so a
 * reader can find the thing this sentence is talking about.
 */
export const EMPTY_CANVAS_HINT =
  'Drag “Starter flow” from the palette for all three, already wired — or drag nodes in one at a time, or press ⌘V to paste.';

/**
 * The other way in (production-ready ticket 23): don't draw one, take one.
 *
 * The gallery was invisible from here. Everything above teaches drawing a flow
 * from parts, which is the right first lesson and the slower one; a reader who
 * would rather see a finished flow had no sentence telling them 23 of them are
 * one panel away. The route is `EXAMPLES_ROUTE` rather than a phrase written
 * here, so the canvas and the shelf cannot come to call it different things.
 *
 * No count in it. This surface has no list to count — `GET /api/examples` is
 * what knows — and a number typed into copy is exactly how this repository
 * ended up with prose claiming twenty, twenty-one and twenty-two at once.
 */
export const EMPTY_CANVAS_EXAMPLES = `Or start from one that already works: open ${EXAMPLES_ROUTE}, copy one, and the copy is yours to edit and run.`;
