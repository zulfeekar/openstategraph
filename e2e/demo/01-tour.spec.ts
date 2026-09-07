import { defineScene, beat, hideInspector } from './support/scene';

/** Scene 1 — the left pane. What this thing is made of, in ten seconds. */
const { test, expect } = defineScene({ order: '01', name: 'tour', speed: 3 });

test('the palette scrolls through packages, tools and node families', async ({
  stage: page,
}) => {
  await page.goto('/');
  await expect(page.locator('.palette')).toBeVisible();
  await hideInspector(page);
  await beat(page, 1200);

  const palette = page.locator('.panel--left .panel__body').first();
  const box = await palette.boundingBox();
  if (!box) throw new Error('the left panel has no box');

  // Over the panel, not over the canvas. A wheel event on the paper zooms.
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 14 });
  await beat(page, 500);

  for (let i = 0; i < 22; i += 1) {
    await page.mouse.wheel(0, 130);
    await page.waitForTimeout(90);
  }
  await beat(page, 900);
  for (let i = 0; i < 12; i += 1) {
    await page.mouse.wheel(0, -230);
    await page.waitForTimeout(70);
  }
  await beat(page, 800);
});
