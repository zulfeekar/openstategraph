import { defineScene, beat, hideInspector, reachAndClick } from './support/scene';

/** Scene 3 — a real package opens. Fourteen nodes, nineteen links, no setup. */
const { test, expect } = defineScene({ order: '03', name: 'open', speed: 2 });

test('opening a package draws the whole workflow', async ({ stage: page }) => {
  await page.goto('/');
  await expect(page.locator('.palette')).toBeVisible();
  await hideInspector(page);
  await beat(page, 900);

  await reachAndClick(page, 'button[aria-label="Open Chinook Assistant"]');
  await expect(page.locator('.node__title').first()).toBeVisible({ timeout: 20_000 });
  await beat(page, 1000);

  // Fit first, so the viewer sees the size of the thing: fourteen nodes and
  // nineteen links do not fit legibly in a 1280-wide frame. Then zoom back in,
  // because a workflow nobody can read is a screenshot of a circuit board — the
  // scale lands in one beat and the detail has to follow it.
  await reachAndClick(page, 'button[aria-label="Fit to screen"]');
  await beat(page, 1600);

  // Ctrl and the wheel, not the zoom button and not the bare wheel. The button
  // steps about three points a click, which took three clicks to get from 32%
  // to 41% and left the cards as unreadable as they started. A bare wheel pans
  // the paper — the first attempt scrolled off into empty canvas and paused
  // run-following on the way. Ctrl and the wheel zooms toward the pointer,
  // about half again per tick, so three ticks turn 32% into a card a viewer
  // can read.
  const focus = page.locator('.node').nth(2);
  const box = await focus.boundingBox();
  if (!box) throw new Error('no node to zoom toward');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 20 });
  await beat(page, 400);
  await page.keyboard.down('Control');
  for (let i = 0; i < 3; i += 1) {
    await page.mouse.wheel(0, -120);
    await page.waitForTimeout(260);
  }
  await page.keyboard.up('Control');
  // Long enough for the "you took the wheel" toast to clear. It is honest — a
  // gesture did take over run-following — but there is no run here, so on film
  // it reads as an error the viewer cannot place.
  await beat(page, 5200);
});
