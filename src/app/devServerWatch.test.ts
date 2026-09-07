import { describe, expect, it } from 'vitest';
import { DEV_SERVER_WATCH_IGNORED } from './devServerWatch';

/**
 * The dev server must not watch `workflows/`.
 *
 * This is a one-line config setting guarding a failure that took an hour to
 * find, so it gets a test rather than a comment alone
 * (the-editor-makes-a-real-package tickets 02 and 05).
 *
 * Since the editor autosaves to `workflows/<slug>/workflow.json`, a watcher on
 * that directory closes a cycle: write → full page reload → the reloaded page
 * opens the workflow → autosave → write. The editor reloaded itself every few
 * seconds with nobody touching it, and because each reload starts a fresh
 * module it also wiped the in-memory baseline that would otherwise have
 * stopped the second write — so the two defences failed together.
 *
 * The visible symptom was somewhere else entirely, which is what made it
 * expensive: the Get Table Schema card measures short while its table list
 * loads and tall once it arrives, so every reload wrote a different height and
 * the package looked like it was oscillating on its own. Ticket 05 was filed
 * against the card. The card was innocent.
 *
 * One file under `workflows/` IS imported by the dev bundle — `seedDemo.ts`
 * pulls in `chinook-assistant/workflow.json` — and it stays ignored anyway,
 * because it is also the file dev autosave writes: watching it would close
 * the loop again. The exception is documented beside the constant; the second
 * test below holds the two files to each other so neither half can go stale
 * alone.
 */
describe('the dev server watcher', () => {
  it('ignores the directory the editor writes to', () => {
    expect(DEV_SERVER_WATCH_IGNORED.some((pattern) => pattern.includes('workflows'))).toBe(true);
  });

  it('documents the one build input it knowingly leaves stale', async () => {
    const { readFileSync } = await import('node:fs');
    const seed = readFileSync(new URL('./seedDemo.ts', import.meta.url), 'utf8');
    const rule = readFileSync(new URL('./devServerWatch.ts', import.meta.url), 'utf8');

    const seedImportsWorkflow = /from '..\/..\/workflows\//.test(seed);
    if (seedImportsWorkflow) {
      // The exception exists, so the rule's docstring must name it.
      expect(rule).toContain('seedDemo');
    } else {
      // The import is gone — delete the exception paragraph and this branch.
      expect(rule).not.toContain('seedDemo');
    }
  });
});
