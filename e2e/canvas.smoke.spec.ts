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
  // The **header**, not the card's centre. Every on-card control is wrapped in
  // `data-no-drag` and the paper guard ignores pointer events from one, so a
  // click landing on a field selects nothing — deliberate, so that dragging
  // cannot start from inside a textarea. This test used to click the centre
  // and pass only because the first seeded node had no field there; the demo
  // changed to one whose prompt textarea fills the card, and the assertion
  // started reporting a fixture change as a selection bug.
  await card.locator('.node__header').click();
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
  expect(horizontal).toBeTruthy();
  await page.getByLabel(/flow direction/i).click();
  // Polled, not read once. The toggle defers `autoLayout.run` into a
  // `requestAnimationFrame` (and `fitToContent` into a second one), so an
  // immediate read races the frame that does the work: it passes on a quiet
  // machine and fails on a loaded one, which is the worst kind of red.
  // Direction change re-arranges: some geometry must differ.
  await expect
    .poll(async () => {
      const now = await page.locator('[data-node-id]').first().boundingBox();
      return now!.x !== horizontal!.x || now!.y !== horizontal!.y;
    })
    .toBe(true);
});

test('the palette adds a node to the canvas', async ({ page }) => {
  const before = await page.locator('[data-node-id]').count();
  await page.getByPlaceholder('Search nodes…').fill('Note');
  await page
    .locator('.palette [class*=card], .palette button', { hasText: 'Note' })
    .first()
    .click();
  await expect.poll(async () => page.locator('[data-node-id]').count()).toBeGreaterThan(before);
});
