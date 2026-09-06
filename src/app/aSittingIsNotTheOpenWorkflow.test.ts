import { describe, expect, it } from 'vitest';

import { BROWSER_SESSION_KEY, browserSessionId } from '../core/runtime/browserSession';
import { DRAFT_SESSION_KEY } from './workflowDrafts';

/**
 * The decision `memory-and-replay/45` had to make rather than assume.
 *
 * `sessionStorage` already held a key with *session* in its name, so the
 * ticket's own instruction was to check whether the sitting a run belongs to
 * was that concept already wearing the word. It is not:
 * `DRAFT_SESSION_KEY` holds **which draft key this tab autosaves under**, and
 * `startWorkflowSession` re-keys it every time the open workflow changes. A
 * sitting borrowed from it would split in two the moment a user loaded a second
 * workflow, and two tabs editing one workflow would collapse into one sitting —
 * the opposite of the axis `43` settled `session_id` on.
 *
 * This test lives in `app/` rather than beside `browserSession.ts` because
 * `core/` may not import `app/` (eslint, CLAUDE.md § Layering), and the pin is
 * on the pair.
 */
describe('the two session keys', () => {
  it('are two keys, because they are two concepts', () => {
    expect(BROWSER_SESSION_KEY).not.toBe(DRAFT_SESSION_KEY);
  });

  it('do not write over one another', () => {
    const seen: Record<string, string> = { [DRAFT_SESSION_KEY]: 'slug-chinook' };
    const store = {
      getItem: (key: string) => seen[key] ?? null,
      setItem: (key: string, value: string) => {
        seen[key] = value;
      },
    };

    const sitting = browserSessionId(store);

    expect(seen[DRAFT_SESSION_KEY]).toBe('slug-chinook');
    expect(seen[BROWSER_SESSION_KEY]).toBe(sitting);
  });
});
