import { expect, test } from '@playwright/test';

/** The seeded demo is the fixture: it loads with no backend and no keys. */
test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('[data-node-id]').first()).toBeVisible();
});

test('the seeded demo renders nodes and links', async ({ page }) => {
  expect(await page.locator('[data-node-id]').count()).toBeGreaterThanOrEqual(3);
  expect(await page.locator('.joint-link').count()).toBeGreaterThanOrEqual(1);
});

test('clicking a node selects it and opens its inspector', async ({ page }) => {
  const card = page.locator('[data-node-id]').first();
  await card.click();
  // The inspector switches from the workflow view to the node view.
  await expect(page.locator('.inspector')).not.toContainText('Diagnostics');
});

test('dragging a node moves it and undo restores it', async ({ page }) => {
  const card = page.locator('[data-node-id]').first();
  const before = await card.boundingBox();
  if (!before) throw new Error('node card has no box');
  await page.mouse.move(before.x + before.width / 2, before.y + 10);
  await page.mouse.down();
  await page.mouse.move(before.x + before.width / 2 + 120, before.y + 90, { steps: 8 });
  await page.mouse.up();
  const after = await card.boundingBox();
  expect(Math.abs((after?.x ?? 0) - before.x)).toBeGreaterThan(40);

  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+z' : 'Control+z');
  const restored = await card.boundingBox();
  expect(Math.abs((restored?.x ?? 0) - before.x)).toBeLessThan(8);
});

test('auto-arrange works in both flow directions', async ({ page }) => {
  await page.getByLabel('Arrange automatically').click();
  const horizontal = await page.locator('[data-node-id]').first().boundingBox();
  await page.getByLabel(/flow direction/i).click();
  const vertical = await page.locator('[data-node-id]').first().boundingBox();
  expect(horizontal && vertical).toBeTruthy();
  // Direction change re-arranges: some geometry must differ.
  expect(horizontal!.x !== vertical!.x || horizontal!.y !== vertical!.y).toBe(true);
});

test('the palette adds a node to the canvas', async ({ page }) => {
  const before = await page.locator('[data-node-id]').count();
  await page.getByPlaceholder('Search nodes…').fill('Note');
  await page.locator('.palette [class*=card], .palette button', { hasText: 'Note' }).first().click();
  await expect
    .poll(async () => page.locator('[data-node-id]').count())
    .toBeGreaterThan(before);
});
