import { expect, test, type Page } from '@playwright/test';

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

test('clicking a field selects its node', async ({ page }) => {
  // The gap the header-click fix left behind (canvas-feels-right ticket 05).
  // Every on-card control is `data-no-drag` so a drag cannot start inside a
  // textarea — right, and it also swallowed selection, because the paper never
  // saw the event. On the seeded demo the first card is mostly textarea, so
  // "click the node" meant "click the field" more often than not and the
  // inspector never switched.
  const field = page.locator('[data-node-id] [data-no-drag] textarea').first();
  await expect(field).toBeVisible();
  await field.click();

  // Selected: the inspector is about the node, not the workflow.
  await expect(page.locator('.inspector')).not.toContainText('Diagnostics');
  // …and still editable, which is what the drag guard is protecting.
  await expect(field).toBeFocused();
});

test('dragging a node moves it and undo restores it', async ({ page }) => {
  const card = page.locator('[data-node-id]').first();
  const before = await card.boundingBox();
  if (!before) throw new Error('node card has no box');
  await page.mouse.move(before.x + before.width / 2, before.y + 10);
  await page.mouse.down();
  await page.mouse.move(before.x + before.width / 2 + 120, before.y + 90, { steps: 8 });
  await page.mouse.up();
  // Polled, not read once. Both reads used to happen immediately after the
  // gesture — after `mouse.up()` here and after the undo keystroke below —
  // and the model→adapter→canvas projection lands on a later frame, so on a
  // loaded machine the old position is still what the DOM reports
  // (reviews-2026-08-14 ticket 10). The assertions are unchanged.
  await expect
    .poll(async () => Math.abs(((await card.boundingBox())?.x ?? 0) - before.x))
    .toBeGreaterThan(40);

  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+z' : 'Control+z');
  await expect
    .poll(async () => Math.abs(((await card.boundingBox())?.x ?? 0) - before.x))
    .toBeLessThan(8);
});

/** The bounding boxes of every card, so a layout can be described. */
async function spread(page: Page): Promise<{ x: number; y: number; count: number }> {
  const boxes = await Promise.all(
    (await page.locator('[data-node-id]').all()).map((card) => card.boundingBox()),
  );
  const seen = boxes.filter((box): box is NonNullable<typeof box> => box !== null);
  const range = (values: number[]) => Math.max(...values) - Math.min(...values);
  return {
    x: range(seen.map((box) => box.x)),
    y: range(seen.map((box) => box.y)),
    count: seen.length,
  };
}

test('auto-arrange works in both flow directions', async ({ page }) => {
  // The layout is scrambled first, and this is the part that makes the test
  // mean anything. It used to assert `expect(horizontal).toBeTruthy()` — that
  // a card has a bounding box — so an arrange that did nothing passed
  // (reviews-2026-08-14 ticket 09). Asserting the *shape* of the layout is not
  // enough on its own either: the seeded demo is already laid out left to
  // right, so a horizontal check passes without ever clicking Arrange.
  // Verified: with the click removed, this test fails.
  const card = page.locator('[data-node-id]').last();
  const box = await card.boundingBox();
  if (!box) throw new Error('node card has no box');
  await page.mouse.move(box.x + box.width / 2, box.y + 10);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2, box.y + 700, { steps: 8 });
  await page.mouse.up();
  const scrambled = await card.boundingBox();
  expect((scrambled?.y ?? 0) - box.y).toBeGreaterThan(400);

  await page.getByLabel('Arrange automatically').click();
  // Arrange put the displaced card back in the row.
  await expect
    .poll(async () => (await card.boundingBox())?.y ?? 0)
    .toBeLessThan((scrambled?.y ?? 0) - 300);
  const horizontal = await page.locator('[data-node-id]').first().boundingBox();
  expect(horizontal).toBeTruthy();
  // What "horizontal" means: the cards are spread further across than down.
  await expect
    .poll(async () => {
      const across = await spread(page);
      return across.count > 1 && across.x > across.y;
    })
    .toBe(true);

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

  // And the new direction is genuinely the other one.
  const down = await spread(page);
  expect(down.y).toBeGreaterThan(down.x);
});

