/**
 * What a warm reload should say about the document it just put on screen.
 *
 * A reload with a draft takes the **restore** branch of
 * `useDeepLinkedWorkflow`, which deliberately does not fetch the document —
 * a tab's unsaved edits must not be overwritten by the file. That is right.
 *
 * What was wrong is that it also said **nothing** (`every-workflow-green` 25).
 * The cold path toasts `describeOpened`, which has a sentence for exactly this
 * case; the warm path skips the load and the toast together. So a file edited
 * outside the editor — by a colleague, by an agent, by `git pull` — was masked
 * by this browser's older copy with no indication at all. Observed: the file
 * held 13 nodes, the canvas showed 12, and nothing on screen mentioned it.
 *
 * The restore rule itself is **not** changed here. `restoreDraftFor` compares
 * canonical bytes rather than timestamps, on the recorded argument that a
 * browser with a wrong clock must not silently win or silently lose. That
 * decision stands; a wrong clock is a real thing and this is a real reason.
 * What it never justified was staying quiet, and quiet is what cost an hour of
 * chasing three correct fixes that appeared to do nothing.
 *
 * Empty string when there is nothing to say, so the caller can skip the toast
 * rather than show a blank one.
 */
export function restoredDraftNotice(slug: string | null | undefined): string {
  const name = (slug ?? '').trim();
  if (!name) return '';
  return (
    `Restored your unsaved edits to ${name} from this browser — not the saved file. ` +
    `If the file changed elsewhere, you are not seeing that yet.`
  );
}
