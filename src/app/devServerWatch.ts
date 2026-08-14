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
 */
export const DEV_SERVER_WATCH_IGNORED: readonly string[] = ['**/workflows/**'];
