import { test as base, expect, type Page } from '@playwright/test';
import { mkdirSync, readdirSync, rmSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * One scene of the product film.
 *
 * A scene is its own spec file, its own browser context and its own video, for
 * one reason: **the whole film cannot share a speed**. Scrolling a palette is
 * worth 3x and a model answering is worth 1x, so speed is a property of the
 * scene, not of the recording. Each scene therefore writes
 * `demo-out/scenes/<order>-<name>@<speed>x.webm` and the stitch script reads
 * the factor out of the file name. The alternative — a manifest beside the
 * files — is a second place the same fact can be wrong.
 *
 * Two things a recorded browser does not do on its own, and both are why an
 * unedited Playwright video reads as broken rather than as a demonstration:
 *
 * - **There is no cursor.** The browser draws none, so clicks appear to happen
 *   by themselves. `CURSOR` paints one from real pointer events.
 * - **Typing is instant.** `fill()` sets a value in one frame, which reads as a
 *   paste. `slowType` presses keys.
 */
export interface SceneSpec {
  /** Sort order in the finished film. */
  order: string;
  /** File-name stem, and what the chapter list calls this scene. */
  name: string;
  /** Playback multiplier applied by the stitch script. 1 keeps real time. */
  speed: number;
}

const SCENES_DIR = resolve(process.cwd(), 'demo-out/scenes');

/**
 * A pointer the camera can see.
 *
 * Injected before any script on the page, so it survives a reload. It listens
 * to real `mousemove` and `mousedown`, which is what `page.mouse` dispatches,
 * so the drawn cursor cannot drift from the gesture that is being recorded —
 * it is the same event, not a re-simulation of it.
 */
const CURSOR = `
(() => {
  const paint = () => {
    if (document.getElementById('__demo_cursor')) return;
    const dot = document.createElement('div');
    dot.id = '__demo_cursor';
    dot.style.cssText = [
      'position:fixed', 'left:0', 'top:0', 'width:22px', 'height:22px',
      'margin:-11px 0 0 -11px', 'border-radius:50%', 'pointer-events:none',
      'z-index:2147483647', 'background:rgba(0,0,0,.72)',
      'box-shadow:0 0 0 2px rgba(255,255,255,.9), 0 2px 8px rgba(0,0,0,.35)',
      'transition:transform .09s ease-out', 'transform:translate(-100px,-100px)',
    ].join(';');
    document.body.appendChild(dot);
    let x = -100, y = -100, down = false;
    const place = () =>
      (dot.style.transform =
        'translate(' + x + 'px,' + y + 'px) scale(' + (down ? 0.7 : 1) + ')');
    addEventListener('mousemove', (e) => { x = e.clientX; y = e.clientY; place(); }, true);
    addEventListener('mousedown', () => { down = true; place(); }, true);
    addEventListener('mouseup', () => { down = false; place(); }, true);
  };
  if (document.body) paint();
  else addEventListener('DOMContentLoaded', paint);
})();
`;

/** Press the keys instead of setting the value, so the camera sees typing. */
export async function slowType(page: Page, selector: string, text: string) {
  const field = page.locator(selector).first();
  await field.click();
  await field.pressSequentially(text, { delay: 55 });
}

/**
 * Move the pointer to an element the way a hand would, then click it.
 *
 * A bare `locator.click()` teleports the pointer, so the drawn cursor jumps and
 * the viewer loses the thread of what is being pointed at.
 */
export async function reachAndClick(page: Page, selector: string, steps = 18) {
  const target = page.locator(selector).first();
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) throw new Error(`no box for ${selector}`);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps });
  await page.waitForTimeout(200);
  await target.click();
}

/**
 * Close the right-hand inspector, so the canvas gets the width.
 *
 * The inspector is open on first load, which is right for someone building a
 * workflow and wrong for a film about one: it takes roughly a fifth of the
 * frame and pushes the nodes into the left half, so the thing the viewer is
 * meant to look at is the smallest thing on screen.
 *
 * Read the toggle's own pressed state rather than clicking blind. A scene that
 * assumed "open" would close it on one machine and open it on the next, and
 * the difference is invisible until the film is watched.
 */
export async function hideInspector(page: Page) {
  const toggle = page.locator('button[aria-label="Toggle inspector"]').first();
  if ((await toggle.getAttribute('aria-pressed')) === 'false') return;
  await toggle.click();
  await page.waitForTimeout(350);
}

/** Let the eye land before the next gesture. */
export async function beat(page: Page, ms = 700) {
  await page.waitForTimeout(ms);
}

/**
 * Register a scene. Call once at the top of a scene spec file.
 *
 * Returns the extended `test` and `expect`. The returned `test` opens the
 * editor, paints the cursor, and files the video under the scene's name.
 */
export function defineScene(spec: SceneSpec) {
  mkdirSync(SCENES_DIR, { recursive: true });

  let startedAt = 0;
  let cutAt: number | null = null;

  /**
   * Mark where the finished film should join this scene.
   *
   * Some scenes must arrange state the viewer should not watch — opening a
   * workflow, filling a question that an earlier scene already showed being
   * typed. Calling `cut()` records the elapsed milliseconds at that instant,
   * which the stitch script turns into an `-ss` seek. Measured rather than
   * guessed: a hardcoded lead-in is wrong on the first slow machine.
   */
  const cut = () => {
    cutAt = Date.now() - startedAt;
  };

  const test = base.extend<{ stage: Page }>({
    stage: async ({ page }, use) => {
      // Video recording begins with the context, which Playwright creates just
      // before this fixture runs, so this is the clip's own zero.
      startedAt = Date.now();
      cutAt = null;
      await page.addInitScript(CURSOR);
      await use(page);
    },
  });

  test.afterEach(async ({ page }) => {
    const video = page.video();
    // `saveAs` waits for the recording to be flushed, which only happens once
    // the page is closed. Closing here rather than leaving it to the fixture
    // teardown is the difference between a saved file and a truncated one.
    await page.close();
    // A re-take must replace its predecessor, not sit beside it. The speed and
    // the cut point are both in the file name, so a re-take that lands on a
    // different cut writes a different name — and the stitch script would then
    // splice the same scene in twice, once from a run that failed.
    for (const stale of readdirSync(SCENES_DIR)) {
      if (stale.startsWith(`${spec.order}-`)) rmSync(resolve(SCENES_DIR, stale));
    }
    const trim = cutAt === null ? '' : `+${(cutAt / 1000).toFixed(1)}s`;
    await video?.saveAs(
      resolve(SCENES_DIR, `${spec.order}-${spec.name}@${spec.speed}x${trim}.webm`),
    );
  });

  return { test, expect, cut };
}
