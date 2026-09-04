/**
 * Whether the sunken `.ask__steps` strip has anything to draw.
 *
 * `memory-and-replay/51` moved the trace tree and the timeline bars out of
 * this box into the run dock along the bottom of the shell. What is left
 * inside is the live line (`turn.running && turn.progress`, or the
 * `waitingLine` placeholder while `running`) and the hand-off pills
 * (`SpawnedPills`, one per spawned child). Both are gated on their own
 * presence already — the box itself was not, so it kept opening on
 * `turn.running || turn.activity.length > 0`, a condition written for the
 * trace tree that used to live here. `activity` now feeds the dock too, so
 * a finished turn with steps in the dock and nothing left to say drew the
 * bordered, sunken container (`AskPanel.css:177`) around nothing —
 * `stable-beta-public/08`.
 *
 * The fix is the condition, not `:empty` CSS: hiding an empty landmark with
 * a stylesheet still leaves the empty landmark in the DOM for a screen
 * reader. So this asks the same question the JSX asks, in one place a test
 * can call without a paper, a controller or a stream.
 */
export function showsSteps(turn: {
  readonly running: boolean;
  readonly hasPills: boolean;
}): boolean {
  return turn.running || turn.hasPills;
}
