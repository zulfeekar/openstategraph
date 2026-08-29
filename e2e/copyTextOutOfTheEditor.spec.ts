import { expect, test } from '@playwright/test';

/**
 * `launch-readiness` 187 — "user cannot copy any text content from the UI, it
 * gives the JSON".
 *
 * The vitest half of this drives `KeyboardFeature`'s handler against a fake
 * window; it runs in the gate and is where a regression will be caught. This
 * half is the layer the defect actually lived at and the one no node test can
 * reach: a **real** selection made over a **real** `<div>` in the running
 * editor, and a real ⌘C.
 *
 * The assertion is `defaultPrevented` rather than the pasteboard, because a
 * headless browser does not reliably run the clipboard command for a synthetic
 * shortcut — and because that is the defect exactly. The canvas claiming a key
 * the browser was about to handle is the whole bug; what the pasteboard then
 * holds is the operating system's business.
 */
test('a selection over prose keeps ⌘C, and the canvas keeps it back when nothing is selected', async ({
  page,
}) => {
  await page.goto('/');
  await page.locator('.node').first().waitFor();

  /** Listeners added now run after the app's, so they can read its verdict. */
  await page.evaluate(() => {
    (window as unknown as { __press: { prevented: boolean | null } }).__press = { prevented: null };
    window.addEventListener('keydown', (event) => {
      if (event.code === 'KeyC' || event.code === 'KeyX' || event.code === 'KeyA') {
        (window as unknown as { __press: { prevented: boolean | null } }).__press.prevented =
          event.defaultPrevented;
      }
    });
  });

  const press = async (key: string) => {
    await page.evaluate(
      () =>
        ((window as unknown as { __press: { prevented: boolean | null } }).__press.prevented =
          null),
    );
    await page.keyboard.press(key);
    return page.evaluate(
      () => (window as unknown as { __press: { prevented: boolean | null } }).__press.prevented,
    );
  };

  const selected = await page.evaluate(() => {
    // The diagnostics panel: ordinary prose in a `<div>`, focus on `<body>`,
    // which is every non-input surface in the shell — the chat answer, the
    // trace tree, Past Runs, the shortcuts drawer itself.
    const el = [...document.querySelectorAll('span, p, li')]
      .filter((e) => e.textContent && e.textContent.trim().length > 30)
      .pop();
    if (!el) return null;
    const range = document.createRange();
    range.selectNodeContents(el);
    const selection = getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    return selection?.toString() ?? null;
  });
  expect(selected?.length ?? 0).toBeGreaterThan(30);

  for (const key of ['Meta+c', 'Meta+x', 'Meta+a']) {
    expect(await press(key), `${key} while text is selected`).toBe(false);
  }

  // And the canvas keeps the key back the moment the selection goes away —
  // which is what clicking a node does, so this is the order a real user
  // reaches a node copy in.
  await page.evaluate(() => getSelection()?.removeAllRanges());
  expect(await press('Meta+c'), 'Meta+c with nothing selected').toBe(true);
});
