import { cpSync, rmSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The recording's own workflows root, and an empty board.
 *
 * **Why the copy exists.** A recording drives the real editor, and the editor
 * saves. Pointed at the repository's own `workflows/`, a stray keystroke in a
 * focused field is a modified tracked file — which is not hypothetical: a
 * throwaway probe that pressed `+`, `=` and `Equal` looking for the zoom
 * shortcut left `+++======` at the head of a skill's YAML frontmatter in
 * `chinook-assistant`, and it survived undetected into a `git add -A` because
 * it arrived inside a 513-line diff of harmless default materialisation.
 *
 * So the recording gets its own tree and cannot reach the tracked one. The
 * `.openstategraph` directory is skipped: it is 144 MB of local run state, it
 * is gitignored, and a recording that starts with an empty one is a recording
 * of what a stranger sees.
 *
 * **Why only `kanban.sqlite` is removed from the state directory.** The patrol
 * scene has to open a board with no cards on it, because the story is *a patrol
 * finding something* — a board that already holds the findings answers the
 * question before it is asked, and a second patrol over the same runs files
 * nothing and reports "0 new". The recorded runs in the same directory are what
 * the patrol reads, and scene 5 produces one with a real model call, so deleting
 * them would either cost another call or leave the patrol with nothing to find
 * when a single scene is re-recorded on its own.
 */
export const DEMO_WORKFLOWS = '/private/tmp/osg-demo-workflows';

export default function prepareRecording() {
  const stateDir =
    process.env.OPENSTATEGRAPH_STATE_DIR ?? '/private/tmp/osg-demo-state';
  rmSync(resolve(stateDir, 'kanban.sqlite'), { force: true });

  rmSync(DEMO_WORKFLOWS, { recursive: true, force: true });
  cpSync(resolve(process.cwd(), 'workflows'), DEMO_WORKFLOWS, {
    recursive: true,
    filter: (src) => !src.includes('/.openstategraph'),
  });
}
