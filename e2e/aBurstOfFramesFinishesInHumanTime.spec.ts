import { expect, test } from '@playwright/test';

/**
 * `the-cost-of-one-more/20` — ten thousand unpaced `update` frames reach their
 * answer.
 *
 * The sibling spec next to this one asks whether the editor **survives** a
 * burst; `15` closed that. This one asks how long the burst takes, which `15`
 * left open and measured as a wall: 100 / 300 / 600 / 2,000 frames all
 * finished in tens of milliseconds, and 3,000, 5,000 and 10,000 did not finish
 * inside five, seven and six minutes respectively.
 *
 * There was no cliff. Measured against this worktree's own production build,
 * one size at a time, the burst was a clean quadratic all the way down — 500
 * frames 8.5 s, 1,000 32.4 s, 1,500 71.2 s, 2,000 128.6 s, ×3.8 per doubling.
 * The apparent step between two and three thousand was the five-minute budget
 * crossing the curve, not the curve changing shape. `20`'s Resolution carries
 * the profile that says where the time went.
 *
 * **This assertion is a deadline, not a ratio** — the distinction
 * `aScalingGateIsCountedNeverTimed.test.ts` draws, and it is the reason this
 * is allowed to be a clock at all. It does not measure speed and it has no
 * opinion about a constant factor: it asks whether ten thousand frames reach
 * an answer, and the two states it separates are three orders of magnitude
 * apart. Before the fix this run did not finish in six minutes and its own
 * two-minute harness budget expired with the tab still blocked; after it, it
 * finishes in **8.6 s**. The timeout below is fourteen times that, so a busy
 * machine cannot fail it and a return to the quadratic cannot pass it.
 */
const FRAMES = 10_000;

test.setTimeout(120_000);

test('ten thousand update frames arriving with no yield reach their answer', async ({ page }) => {
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

  await page.goto('/?w=chinook-assistant');
  await page.waitForTimeout(2500);

  const ask = page.locator('[aria-label*="Ask" i], button[title*="Ask" i]').first();
  if (await ask.count()) await ask.click();
  const composer = page.locator('textarea, [contenteditable="true"]').first();
  await composer.click();
  await composer.fill('burst');
  await page.keyboard.press('Meta+Enter');

  // `textContent`, never `innerText`. `20` suspected the instrument of owning
  // some of the five minutes, and the measurement said it owned none of them —
  // 1,000 frames took 30.9 s read with `innerText` and 31.2 s read with
  // `textContent`, because the read only ever succeeds once, after the main
  // thread is already free. `textContent` is kept anyway: it forces no layout,
  // so the harness cannot acquire a cost later that this note says it does not
  // have.
  const body = await page.evaluate(() => document.body.textContent ?? '', { timeout: 100_000 });

  expect(body).not.toContain('hit an unrecoverable error');
  expect(body).toContain('burst finished');
  // Every frame is still a row: coalescing changes when the panel commits, not
  // what it holds.
  const rows = await page.evaluate(() => document.querySelectorAll('.ask__trace-output').length);
  expect(rows).toBe(FRAMES);
});
