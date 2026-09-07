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
 *
 * **Verified against the case it was written for**, 2026-08-21, in a production
 * build: a package open with an unsaved edit, its `workflow.json` then changed
 * on disk from three nodes to five, then reloaded. The canvas restores the
 * three-node draft and this sentence appears. Worth recording here because the
 * ticket sat `partially resolved` for two days on the belief that the sentence
 * was unreachable — it was reachable from `9be5b53`, and nobody had run the
 * changed-on-disk reproduction rather than an ordinary warm reload.
 *
 * The hedge in the second sentence — *if* the file changed elsewhere — is the
 * known limit, not an oversight. After a reload `workflowFileWatch`'s
 * `knownSavedAt` map is empty, so its first poll re-baselines silently and its
 * definite "changed on disk" banner never returns; this is the only thing said.
 * Making it definite is `every-workflow-green` 41, and it is a change to what
 * is *said*, never to which document wins.
 */
export function restoredDraftNotice(slug: string | null | undefined): string {
  const name = (slug ?? '').trim();
  if (!name) return '';
  return (
    `Restored your unsaved edits to ${name} from this browser — not the saved file. ` +
    `If the file changed elsewhere, you are not seeing that yet.`
  );
}
