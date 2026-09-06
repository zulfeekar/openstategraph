import type { TabDefinition } from '@design/primitives';

/**
 * The board's three tabs — `kanban-patrol/06`.
 *
 * ## Why this is not in `patrolBoardModel`
 *
 * It was, and that module had five reasons to change: a column, a tab, a
 * priority level, the card's shape and the board's copy. A tab and a column
 * are unrelated axes — one is *which source of findings you are looking at*,
 * the other is *what a finding needs next* — and they will move for different
 * reasons and at different times. Splitting them is the smallest honest cut.
 */

export type BoardTabId = 'workflows' | 'osgEngineering' | 'github';

export const BOARD_TABS: readonly TabDefinition<BoardTabId>[] = [
  { id: 'workflows', label: 'Workflows' },
  { id: 'osgEngineering', label: 'OSG Engineering' },
  { id: 'github', label: 'GitHub' },
];

export type BoardTabState =
  | { readonly kind: 'board' }
  | {
      readonly kind: 'unavailable';
      readonly title: string;
      readonly body: string;
      /**
       * A shell command the reader is meant to run, kept out of `body` —
       * `osg-agent-experience/83`. Prose reflows, and a command that reflows
       * with it cannot be selected in one piece; so it is a field of its own,
       * rendered on a line of its own.
       */
      readonly command?: string;
    };

/**
 * What the backend said about the environment it is running in —
 * `team-board-and-gap-reports/04`.
 *
 * Two fields, both from `GET /api/health`, and the second is the **name** of
 * a variable rather than its value: the variable holds a URI with a password
 * in it, and what this surface needs is something a maintainer can be told to
 * set. Nothing here spells the name itself — one copy owner, and the owner is
 * the process that actually reads the variable.
 */
export interface BoardConfig {
  readonly teamBoardConfigured: boolean;
  readonly teamBoardEnvVar: string;
  /**
   * Why the configured board could not be opened, or `null`/absent —
   * `team-board-and-gap-reports/18`. The backend probes once at startup and
   * publishes the sentence; nothing here composes one, for the same reason
   * nothing here spells the variable's name.
   *
   * Optional, because an older process does not answer it and because the
   * two tests written before this ticket construct a `BoardConfig` without
   * it: absent means *nothing said anything went wrong*, which is the same
   * reading a `null` gets.
   */
  readonly teamBoardError?: string | null;
}

/**
 * What a tab is worth before the backend has answered.
 *
 * Not an optimistic guess: a board that drew four empty columns while the
 * fact was still in flight would make the claim-versus-state mistake this
 * module exists to avoid, one beat before making the right one. The variable
 * name is empty because nothing has said one, and the sentence below is
 * written to survive that.
 */
const UNANSWERED: BoardConfig = {
  teamBoardConfigured: false,
  teamBoardEnvVar: '',
  teamBoardError: null,
};

/**
 * What a tab has behind it.
 *
 * Two of the three have nothing, and saying so is the point. Four empty
 * columns under a heading is a board that **ran and found nothing** — a
 * different claim from a board that cannot run, and the more reassuring of the
 * two. `ArrivalDialog` records the same distinction in its own words: *"no
 * workflows" and "could not ask" are two very different states and one
 * appearance is how 27 was reported*.
 *
 * The two sentences differ because the two states differ. One is a connection
 * this product supports and nobody has configured; the other is a connection
 * this product does not have yet.
 *
 * ## And a third state, since `team-board-and-gap-reports/04`
 *
 * *Configured, and here are the cards.* `02` and `03` made something able to
 * point at a shared board, so this is a function of **state** and not of the
 * tab id alone — two of the three tabs can be `board`, and which ones depends
 * on configuration. `github` is the one that cannot, whatever the environment
 * says, because no store exists behind it.
 *
 * The argument has a default, which is why the older test needed no edit: an
 * unanswered question reads as unconfigured, and the unconfigured answer is
 * word for word the one it always was, plus the variable to set.
 */
export function boardTabState(tab: BoardTabId, config: BoardConfig = UNANSWERED): BoardTabState {
  switch (tab) {
    case 'workflows':
      return { kind: 'board' };
    case 'osgEngineering':
      if (config.teamBoardConfigured && config.teamBoardError) {
        return unopenable(config.teamBoardError);
      }
      if (config.teamBoardConfigured) return { kind: 'board' };
      return {
        kind: 'unavailable',
        title: 'Not configured',
        body:
          'This tab would list what a patrol found in the engineering source a project ' +
          'points at. Nothing points at one yet, so there is nothing to list — and an ' +
          'empty board here would read as a patrol that ran and came back clean.' +
          // The half that makes the sentence actionable — `CLAUDE.md`'s Ollama
          // rule on a surface: never leave a maintainer with "not configured"
          // and no name to configure. Appended rather than woven in, so the
          // original sentence stays the sentence its own test pins, and
          // omitted when nothing has told us the name yet rather than
          // inventing one.
          (config.teamBoardEnvVar ? ` Set ${config.teamBoardEnvVar} and restart to use one.` : ''),
      };
    case 'github':
      return {
        kind: 'unavailable',
        title: 'Not available',
        body:
          'This product has no GitHub connection yet. When it has one, this tab shows ' +
          'what the patrol found there; until then it shows this, because four empty ' +
          'columns would be a claim rather than a state.',
      };
  }
}

/**
 * ## And a fourth state, since `team-board-and-gap-reports/18`
 *
 * *Configured, and this server could not open it.* The owner upgraded with an
 * extras line that lacked the board's driver, so the backend answered
 * `configured: true`, this tab drew four empty columns, and the real reason
 * arrived as a traceback in the terminal once per stream reconnect.
 *
 * Four empty columns here is the worst form of the claim-versus-state mistake
 * this module exists to prevent: not *a patrol ran and found nothing*, but
 * *the findings exist and you are looking at the wrong table*.
 *
 * The sentence is the backend's, unedited — it names the variable, what is
 * wrong, and the command that repairs **this** installation, none of which a
 * browser can know. What is added here is the frame a reader needs around it:
 * which tab this is about, and that a restart is what applies the fix,
 * because the board is opened once at startup and not per request.
 */
function unopenable(error: string): BoardTabState {
  // The backend puts the command on its own line, because it is the only
  // thing that knows where its prose ends (`osg-agent-experience/83`). So the
  // split is on that newline — never on a guess about what a command looks
  // like, which is the parse that breaks the first time the sentence changes.
  const [prose = '', ...rest] = error.split('\n');
  const command = rest.join('\n').trim();
  return {
    kind: 'unavailable',
    title: 'Board unavailable',
    body:
      'This tab would list what a patrol found in the engineering source this ' +
      'project points at. Something points at one, and this server could not open ' +
      'it — so an empty board here would be somebody else\u2019s cards missing, not ' +
      'a patrol that came back clean. It is opened once, at startup, so restart ' +
      'after fixing it. The server said: ' +
      prose.trim(),
    ...(command ? { command } : {}),
  };
}
