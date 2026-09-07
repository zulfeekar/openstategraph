import { defineScene, beat, hideInspector, reachAndClick } from './support/scene';

/** Scene 2 — a workflow exists in one drag. Input, agent, output, wired. */
const { test, expect } = defineScene({ order: '02', name: 'starter', speed: 2 });

test('dragging Starter flow onto the canvas places a wired workflow', async ({
  stage: page,
}) => {
  await page.goto('/');
  await expect(page.locator('.palette')).toBeVisible();
  await hideInspector(page);
  await beat(page, 900);

  // Find it by name rather than by position: the palette's order is data.
  const search = page.locator('.palette__search input').first();
  await search.click();
  await search.pressSequentially('starter', { delay: 70 });
  await beat(page, 700);

  const item = page.getByRole('button', { name: /^Starter flow/ }).first();
  const from = await item.boundingBox();
  const stage = await page.locator('.canvas-stage').boundingBox();
  if (!from || !stage) throw new Error('palette item or canvas has no box');

  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2, { steps: 16 });
  await beat(page, 400);
  await page.mouse.down();
  await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2, {
    steps: 28,
  });
  await beat(page, 350);
  await page.mouse.up();

  await expect(page.locator('.node__title').first()).toBeVisible({ timeout: 15_000 });
  await beat(page, 700);
  await reachAndClick(page, 'button[aria-label="Fit to screen"]');
  await beat(page, 1400);
});
