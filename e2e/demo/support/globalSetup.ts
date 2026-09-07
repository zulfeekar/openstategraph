import { rmSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * Empty the board before a recording, and nothing else.
 *
 * The patrol scene has to open a board with no cards on it, because the story
 * is *a patrol finding something* — a board that already holds the findings
 * answers the question before it is asked, and a second patrol over the same
 * runs files nothing and reports "0 new".
 *
 * Only `kanban.sqlite` is removed. The recorded runs in the same directory are
 * what the patrol reads, and scene 5 produces one with a real model call, so
 * deleting them would either cost another call or leave the patrol with
 * nothing to find when a single scene is re-recorded on its own.
 */
export default function resetBoard() {
  const stateDir =
    process.env.OPENSTATEGRAPH_STATE_DIR ?? '/private/tmp/osg-demo-state';
  rmSync(resolve(stateDir, 'kanban.sqlite'), { force: true });
}
