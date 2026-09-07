import { defineScene, beat, hideInspector, reachAndClick, slowType } from './support/scene';

/** Scene 4 — the question. Typed, not pasted. */
const { test, expect } = defineScene({ film: 'demo', order: '04', name: 'ask', speed: 2 });

export const QUESTION = 'How many customers are in the database?';

test('the chat opens and takes a question', async ({ stage: page }) => {
  await page.goto('/?w=chinook-assistant');
  await expect(page.locator('.node__title').first()).toBeVisible({ timeout: 20_000 });
  await hideInspector(page);
  await beat(page, 900);

  await reachAndClick(page, 'button[aria-label="Ask the workflow"]');
  await expect(page.locator('.ask__composer-input textarea')).toBeVisible();
  await beat(page, 600);

  await slowType(page, '.ask__composer-input textarea', QUESTION);
  await beat(page, 1200);
});
