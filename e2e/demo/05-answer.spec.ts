import { defineScene, beat, hideInspector, reachAndClick } from './support/scene';

/**
 * Scene 5 — the payoff, at real speed.
 *
 * One model call carries both halves of it: the answer arriving, and then the
 * timeline that says what the run actually did. Splitting them would cost a
 * second live run for a cut the viewer never sees.
 *
 * Everything before `cut()` is setup the viewer should not watch, and the film
 * joins at the send.
 */
const { test, expect, cut } = defineScene({ film: 'demo', order: '05', name: 'answer', speed: 1 });

const QUESTION = 'How many customers are in the database?';

test('the answer streams in and the timeline says what ran', async ({
  stage: page,
}) => {
  await page.goto('/?w=chinook-assistant');
  await expect(page.locator('.node__title').first()).toBeVisible({ timeout: 20_000 });
  await hideInspector(page);
  await page.getByRole('button', { name: 'Ask the workflow' }).click();
  await expect(page.locator('.ask__composer-input textarea')).toBeVisible();
  // `fill`, not typing: scene 4 already showed the typing.
  await page.locator('.ask__composer-input textarea').fill(QUESTION);
  await page.waitForTimeout(400);

  cut();

  await reachAndClick(page, '.ask__composer-send');
  await expect(page.locator('.ask__thread')).toContainText(QUESTION, {
    timeout: 30_000,
  });

  // **Wait for the run to end, not for the text to grow.** An earlier version
  // polled the thread's length, and the echoed question alone cleared the
  // threshold — so the film cut away mid-run, with the cards still lighting up
  // and a Stop button on screen. A run is over when Stop is gone.
  await expect
    .poll(async () => page.getByRole('button', { name: 'Stop' }).count(), {
      timeout: 180_000,
      intervals: [1000],
    })
    .toBe(0);
  // The last tokens land after the transport closes.
  await beat(page, 2500);

  // The answer is a model's wording, so this asserts that one arrived rather
  // than what it says: the thread now holds more than the question.
  const thread = await page.locator('.ask__thread').innerText();
  expect(thread.length).toBeGreaterThan(QUESTION.length + 60);

  await reachAndClick(page, 'button[aria-label="Toggle run timeline"]');
  await beat(page, 3500);
});
