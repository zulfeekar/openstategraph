/**
 * Paths the dev server must not watch.
 *
 * `workflows/` is **data the editor writes**, not source it is built from.
 * Since disk autosave landed (the-editor-makes-a-real-package ticket 02),
 * every edit updates a file in there — and with the default watcher that
 * tripped a full page reload, which reloaded the workflow, which autosaved,
 * which reloaded. The editor reloaded itself every few seconds with nobody
 * touching it, and because each reload starts a fresh module it also wiped the
 * in-memory baseline that would otherwise have stopped the second write, so
 * both defences failed at once.
 *
 * The symptom surfaced somewhere else entirely, which is what made it
 * expensive to find: the Get Table Schema card measures short while its table
 * list loads and tall once it arrives, so every reload wrote a different
 * height and the package looked as though it were oscillating on its own.
 * Ticket 05 was filed against the card; the card was innocent.
 *
 * Lives here rather than inline in `vite.config.ts` so the rule has one
 * definition and a test can hold it to it — the config file itself is outside
 * the app's TypeScript project and cannot be imported from a test.
 *
 * **One known exception, accepted with eyes open:** `seedDemo.ts` imports
 * `workflows/chinook-assistant/workflow.json`, so in dev (and only in dev —
 * ticket 41 gated the seed out of production builds) that one file is both a
 * build input and watch-ignored. Editing it on disk therefore shows a stale
 * canvas until a manual reload. That trade is deliberate, not an oversight:
 * the seed document is exactly the document the dev editor opens and
 * autosaves into, so watching it would recreate the write → reload →
 * autosave → write loop described above for the most-edited file in the
 * repository. A manual reload after an out-of-editor edit is the cheap side
 * of that trade. (workflow-gallery follow-up to ticket 41.)
 */
export const DEV_SERVER_WATCH_IGNORED: readonly string[] = ['**/workflows/**'];
