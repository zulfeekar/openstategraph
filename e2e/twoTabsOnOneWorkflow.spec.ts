import { expect, test, type BrowserContext, type Route } from '@playwright/test';

/**
 * `osg-agent-experience/69` — **three tabs on one workflow did not see each
 * other's saves.**
 *
 * The owner, after `68`: *"a user opens three tabs on the same workflow, how
 * does each get the latest changes?"* Until this spec's subject shipped, they
 * did not: a tab that was not the writer learned nothing until its user
 * reloaded, and a reload is the gesture `68` is the ticket about.
 *
 * ## Why two browser contexts and not two pages
 *
 * Two pages of one context share `localStorage`, which is where the browser
 * draft and its write guard live — so a second tab restores the *first* tab's
 * draft, and the guard refuses its writes as a conflict before any of this
 * feature is reached. Every assertion below would then be true for the wrong
 * reason. Separate contexts are also the honest model of the case that
 * matters: the second writer is a `git pull`, the CLI or a coding agent as
 * often as it is a tab, and none of those share anything with this browser.
 *
 * The cost of separate contexts is that `BroadcastChannel` cannot carry the
 * news — it is per origin *per browser profile* — so what this exercises is
 * the transport that covers every writer and costs no connection: the
 * five-second `savedAt` poll, which receives the file's digest in the row it
 * already reads. The `BroadcastChannel` half is a latency optimisation over
 * the same decision and is asserted in
 * `src/app/aSecondTabSeesTheSave.test.ts`. Waiting the poll out is why the
 * timeouts below are twenty seconds rather than five.
 *
 * ## "The file on disk" is the PUT
 *
 * The backend is stubbed with `context.route`, so nothing here touches
 * `workflows/`, and the spec runs on a CI job that has Node and no Python —
 * `68`'s spec's own argument. The editor's only way to change the file is
 * `PUT /api/workflows/<slug>`, so "unchanged on disk" is exactly "no PUT was
 * issued by that tab".
 */

const SLUG = 'two-tabs-probe';

/** A document the editor can import, in the file's authored form. */
function documentWith(name: string, prompt: string): unknown {
  return {
    version: 3,
    name,
    settings: {},
    nodes: [
      {
        id: 'agent-one',
        type: 'agent.llm',
        position: { x: 200, y: 200 },
        size: { width: 252, height: 494 },
        parentId: null,
        data: { systemPrompt: prompt, tier: 'react', rulesMode: 'extend' },
        title: 'One',
      },
    ],
    edges: [],
  };
}

interface Disk {
  document: unknown;
  digest: string;
  /** Every PUT, tagged with the name it carried, so a writer is identifiable. */
  writes: { name: string }[];
}

/**
 * One package, shared by every context — the file both tabs are editing.
 *
 * The digest moves on every write, exactly as `package_digest` does, because
 * the whole feature turns on a tab being able to tell a revision it has from
 * one it does not.
 */
async function stubBackend(
  context: BrowserContext,
  disk: Disk,
  /** Whether this context's writes are currently being refused — a backend
   * blip, which is the ordinary way a tab comes to hold unsaved edits at all. */
  refuseWrites: () => boolean = () => false,
): Promise<void> {
  const json = (route: Route, body: unknown): Promise<void> =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  // Registered first — Playwright matches in reverse registration order, so
  // the catch-all has to go in before the specific one or it swallows every
  // workflow request (`68`'s spec paid for this).
  //
  // There is no stub for `GET /api/workflows/{slug}/events`, and its absence
  // is the point: the editor deliberately does not open that stream, because
  // a third long-lived connection per tab saturates a browser's six-per-origin
  // budget at two tabs — see `useExternalWorkflowChange`'s header for the
  // measurement. The catch-all answers it as JSON, an `EventSource` would
  // refuse that outright, and every assertion below still passes.
  await context.route('**/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  );

  await context.route('**/api/workflows**', async (route) => {
    const path = new URL(route.request().url()).pathname;

    if (route.request().method() === 'PUT') {
      if (refuseWrites()) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'the backend is having a moment' }),
        });
      }
      const body = route.request().postDataJSON() as { name?: string; document?: unknown };
      disk.writes.push({ name: body.name ?? '' });
      disk.document = body.document;
      disk.digest = `rev-${disk.writes.length + 1}`;
      return json(route, { slug: SLUG, digest: disk.digest });
    }
    if (path.endsWith('/summary')) {
      return json(route, {
        slug: SLUG,
        name: 'Probe',
        savedAt: '2026-09-05T10:10:00+00:00',
        digest: disk.digest,
        nodes: 1,
        edges: 0,
      });
    }
    if (path.endsWith('/capabilities')) {
      return json(route, {
        tools: [],
        functions: [],
        pluginTools: [],
        ambientTools: [],
        warnings: [],
      });
    }
    if (path.endsWith(`/api/workflows/${SLUG}`)) {
      return json(route, { slug: SLUG, document: disk.document });
    }
    if (path.endsWith('/api/workflows')) return json(route, { workflows: [] });
    return json(route, {});
  });
}

