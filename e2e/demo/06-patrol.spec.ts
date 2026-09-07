import { defineScene, beat, reachAndClick } from './support/scene';

/**
 * Scene 6 — the board fills itself.
 *
 * The findings are real and they come from the run scene 5 just made, which is
 * why this scene is last: a patrol reads recorded runs, so there has to be one.
 * Nothing here is seeded. If the run had been clean, the film would show a
 * clean board.
 */
const { test, expect } = defineScene({ film: 'demo', order: '06', name: 'patrol', speed: 1.5 });

test('a patrol files cards from the run that just happened', async ({
  stage: page,
}) => {
  await page.goto('/');
  await expect(page.locator('.palette')).toBeVisible();
  await beat(page, 800);

  await reachAndClick(page, 'button[aria-label="Patrol board"]');
  // The empty state is part of the story: it says the board is blank because
  // nothing has looked yet, not because everything is clean.
  await expect(page.locator('.patrol-board__empty')).toBeVisible();
  await beat(page, 2600);

  // Two buttons carry this name — the empty state's and the footer's. The one
  // the eye is on is the first.
  await reachAndClick(page, '.patrol-board__empty button.btn--primary');

  // Cards land one at a time as the patrol finds them.
  await expect(page.locator('.dialog__body')).toContainText('Patrol finished', {
    timeout: 120_000,
  });
  await beat(page, 3800);
});
