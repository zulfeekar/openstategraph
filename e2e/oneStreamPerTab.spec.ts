import { expect, test, type BrowserContext, type Route } from '@playwright/test';

/**
 * `osg-agent-experience/71` — **a third SSE stream per tab saturates the
 * browser's connection budget.**
 *
 * A browser allows six concurrent HTTP/1.1 connections per origin. An editor
 * tab held one per live subject — `/api/events` for the catalogue,
 * `/api/kanban/patrol/events` for the job chip, `/api/kanban/events` while a
 * board was open — and `69`'s per-package watcher would have been another.
 * Staged on 2026-09-05 against the running editor with three: **two** tabs on
 * one workflow saturated the budget, the last `EventSource` sat at
 * `readyState 0` for minutes with `onopen` never firing, and an ordinary
 * `fetch('/api/workflows/<slug>/summary')` in that tab did not complete within
 * 45 seconds — so the five-second file watch, which is what tells a tab its
 * package was deleted, stopped answering too.
 *
 * ## What only a browser can say
 *
 * `src/oneStreamPerTab.test.ts` counts the doors in the source and drives the
 * client objects; neither can see how many sockets a real page ends up
 * holding, because that depends on when React mounts each subscriber and what
 * the reconcile does in between. So this counts them in Chromium: every
 * `EventSource` a page constructs and every one it closes, from an init script
 * that runs before the bundle does.
 *
 * **One *open* at a time is the claim, not one construction ever.** A tab
 * deep-linked to `?w=<slug>` learns its slug asynchronously — the document has
 * to load first — so the connection is reopened once with `slug=` added, and
 * that is a reconnect rather than a second socket. The assertion is therefore
 * on what is live, with a bound on the churn beside it so a regression that
 * reopens on every render is still a red test.
 *
 * ## Two contexts, not two pages
 *
 * `69`'s spec's argument, unchanged: two pages of one context share
 * `localStorage`, so the second tab restores the first tab's draft and every
 * assertion becomes true for the wrong reason. The budget this measures is
 * per origin per *browser process*, so two contexts still contend for it —
 * which is the case the ticket is named after.
 */

const SLUG = 'one-stream-probe';

function documentWith(name: string): unknown {
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
        data: { systemPrompt: 'ORIGINAL PROMPT.', tier: 'react', rulesMode: 'extend' },
        title: 'One',
      },
    ],
    edges: [],
  };
}

/** What the init script publishes about this page's live streams. */
interface StreamCensus {
  opened: string[];
  live: string[];
}

async function countStreams(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    const opened: string[] = [];
    const live = new Set<string>();
    const Real = window.EventSource;
    // A subclass rather than a wrapper: the editor never reads a member this
    // does not have, and `instanceof` keeps working for anything that does.
    class Counted extends Real {
      constructor(url: string | URL, init?: EventSourceInit) {
        super(url, init);
        opened.push(String(url));
        live.add(String(url));
      }
      close(): void {
        live.delete(String(this.url));
        super.close();
      }
    }
    window.EventSource = Counted as unknown as typeof EventSource;
    (window as unknown as { __streams: () => StreamCensus }).__streams = () => ({
      opened: [...opened],
      live: [...live],
    });
  });
}

/**
 * The backend, stubbed — nothing here touches `workflows/`, so this runs on a
 * job with Node and no Python (`68`'s spec's own argument).
 *
 * `/api/events` answers as a real `text/event-stream`. `route.fulfill` sends a
 * complete response, so the client sees the comment frame, the response ends,
 * and `EventSource` reconnects — which is exactly the behaviour being counted:
 * a reconnect reuses the object, so the construction count does not move.
 */
async function stubBackend(context: BrowserContext, digest: () => string): Promise<void> {
  const json = (route: Route, body: unknown): Promise<void> =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });

  // Registered first: Playwright matches in reverse registration order, so a
  // catch-all has to go in before the specific handlers.
  await context.route('**/api/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }),
  );

  await context.route('**/api/events**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: { 'cache-control': 'no-store' },
      body: ': connected\n\n',
    }),
  );

  await context.route('**/api/workflows**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/summary')) {
      return json(route, {
        slug: SLUG,
        name: 'Probe',
        savedAt: '2026-09-05T10:10:00+00:00',
        digest: digest(),
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
      return json(route, { slug: SLUG, document: documentWith('Probe') });
    }
    if (path.endsWith('/api/workflows')) return json(route, { workflows: [] });
    return json(route, {});
  });
}

test('two tabs on one workflow hold one live stream each', async ({ browser }) => {
  const digest = () => 'rev-1';
  const censusOf = async (page: {
    evaluate: (fn: string) => Promise<unknown>;
  }): Promise<StreamCensus> =>
    (await page.evaluate('window.__streams()')) as StreamCensus;

  const first = await browser.newContext();
  await countStreams(first);
  await stubBackend(first, digest);
  const tabA = await first.newPage();
  await tabA.goto(`/?w=${SLUG}`);
  await expect(tabA.locator('[data-node-id]').first()).toBeVisible();

  const second = await browser.newContext();
  await countStreams(second);
  await stubBackend(second, digest);
  const tabB = await second.newPage();
  await tabB.goto(`/?w=${SLUG}`);
  await expect(tabB.locator('[data-node-id]').first()).toBeVisible();

  for (const tab of [tabA, tabB]) {
    // The subject is added once the tab knows its slug, so wait for the state
    // this asserts rather than for a duration.
    await expect
      .poll(async () => (await censusOf(tab)).live.join(' '), { timeout: 15_000 })
      .toContain(`slug=${SLUG}`);

    const census = await censusOf(tab);

    // The ticket, in one assertion. Not "one EventSource was ever built" —
    // see the header — but one is open, which is what spends a connection.
    expect(census.live).toHaveLength(1);
    expect(census.live[0]).toContain('/api/events?');
    expect(census.live[0]).toContain('patrol=1');

    // And the churn is bounded, so a reconcile that reopened on every render
    // would fail here rather than pass the assertion above by luck.
    expect(census.opened.length).toBeLessThanOrEqual(3);
    for (const url of census.opened) expect(url).toContain('/api/events');
  }

  // The symptom the ticket actually reported, and the one a connection count
  // does not by itself rule out: with the budget gone, ordinary requests in
  // the last tab stopped completing. Forty-five seconds was the observed
  // stall; five is generous and still an order of magnitude inside it.
  for (const tab of [tabA, tabB]) {
    const elapsed = await tab.evaluate(async (slug: string) => {
      const started = performance.now();
      await fetch(`/api/workflows/${slug}/summary`);
      return performance.now() - started;
    }, SLUG);
    expect(elapsed).toBeLessThan(5_000);
  }

  await first.close();
  await second.close();
});