test('a second tab with no unsaved edits takes the new version without a reload', async ({
  browser,
}) => {
  const disk: Disk = {
    document: documentWith('Probe', 'ORIGINAL PROMPT.'),
    digest: 'rev-1',
    writes: [],
  };

  const watching = await browser.newContext();
  await stubBackend(watching, disk);
  const tabB = await watching.newPage();
  await tabB.goto(`/?w=${SLUG}`);
  await expect(tabB.locator('[data-node-id]').first()).toBeVisible();
  await expect(tabB.getByLabel('Name').first()).toHaveValue('Probe');

  // Somebody else writes the file. A whole context away, which is what the
  // CLI and an agent are — nothing is shared with the tab above but the file.
  const writing = await browser.newContext();
  await stubBackend(writing, disk);
  const tabA = await writing.newPage();
  await tabA.goto(`/?w=${SLUG}`);
  await expect(tabA.locator('[data-node-id]').first()).toBeVisible();
  const nameA = tabA.getByLabel('Name').first();
  await nameA.fill('Renamed By The Other Tab');
  await nameA.blur();
  await expect.poll(() => disk.writes.length).toBeGreaterThan(0);

  // The whole ticket, in one assertion: no reload, no gesture in this tab.
  await expect(tabB.getByLabel('Name').first()).toHaveValue('Renamed By The Other Tab', {
    timeout: 15_000,
  });
  // …and it was told, because a canvas that changes under somebody in silence
  // is the failure `68` is about with the arrow reversed.
  // `.first()` because the toast is announced in a live region as well as
  // drawn — two nodes, one sentence, which is the accessibility arrangement
  // rather than a duplicate notice.
  await expect(tabB.getByText(/was saved elsewhere/).first()).toBeVisible();

  await watching.close();
  await writing.close();
});

test('a second tab with unsaved edits is asked, and writes nothing until it answers', async ({
  browser,
}) => {
  // **Getting a tab into the "unsaved edits" state takes a refused write, and
  // that is a finding rather than a contrivance.** This editor autosaves to
  // the package on every edit, so a tab is dirty only inside the one-second
  // debounce or when the write did not land — which is exactly when it
  // matters, and is the state `45`'s conflict stand-down and every backend
  // blip produce. A spec that just typed and waited would be asserting the
  // clean path twice.
  const disk: Disk = {
    document: documentWith('Probe', 'ORIGINAL PROMPT.'),
    digest: 'rev-1',
    writes: [],
  };
  let refuseWrites = false;

  const watching = await browser.newContext();
  await stubBackend(watching, disk, () => refuseWrites);
  const tabB = await watching.newPage();
  await tabB.goto(`/?w=${SLUG}`);
  await expect(tabB.locator('[data-node-id]').first()).toBeVisible();

  // 1 — the backend stops accepting writes, and the user types. The edit is on
  // screen and nowhere else: this tab now holds the only copy of it.
  refuseWrites = true;
  const nameB = tabB.getByLabel('Name').first();
  await nameB.fill('My Unsaved Work');
  await nameB.blur();
  await tabB.waitForTimeout(2000);
  expect(disk.writes.length).toBe(0);

  // 2 — the backend comes back, and somebody else has rewritten the file in
  // the meantime. This tab's edit is not in it.
  refuseWrites = false;
  disk.document = documentWith('Rewritten Elsewhere', 'SOMEBODY ELSE WROTE THIS.');
  disk.digest = 'rev-99';

  // The question, in `68`'s dialog with this occasion's own sentence.
  await expect(tabB.getByText('This workflow changed on disk')).toBeVisible({ timeout: 20_000 });
  await expect(tabB.getByText(/Someone else just saved this workflow/)).toBeVisible();
  await expect(tabB.getByRole('button', { name: 'Take the file' })).toBeVisible();
  await expect(tabB.getByRole('button', { name: 'Keep my edits' })).toBeVisible();

  // **The dialog being up is not enough, and `68` paid to learn that.** It is
  // modal, so nothing fires `controller.onChange` while it stands and a write
  // would arrive on the *next* change. So the sequence continues past Escape
  // into the edit that would otherwise carry this tab's document over the file
  // it is being asked about — with the backend accepting writes again. This is
  // the line that goes red when the disarm before the offer is removed.
  await tabB.keyboard.press('Escape');
  await tabB.getByLabel('Name').first().fill('Edited After Deferring');
  await tabB.getByLabel('Name').first().blur();
  await tabB.waitForTimeout(2500);
  expect(disk.writes).toEqual([]);

  await watching.close();
});
