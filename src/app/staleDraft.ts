/**
 * Whether this browser's draft is older than the file it was taken from.
 *
 * `restoreDraftFor` restored a draft whenever it **differed** from the file,
 * and never asked which came first. So a draft captured from an old version of
 * a package won over a newer file on disk, silently, for as long as the draft
 * lived (`every-workflow-green` 25).
 *
 * That cost real time: three separate correct fixes appeared to do nothing,
 * because each corrected file was masked on load by a stale draft. Worse than
 * the delay, it makes a file on disk stop being a picture of what you are
 * editing, which is the one thing an editor must not do.
 *
 * The rule is a comparison, not a guess. A draft that is **newer** than the
 * file is a person's unsaved work and must win — losing it was a real
 * complaint, and is why drafts exist. A draft that is **older** than the file
 * has been overtaken by something the person cannot see, and must not.
 *
 * Unknown timestamps mean "cannot tell", and cannot-tell keeps the draft: the
 * failure this guards against is losing edits, and refusing to restore on
 * missing metadata would reintroduce it. Every real path records both.
 */
export function draftIsStale(
  draftSavedAt: string | null | undefined,
  fileSavedAt: string | null | undefined,
): boolean {
  if (!draftSavedAt || !fileSavedAt) return false;
  const draft = Date.parse(draftSavedAt);
  const file = Date.parse(fileSavedAt);
  if (Number.isNaN(draft) || Number.isNaN(file)) return false;
  return file > draft;
}
