import { expect, test } from '@playwright/test';

/**
 * `the-cost-of-one-more/15` — a burst of `update` frames exceeded React's
 * nested-update limit and the editor was replaced by its error boundary.
 *
 * This is the **only** shape of test that can see the defect, and that is a
 * statement about the defect rather than a preference. A render loop has no
 * unit: it is React's reconciler counting commits that were scheduled from
 * inside a commit, so reproducing it needs a real React, real passive-effect
 * flushing, and a real stream whose chunks arrive with no macrotask between
 * them. `vite.config.ts` runs the unit suite in `node` with no DOM on
 * purpose, so it cannot mount a component; a unit test could only have
 * asserted that a callback is memoised, which is a different claim and one
 * the loop survives (`runningReportIsAboutState.test.ts` pins the seam and
 * says so).
 *
 * The stub replaces `window.fetch` for the stream door only — no model is
 * called, no backend is needed for this route — and enqueues every frame
 * synchronously inside `start()`, which is the point: a fast local backend
 * and a replayed recording both deliver a chunk per microtask with no yield
 * to the event loop, and that is the condition under which React's
 * same-value bail-out never applies.
 *
 * Before the fix this failed at roughly frame fifty with `Maximum update
 * depth exceeded` (minified: React error #185) and the boundary's
 * "OpenStateGraph hit an unrecoverable error" on screen.
 */
const FRAMES = 2000;

test('two thousand update frames arriving with no yield leave the editor alive', async ({ page }) => {
  await page.addInitScript((frames: number) => {
    const real = window.fetch.bind(window);
    window.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : String((input as Request).url ?? input);
      if (!url.includes('/api/runs/stream')) return real(input as RequestInfo, init);
      const enc = new TextEncoder();
      const frame = (name: string, data: unknown) =>
        enc.encode(`event: ${name}\ndata: ${JSON.stringify(data)}\n\n`);
      const body = new ReadableStream({
        start(controller) {
          controller.enqueue(frame('started', { threadId: 'burst', elapsedMs: 0 }));
          for (let i = 0; i < frames; i++) {
            controller.enqueue(frame('update', { node: 'router', output: `step ${i}`, elapsedMs: i }));
          }
          controller.enqueue(frame('done', { answer: 'burst finished', elapsedMs: frames }));
          controller.close();
        },
      });
      return Promise.resolve(
        new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } }),
      );
    }) as typeof window.fetch;
  }, FRAMES);

  const reactErrors: string[] = [];
  const record = (text: string) => {
    if (/Maximum update depth exceeded|Minified React error #185/.test(text)) reactErrors.push(text);
  };
  page.on('pageerror', (error) => record(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') record(message.text());
  });

  await page.goto('/?w=chinook-assistant');
  await page.waitForTimeout(2500);

  const ask = page.locator('[aria-label*="Ask" i], button[title*="Ask" i]').first();
  if (await ask.count()) await ask.click();
  const composer = page.locator('textarea, [contenteditable="true"]').first();
  await composer.click();
  await composer.fill('burst');
  await page.keyboard.press('Meta+Enter');

  const body = await page.evaluate(() => document.body.innerText, { timeout: 120_000 });

  expect(reactErrors, reactErrors[0] ?? '').toHaveLength(0);
  // The boundary's own headline — the thing a user actually saw.
  expect(body).not.toContain('hit an unrecoverable error');
  // Alive is not enough: the run must have reached its end.
  expect(body).toContain('burst finished');
});
