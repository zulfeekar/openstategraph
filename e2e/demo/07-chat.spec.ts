import { defineScene, beat, reachAndClick, slowType } from './support/scene';

/**
 * Scene 7 — the other surface, the one a customer sees.
 *
 * `/` is the editor and `/chat` is the product built on the same `/api`. Every
 * scene before this one is a builder's view; this is what the builder ships.
 * Nothing here mentions a node, a port or a superstep — a question goes in, the
 * router picks a workflow, the live flow draws what is running, and an answer
 * comes back with the SQL it used.
 *
 * Real time, unlike the builder's film. This one is short on its own — a
 * question, a route, a diagram, an answer — and every second of it is the
 * thing being sold. Speeding it up would save ten seconds and cost the
 * viewer the ability to read the answer, which is the only reason to watch.
 */
const { test, expect } = defineScene({ film: 'chat', order: '07', name: 'chat', speed: 1 });

const QUESTION = 'Which genre earns the most revenue?';

test('a customer asks, the router picks, the flow draws itself', async ({
  stage: page,
}) => {
  await page.goto('/chat');
  await expect(page.locator('textarea')).toBeVisible();
  await beat(page, 1600);

  await slowType(page, 'textarea', QUESTION);
  await beat(page, 700);
  await reachAndClick(page, 'button:has-text("Send")');

  // The live flow is a diagram of the run, drawn while it runs.
  await expect(page.locator('.flowchart').first()).toBeVisible({ timeout: 60_000 });
  await beat(page, 1500);

  // Over when Stop is gone. The transcript keeps growing after the first draft
  // — the grader sends it back once — so waiting on text would cut away from
  // the interesting half.
  await expect
    .poll(async () => page.getByRole('button', { name: 'Stop' }).count(), {
      timeout: 180_000,
      intervals: [1000],
    })
    .toBe(0);
  await beat(page, 2500);

  const transcript = await page.locator('body').innerText();
  expect(transcript.length).toBeGreaterThan(QUESTION.length + 200);
  await beat(page, 2000);
});
