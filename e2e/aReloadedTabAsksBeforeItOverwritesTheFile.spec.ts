import { expect, test, type Page, type Route } from '@playwright/test';

/**
 * `osg-agent-experience/68` — **a reload wrote its own old draft over a file a
 * CLI session had rewritten, and nobody pressed anything.**
 *
 * ## Why this is an e2e and not another unit test
 *
 * The unit cases in `src/app/aReloadedTabAsksBeforeItOverwritesTheFile.test.ts`
 * call `ensureDiskBaseline` directly. They cannot see the thing that made this
 * a data-loss blocker rather than a wrong return value: the write was fired by
 * the *restore itself*. `importJSON` raises `controller.onChange`, disk
 * autosave is listening from mount, and so a page load with no gesture in it
 * at all reached `PUT`. Only a real page, reloaded, with a real autosave
 * effect running, puts those pieces in the same room.
 *
 * ## "The file on disk" is the PUT, and that is deliberate
 *
 * The backend is stubbed with `page.route`, so nothing here touches
 * `workflows/`. The editor's only way to change the file is
 * `PUT /api/workflows/<slug>`, so "unchanged on disk" is exactly "no PUT was
 * issued" — and stating it that way is what lets this run on a CI job that has
 * Node and no Python. A version that needed a live backend would be a spec
 * that never ran, which is the state `pages.yml` is in and not a model to
 * copy.
 *
 * The reproduction it encodes is the one performed in the browser on
 * 2026-09-05: open the package, edit it (the edit is autosaved, so draft and
 * file agree), rewrite the file underneath, reload.
 */

const SLUG = 'a-reloaded-tab-probe';

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

/**
 * A backend holding one package, and counting every write attempt.
 *
 * `state.onDisk` is reassigned between page loads to stand for the CLI session
 * that rewrote the file. Everything else answers the minimum the editor needs
 * to open a workflow without an error path of its own confusing the result.
 */
async function stubBackend(
  page: Page,
  state: { onDisk: unknown; digest: string; writes: unknown[] },
): Promise<void> {
  const json = (route: Route, body: unknown): Promise<void> =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  // **Registered first, and that is load-bearing.** Playwright matches routes
  // in reverse registration order, so the catch-all has to go in before the
  // specific one or it swallows every workflow request — which it did, and the
  // symptom was a blank canvas rather than an error.
  //
  // It also means no request in this spec escapes to a real server: the dev
  // build points at a backend origin of its own, and every `/api/` call is
  // answered here.
  await page.route('**/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  );

  await page.route('**/api/workflows**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;

    if (route.request().method() === 'PUT') {
      state.writes.push(route.request().postDataJSON());
      state.digest = `after-write-${state.writes.length}`;
      return json(route, { slug: SLUG, digest: state.digest });
    }
    if (path.endsWith('/summary')) {
      return json(route, {
        slug: SLUG,
        name: 'Probe',
        savedAt: '2026-09-05T10:10:00+00:00',
        // **Moves with the document, because a real one does.**
        // `workflow_store.digest_of` is a content hash, so a stub holding one
        // constant while `state.onDisk` is reassigned describes a backend that
        // does not exist — and `osg-agent-experience/69` gave that difference
        // a consequence: a draft records the revision it was taken from, and a
        // file still holding that revision is a file nobody else touched, so
        // the draft is restored silently. Against the frozen digest this spec
        // asserted a dialog for a file the backend was claiming had not
        // changed.
        digest: state.digest,
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
      return json(route, { slug: SLUG, document: state.onDisk });
    }
    if (path.endsWith('/api/workflows')) return json(route, { workflows: [] });
    return json(route, {});
  });

}

test('a reload writes nothing to the file until the user chooses', async ({ page }) => {
  const state = {
    onDisk: documentWith('Probe', 'ORIGINAL PROMPT.'),
    digest: 'rev-1',
    writes: [] as unknown[],
  };
  await stubBackend(page, state);

  // 1 — open it, and make an unsaved edit. Disk autosave writes that edit, so
  // this tab's draft and the file agree, which is the state every tab is in.
  await page.goto(`/?w=${SLUG}`);
  await expect(page.locator('[data-node-id]').first()).toBeVisible();
  const name = page.getByLabel('Name').first();
  await name.fill('Probe DRAFT EDIT');
  await name.blur();
  await expect.poll(() => state.writes.length).toBeGreaterThan(0);

  // 2 — a CLI session rewrites the file. The tab knows nothing about it.
  state.onDisk = documentWith('CLI Rewrote The File', 'CLI REWROTE THIS PROMPT.');
  state.digest = 'rev-2';
  const before = state.writes.length;

  // 3 — the reload. This is the whole defect: no drag, no keystroke, no Save.
  await page.reload();

  // The choice is on screen, naming the file rather than describing it in the
  // abstract — a reader has to be able to tell which of two documents is which.
  await expect(page.getByText('This workflow changed on disk')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Take the file' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Keep my edits' })).toBeVisible();

  // …and the file is untouched.
  //
  // **This assertion alone is not enough, and that is worth stating rather
  // than leaving implied.** Verified by mutation: with the comparison in
  // `ensureDiskBaseline` disabled, this line stayed green — the dialog is
  // modal, so nothing fires `controller.onChange` while it is up, and the
  // write the ticket describes arrives on the *next* change. A test that
  // cannot see the defect it names is a test of itself.
  //
  // So the sequence continues past the dialog. Escape is the deliberate third
  // outcome — write nothing, decide nothing — and an edit after it is exactly
  // the keystroke that used to carry the draft to disk. This is the line that
  // goes red when the fix is removed.
  await page.waitForTimeout(1500);
  expect(state.writes.length).toBe(before);

  await page.keyboard.press('Escape');
  await page.getByLabel('Name').first().fill('Edited After Deferring');
  await page.getByLabel('Name').first().blur();
  await page.waitForTimeout(2000);
  expect(state.writes.length).toBe(before);

  // 4 — the user reloads and takes the file. The canvas becomes the file, and
  // still nothing is written: there is now nothing to write.
  await page.reload();
  await page.getByRole('button', { name: 'Take the file' }).click();
  await expect(page.getByLabel('Name').first()).toHaveValue('CLI Rewrote The File');
  await page.waitForTimeout(1500);
  expect(state.writes.length).toBe(before);
});
