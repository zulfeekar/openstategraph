import { expect, test, type Page } from '@playwright/test';

/**
 * The team tab, in a browser — `team-board-and-gap-reports/11`.
 *
 * `04` made the *OSG Engineering* tab a function of the environment rather
 * than of the tab id, and left the browser pass unwritten. What vitest can
 * reach is `boardTabState`, a pure function over a config record, and
 * `aTeamTabWithSomethingBehindItSaysSo.test.ts` already pins both of its
 * answers. What no unit test in this repository can reach is the wiring
 * between them: `useBoardConfig` reads `GET /api/health`, maps two snake_case
 * fields onto two camelCase ones, hands the record to `AppShell`, which hands
 * it to `PatrolBoard`, which asks `boardTabState`. Six seams, none of which a
 * `boardTabState` test can see — and vitest's environment here is `node` with
 * `include: ['src/**\/*.test.ts']`, so there is no DOM to render the chain
 * into even if one wanted to.
 *
 * So this drives the real product: open the board, switch to the tab, read
 * what a maintainer would read.
 *
 * ## Why `/api/health` is stubbed rather than configured
 *
 * The state under test is *what the backend said*, and the two answers differ
 * by one boolean. Setting the real variable would mean restarting a server
 * between two cases and would make the spec a test of this machine's
 * environment; `page.route` makes both cases available in one run against any
 * build. It also keeps the spec honest about the seam it is testing — the
 * payload keys are the wire's, `team_board_configured` and `team_board_env`,
 * so a rename on either side fails here rather than silently reading
 * `undefined` as *not configured*, which is exactly the sentence this tab
 * shows when nothing is wrong.
 *
 * The variable's *name* is a string this spec asserts is echoed through, never
 * a constant it imports: the whole claim is that the value the backend chose
 * reaches the surface, and asserting against an import would pass if the chain
 * dropped it and the view had its own copy.
 */

const HEALTH = '**/api/health';
const CARDS = '**/api/kanban/cards*';

/** The tab's third state needs rows, and rows must not come from whatever the
 *  machine's store happens to hold. Refusing the read leaves `useBoardRows`
 *  with `null` — *nobody answered*, not *nothing there* — and `PatrolBoard`
 *  falls back to its own fixture, which is deterministic on any checkout. */
async function stubBoard(page: Page, teamBoardConfigured: boolean, envVar: string) {
  await page.route(HEALTH, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'ok',
        team_board_configured: teamBoardConfigured,
        team_board_env: envVar,
      }),
    }),
  );
  await page.route(CARDS, (route) => route.fulfill({ status: 503, body: '' }));
}

/** Everything is scoped to the dialog. `.panel-empty` is the shared primitive
 *  the inspector uses too, so an unscoped locator matches "Nothing selected"
 *  on the canvas behind the board and resolves to two elements. */
function board(page: Page) {
  return page.getByRole('dialog');
}

async function openBoard(page: Page, tab: 'OSG Engineering' | 'GitHub') {
  await page.goto('/');
  await page.getByRole('button', { name: 'Patrol board' }).click();
  await board(page).getByRole('tab', { name: tab }).click();
}

async function openTeamTab(page: Page) {
  await openBoard(page, 'OSG Engineering');
}

test('with no shared board configured, the team tab names the variable that would configure one', async ({
  page,
}) => {
  await stubBoard(page, false, 'OPENSTATEGRAPH_KANBAN_URL');
  await openTeamTab(page);

  const notice = board(page).locator('.panel-empty');
  await expect(notice).toBeVisible();
  await expect(notice).toContainText('Not configured');
  // The half `04` added, and the half that makes the sentence actionable —
  // `CLAUDE.md`'s Ollama rule on a surface: never "not configured" with no
  // name to configure.
  await expect(notice).toContainText('Set OPENSTATEGRAPH_KANBAN_URL and restart');
  // The name, never the value. A URI with a password in it must not reach a
  // surface, and the endpoint is typed so that it cannot — this fails if that
  // ever stops being true.
  await expect(page.locator('body')).not.toContainText('postgresql://');
  await expect(page.locator('.patrol-board')).toHaveCount(0);
});

test('the name the backend gives is the name the tab prints', async ({ page }) => {
  // A different variable, so a view carrying its own hardcoded copy of the
  // name would pass the case above and fail this one.
  await stubBoard(page, false, 'A_DIFFERENT_VARIABLE_ENTIRELY');
  await openTeamTab(page);

  await expect(board(page).locator('.panel-empty')).toContainText(
    'Set A_DIFFERENT_VARIABLE_ENTIRELY and restart',
  );
});

test('with a shared board configured, the team tab is a board — four columns and a card', async ({
  page,
}) => {
  await stubBoard(page, true, 'OPENSTATEGRAPH_KANBAN_URL');
  await openTeamTab(page);

  await expect(board(page).locator('.panel-empty')).toHaveCount(0);
  const columns = page.locator('.patrol-board');
  await expect(columns).toBeVisible();
  for (const column of ['Detected', 'Needs You', 'In Progress', 'Resolved']) {
    await expect(columns).toContainText(column);
  }
  await expect(columns.locator('.patrol-card').first()).toBeVisible();
});

test('the GitHub tab is unavailable whatever the environment says', async ({ page }) => {
  // The clause `boardTabState` makes and this is the browser's copy of: the
  // team variable is not a master switch. `github` has no store behind it, so
  // a configured board must not turn its tab on — which is the mistake a
  // single `configured` boolean invites at the view layer.
  await stubBoard(page, true, 'OPENSTATEGRAPH_KANBAN_URL');
  await openBoard(page, 'GitHub');

  await expect(board(page).locator('.panel-empty')).toContainText('Not available');
  await expect(page.locator('.patrol-board')).toHaveCount(0);
});
