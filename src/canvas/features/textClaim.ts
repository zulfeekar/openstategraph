/**
 * Where the browser's own text handling has a claim on a key, and a canvas
 * shortcut does not.
 *
 * Two questions, deliberately kept separate rather than merged into one
 * "should a canvas shortcut win here". They are answered by different facts
 * and they protect different bindings:
 *
 *  - `isTextEntry` — is *focus* in a field. It exists because typing "a" in a
 *    prompt must not select every node, and `Escape` uses it to decide whether
 *    it has a field to blur. Focus is the whole answer there.
 *  - `hasTextSelection` — is there *selected text* anywhere in the document.
 *    Focus is irrelevant: a reader selects an error message with the mouse and
 *    focus stays on `<body>`.
 *
 * They were one predicate until `launch-readiness` 187, when the second
 * question was asked of the first and got the wrong answer — selected text in
 * a `<div>` is not a field, so ⌘C reached the node clipboard and put JSON on
 * the pasteboard instead of the error message somebody was trying to report.
 * `isTextEntry` was right about what it says; it was simply being asked
 * something else.
 */

/** True when focus is somewhere the user is typing. */
export function isTextEntry(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

/**
 * True when the document holds a selection a user could copy.
 *
 * The text, not the collapsed flag, is the test — and that is what makes this
 * complete rather than a plausible one-liner. A range can be non-collapsed and
 * still carry nothing: JointJS sets `user-select: none` inline on the cells
 * layer, so **no node on the canvas is selectable text at all**, and any range
 * spanning one stringifies to nothing. Reading the text therefore answers "is
 * this a canvas selection or a prose selection" for free, and more reliably
 * than walking the tree for a container that a portal could put anywhere.
 *
 * A stale selection cannot strand the node clipboard either: pressing ⌘C on a
 * node means having clicked the canvas first, and a mousedown collapses the
 * document selection (verified in the browser, 2026-08-29).
 */
export function hasTextSelection(): boolean {
  const selection = window.getSelection?.();
  return selection !== null && selection !== undefined && selection.toString().trim() !== '';
}
