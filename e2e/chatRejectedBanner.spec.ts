import { expect, test } from '@playwright/test';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * `launch-readiness` 33 — ticket 25's banner ("The answer below is one our
 * reviewer rejected…") rendered on every chat turn, including graderless
 * runs where the backend sends `publishedRejected: false` (stranger run
 * three, 2026-08-24). The backend was correct; `.rejected-banner`'s CSS set
 * `display: flex` unconditionally, which — being an author rule — overrides
 * the UA `[hidden] { display: none }` regardless of the `hidden` attribute
 * `rejectedBanner.hidden = !d.publishedRejected` was toggling in JS. So the
 * banner was visible from the moment `turnEl()` created it, before any
 * `done` frame arrived.
 *
 * This loads `chat.html` directly (no backend, no network) and drives the
 * exact DOM node the page's own `stream()` function manipulates, so the
 * assertion is about the real cascade a browser applies — not a photograph
 * and not a re-implementation of the CSS in JS.
 */
test('the rejected banner is hidden until publishedRejected is true, and hidden again when it is false', async ({ page }) => {
  const file = path.join(__dirname, '..', 'backend', 'openstategraph', 'api', 'static', 'chat.html');
  await page.goto('file://' + file);

  const created = await page.evaluate(() => {
    const el = (window as any).turnEl('does the fixture ever answer?');
    const banner = el.querySelector('.rejected-banner');
    return getComputedStyle(banner).display;
  });
  // Freshly created turn, before any frame has arrived: must not show.
  expect(created).toBe('none');

  const whenPublishedRejectedIsFalse = await page.evaluate(() => {
    const banner = document.querySelector('.rejected-banner') as HTMLElement;
    banner.hidden = !false; // mirrors line 1444: rejectedBanner.hidden = !d.publishedRejected
    return getComputedStyle(banner).display;
  });
  expect(whenPublishedRejectedIsFalse).toBe('none');

  const whenPublishedRejectedIsTrue = await page.evaluate(() => {
    const banner = document.querySelector('.rejected-banner') as HTMLElement;
    banner.hidden = !true;
    return getComputedStyle(banner).display;
  });
  expect(whenPublishedRejectedIsTrue).toBe('flex');
});
