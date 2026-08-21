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

/**
 * Whether this browser holds work the file on disk does not — the inverse
 * question to `draftIsStale`, and a different one from "they differ".
 *
 * `ship-it` 39 needs it because publishing ships the **saved** version: the
 * moment the draft is ahead of the file, pressing Publish would put something
 * other than what is on screen in front of customers, and that is the sentence
 * the toolbar owes the user before it happens.
 *
 * Unknown timestamps mean "cannot tell", and cannot-tell answers **false**
 * here — the opposite default from `draftIsStale`, and deliberately so. The
 * two functions guard opposite losses: that one keeps a draft when it cannot
 * tell, because losing edits is the failure. This one declines to raise a
 * confirm it cannot justify, because a warning that fires on every publish is
 * a warning nobody reads by the third one.
 */
export function draftIsAhead(
  draftSavedAt: string | null | undefined,
  fileSavedAt: string | null | undefined,
): boolean {
  if (!draftSavedAt || !fileSavedAt) return false;
  const draft = Date.parse(draftSavedAt);
  const file = Date.parse(fileSavedAt);
  if (Number.isNaN(draft) || Number.isNaN(file)) return false;
  return draft > file;
}
