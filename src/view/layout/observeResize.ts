/**
 * Tell me when this element's own box changes.
 *
 * The counterpart of `useViewportWidth`, and it exists because that hook
 * cannot answer the question `launch-readiness` 189 asks. `useViewportWidth`
 * listens for `resize` on `window`; the run dock (`memory-and-replay` 51) is a
 * **sibling** of the shell's stage, so opening it or dragging its edge takes
 * three hundred pixels of height out of the stage while the window's size does
 * not change and no `resize` event fires anywhere. Anything anchored inside
 * the stage would go on believing it had the whole window.
 *
 * Shaped as a subscription rather than as a hook because that is what
 * `useFloating` asks for — *"tell me when the anchor may have moved"* — and it
 * already carries the same escape hatch for the canvas, which pans and zooms
 * by an SVG transform and raises no DOM event either. One mechanism, two
 * reasons an anchor moves; no second positioning module.
 *
 * Guarded against no-op notifications, which is not an optimisation here: a
 * `ResizeObserver` fires on every reflow and a drag produces one per frame, so
 * an unguarded relay would re-measure and re-render on every repaint for the
 * whole length of a drag. `JointGraphAdapter.applyGeometry` is the precedent —
 * same observer, same one-pixel threshold, same reason.
 *
 * Returns its own unsubscribe, and a no-op one when there is nothing to watch.
 */
export function observeResize(element: HTMLElement | null, changed: () => void): () => void {
  if (!element || typeof ResizeObserver === 'undefined') return () => {};

  let width = element.getBoundingClientRect().width;
  let height = element.getBoundingClientRect().height;

  const observer = new ResizeObserver(() => {
    const box = element.getBoundingClientRect();
    if (Math.abs(box.width - width) < 1 && Math.abs(box.height - height) < 1) return;
    width = box.width;
    height = box.height;
    changed();
  });
  observer.observe(element);
  return () => observer.disconnect();
}
