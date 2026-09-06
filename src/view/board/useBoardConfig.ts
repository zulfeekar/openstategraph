import { useEffect, useState } from 'react';
import { RuntimeClient } from '@core/runtime/RuntimeClient';
import type { BoardConfig } from './boardTabs';

/**
 * What the backend says about the environment behind the board's tabs —
 * `team-board-and-gap-reports/04`.
 *
 * **Asked while the board is open, and not before.** The fact costs one
 * `GET /api/health`, which reads environment variables and opens no socket,
 * but a tab that never opens the board should not pay even that on load —
 * the same "cost only while somebody is looking" rule `kanban_events.py`
 * argued for the poll behind it.
 *
 * **`null` means unanswered, and callers must not read it as `false`.** A
 * board that drew four empty columns for a second while the question was in
 * flight would make the claim-versus-state mistake `boardTabs.ts` exists to
 * avoid, one beat before making the right one. `boardTabState`'s default
 * argument is where that lands: unanswered reads as unconfigured, which is
 * the conservative sentence rather than the optimistic board.
 *
 * A hook rather than a fetch inside `PatrolBoard`, because the view must
 * contain no `fetch(` — `aTabThatIsNotBuiltSaysSo.test.ts` asserts exactly
 * that, and this is the layering rule it stands for: the view calls the
 * client, it does not become one.
 */
export function useBoardConfig(open: boolean): BoardConfig | null {
  const [config, setConfig] = useState<BoardConfig | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    const client = new RuntimeClient();
    void client.health().then((result) => {
      if (!live || !result.ok) return; // an unreachable backend is not
      // evidence that nothing is configured — it stays whatever it last was.
      setConfig({
        teamBoardConfigured: result.value.teamBoardConfigured,
        teamBoardEnvVar: result.value.teamBoardEnvVar,
      });
    });
    return () => {
      live = false;
    };
  }, [open]);

  return config;
}
