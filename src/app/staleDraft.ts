/**
 * @deprecated Retired, and never wired in — `osg-agent-experience/70`.
 *
 * **Read the first sentence of this docstring before the rest of it.** Until
 * 2026-09-05 this opened by describing a fix it performs — *"`restoreDraftFor`
 * restored a draft whenever it differed from the file, and never asked which
 * came first"* — in the present tense, as a thing this repository does.
 * `restoreDraftFor` never called it, and no shipped module ever has. A reader
 * checking whether the editor guards against a stale draft found a function
 * that says it does, is tested, and is connected to nothing, which is worse
 * than an absence because an absence is legible.
 *
 * ## What replaced it, and why a clock lost
 *
 * The question this asks — *is my draft behind the file* — is a real one and
 * is answered, twice, without a clock:
 *
 * - `osg-agent-experience/68` compares **canonical bytes** on the reload path.
 *   `restoreDraftFor` records the argument at length: a browser with a wrong
 *   clock must not silently win or silently lose, so what is on screen is
 *   decided by whether the documents differ rather than by which claims to be
 *   newer.
 * - `osg-agent-experience/69` gave a draft the **revision** it was taken from
 *   (`saveWorkflow`'s `baseDigest`), which answers *which came first* exactly
 *   — a content digest cannot be wrong about its own file — and narrows 68's
 *   question back to the case it was written for.
 *
 * So there is nothing left for a timestamp comparison to decide, and wiring it
 * in now would be a third answer to a settled question.
 *
 * ## Why it is still here
 *
 * Retired by commit rather than by deletion, which is the standing rule, and
 * because the argument below is the record of `every-workflow-green` 25 —
 * where three separate correct fixes appeared to do nothing, each corrected
 * file masked on load by a stale draft. That account is worth keeping legible;
 * the function is what it is attached to. Whether the declaration itself is
 * removed is the owner's call, recorded in the ticket.
 *
 * `src/app/aRetiredGuardSaysSo.test.ts` fails if a shipped module starts
 * calling this, and if `draftIsAhead` — the live one — ever stops having a
 * caller. The next drift is a red test rather than a paragraph.
 *
 * ---
 *
 * Whether this browser's draft is older than the file it was taken from.
 *
 * The rule is a comparison, not a guess. A draft that is **newer** than the
 * file is a person's unsaved work and must win — losing it was a real
 * complaint, and is why drafts exist. A draft that is **older** than the file
 * has been overtaken by something the person cannot see, and must not.
 *
 * Unknown timestamps mean "cannot tell", and cannot-tell keeps the draft: the
 * failure this guards against is losing edits, and refusing to restore on
 * missing metadata would reintroduce it.
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
 * **The live one of the two.** `usePublishState` calls it; the sibling above
 * is retired and calls nothing.
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