test('the palette adds a node from the keyboard', async ({ page }) => {
  // Was `.click()` until `say-it-on-the-surface` 04. A mouse click no longer
  // places anything from any palette row — drag aims, the keyboard places —
  // and this test is the reason the click was kept once before, so it is the
  // test that has to move rather than the rule. The *capability* it guards is
  // unchanged and is the one the accessibility argument was always about: a
  // person who cannot drag can still put a node on the canvas.
  const before = await page.locator('[data-node-id]').count();
  await page.getByPlaceholder('Search nodes…').fill('Note');
  const item = page
    .locator('.palette [class*=card], .palette button', { hasText: 'Note' })
    .first();
  await item.focus();
  await item.press('Enter');
  await expect.poll(async () => page.locator('[data-node-id]').count()).toBeGreaterThan(before);
});

test('a plain click on a palette row places nothing', async ({ page }) => {
  // The complaint, twice over: "on click it appears on the canvas is not
  // correct". A click aims at nothing, so it places nothing — and the palette
  // now says so in its own body rather than in a source comment.
  //
  // **The howto is read on arrival, and that ordering is the fix for
  // `ship-it/57`.** This assertion used to sit at the end, after the search
  // box had been filled — and the palette hides the paragraph while searching
  // on purpose, because a filtered palette is a lookup rather than a first
  // visit. So it asked for an element the product had correctly removed, and
  // failed on every runner from the day it was written (`bc6151f`) until CI
  // next ran. Nothing is weakened here: the same sentence is still required,
  // and the gate that hides it is now required too.
  await expect(page.locator('.palette-howto')).toContainText('Drag any of these');
  await page.getByPlaceholder('Search nodes…').fill('Note');
  await expect(page.locator('.palette-howto')).toHaveCount(0);
  const before = await page.locator('[data-node-id]').count();
  await page.locator('.palette button[draggable]').first().click();
  // Given a moment to be wrong in: a placement lands a frame or two later, so
  // an immediate read would pass even if the click still placed.
  await page.waitForTimeout(300);
  expect(await page.locator('[data-node-id]').count()).toBe(before);
});

test('two keystrokes make two nodes you can both see', async ({ page }) => {
  // The count-based assertion above cannot see the bug that shipped: three
  // activations put three nodes at *exactly* the same coordinate, so a user
  // saw one card and owned three. `toBeGreaterThan(before)` passes on a
  // perfect stack (reviews-2026-08-14 ticket 02). `freePositionNear` is what
  // fixed it and it is on the *activation* path, so this still guards it —
  // through the keyboard, which is now that path.
  await page.getByPlaceholder('Search nodes…').fill('Text Input');
  const item = page.locator('.palette button[draggable]').first();
  await item.focus();
  await item.press('Enter');
  await item.press('Enter');

  await expect
    .poll(async () => page.locator('[data-node-id^="node:input.text"]').count())
    .toBeGreaterThanOrEqual(2);

  const boxes = await page.locator('[data-node-id^="node:input.text"]').evaluateAll((nodes) =>
    nodes.map((node) => {
      const box = node.getBoundingClientRect();
      return `${Math.round(box.x)},${Math.round(box.y)}`;
    }),
  );

  // Distinct positions, not merely distinct nodes.
  expect(new Set(boxes).size).toBe(boxes.length);
});

test('a node dragged from the palette lands where it was dropped', async ({ page }) => {
  // Drag-and-drop had no coverage at any level — not a unit test, not an e2e
  // (the existing drag test moves an *existing* node). The drop handler does
  // real work: `clientToLocal`, the assembly branch, and the splice-insert
  // decision. A renamed MIME type or an inverted `isPaletteDrag` was
  // undetectable (reviews-2026-08-14 ticket 02).
  await page.getByPlaceholder('Search nodes…').fill('Markdown File');
  const item = page.locator('.palette button[draggable]').first();
  await expect(item).toBeVisible();

  const before = await page.locator('[data-node-id]').count();
  const stage = page.locator('.canvas-stage');
  const target = await stage.boundingBox();
  if (!target) throw new Error('the canvas is not on screen');
  // Well inside the stage and away from its edges, so the drop cannot land on
  // the palette or a panel.
  const dropAt = { x: target.x + target.width * 0.6, y: target.y + target.height * 0.7 };

  await item.hover();
  await page.mouse.down();
  await page.mouse.move(dropAt.x, dropAt.y, { steps: 16 });
  await page.mouse.up();

  await expect.poll(async () => page.locator('[data-node-id]').count()).toBeGreaterThan(before);

  // Where it was dropped, not wherever the canvas felt like — that is the
  // whole difference between a drag and a click.
  const dropped = page.locator('[data-node-id^="node:input.markdown"]').last();
  const box = await dropped.boundingBox();
  expect(box).not.toBeNull();
  expect(Math.abs((box?.x ?? 0) + (box?.width ?? 0) / 2 - dropAt.x)).toBeLessThan(160);
  expect(Math.abs((box?.y ?? 0) + (box?.height ?? 0) / 2 - dropAt.y)).toBeLessThan(160);
});

test('a refused connection says why', async ({ page }) => {
  // The defect this guards (reviews-2026-08-14 ticket 03): dragging between
  // incompatible ports was refused in **silence**. The rule had a sentence
  // ready — "Text output can't feed a Skill input" — and `validateConnection`
  // returned a bare boolean, so JointJS refused the link, `link:connect` never
  // fired, and the reason was thrown away. A refused drag and a successful one
  // looked identical.
  //
  // Deliberately an e2e test: the whole failure lived in the gesture wiring
  // between JointJS and the controller, which is the one layer no unit test
  // in this repo can reach.
  const out = page.locator('[data-port-direction="out"][data-port-id="text"]').first();
  const wrongIn = page.locator('[data-port-direction="in"][data-port-id="skill"]').first();
  await expect(out).toBeVisible();
  await expect(wrongIn).toBeVisible();

  const from = await out.boundingBox();
  const to = await wrongIn.boundingBox();
  if (!from || !to) throw new Error('ports are not on screen');

  await page.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await page.mouse.down();
  // Several steps: the paper only starts a link once the pointer leaves the
  // magnet (`magnetThreshold: 'onleave'`).
  await page.mouse.move(to.x + to.width / 2, to.y + to.height / 2, { steps: 12 });
  await page.mouse.up();

  // The rule's own words, not a generic "invalid connection".
  await expect(page.locator('.toaster')).toContainText(/can't feed|cannot connect|loop/i);

  // …and the inspector must not claim something was removed. While a link is
  // being drawn JointJS owns a temporary cell with an id of its own, and
  // pressing through it used to select that id — so a refused drag reported
  // "Link removed. That link is no longer in the workflow." about a link that
  // was never in it.
  await expect(page.locator('.inspector')).not.toContainText('Link removed');
});

test('clicking a real link still selects it', async ({ page }) => {
  // The guard above refuses to select an id the model does not have. This is
  // the other side of it: a genuine edge must still be selectable, or the
  // fix for the phantom would have cost the feature.
  // The midpoint of the drawn path, not the centre of the bounding box — a
  // link's box is large and mostly empty, so a box-relative click lands on
  // whatever is behind it (a node, in this document).
  const at = await page.evaluate(() => {
    const paths = [...document.querySelectorAll('.joint-link path')] as SVGPathElement[];
    const path = paths.find((candidate) => candidate.getTotalLength() > 20);
    if (!path) return null;
    const mid = path.getPointAtLength(path.getTotalLength() / 2);
    const ctm = path.getScreenCTM();
    if (!ctm) return null;
    return { x: mid.x * ctm.a + mid.y * ctm.c + ctm.e, y: mid.x * ctm.b + mid.y * ctm.d + ctm.f };
  });
  if (!at) throw new Error('no link path on screen');
  await page.mouse.click(at.x, at.y);

  await expect(page.locator('.inspector')).toContainText('Link');
  await expect(page.locator('.inspector')).not.toContainText('Link removed');
});
