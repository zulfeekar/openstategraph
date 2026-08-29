import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * Ticket 06, the owner's QA sharpening — a source assertion, deliberately.
 *
 * The tests worth writing are elsewhere (`createNewWorkflow`, `consequences`):
 * they cover the knowledge. What the owner asked for here is a matter of
 * *placement* — the toolbar stretches the width of the window, Create New is
 * in it rather than buried in a panel, and the list it routes to names its
 * three verbs out loud. Placement has no seam to unit-test in a `node`
 * environment with no DOM, and it is exactly the kind of thing a later tidy-up
 * silently undoes, so it is pinned here in the same style `lexicon.test.ts`
 * pins user-facing wording.
 */

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('the toolbar', () => {
  const topbar = read('./TopBar.tsx');
  const css = read('./TopBar.css');
  const shell = read('../AppShell.tsx');
  const shellCss = read('../AppShell.css');

  it('stretches to the right edge instead of ending mid-window', () => {
    // It used to be `flex: none` inside a row that held two more buttons
    // beside it, so the toolbar's surface stopped short of the window and the
    // last two controls floated on the canvas background. Ticket 06 fixed that
    // by deleting the row — which is what these three assertions pin. Width
    // now comes from the shell's own cross-axis stretch and needs no `flex`
    // at all; see the height test below for why asserting `flex: 1 1 auto`
    // here (as this test did until ticket 24) pinned the bug rather than the
    // fix.
    expect(shell).toMatch(/<div className="app-shell">\s*<TopBar/);
    expect(shellCss).not.toContain('app-shell__workflow-btn');
    expect(shell).not.toContain('app-shell__topbar-row');
  });

  it('never grows along the shell’s main axis, which is vertical', () => {
    // Ticket 24, the owner's "the top bar is buggy height on smaller screens".
    // `.app-shell` is `flex-direction: column`, so `flex-grow` on the toolbar
    // is a claim on **height**, not width. Ticket 06 wrote `flex: 1 1 auto`
    // meaning "reach the right edge"; below 1100px `AppShell.css` lifts both
    // side panels out of flow, `.app-shell__body`'s auto basis collapses to
    // the canvas's own content, and the toolbar duly grew into the free space
    // it had been told it could have — 424px of it at 768px wide, measured.
    expect(css).toMatch(/\.topbar\s*\{[^}]*flex:\s*none/);
    expect(css).not.toMatch(/\.topbar\s*\{[^}]*flex:\s*1 1 auto/);
  });

  it('degrades by wrapping into whole rows, not by overflowing off-screen', () => {
    // At 390px the controls ran 741px wide inside a 390px header with no
    // scroller, so Run — the primary action — was simply off the edge.
    // Wrapping keeps every control reachable, and pinning each line to the
    // row token keeps the bar's height a multiple of one row instead of
    // whatever the tallest control in a wrapped line happens to be.
    expect(css).toMatch(/\.topbar\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(css).toMatch(/\.topbar\s*\{[^}]*min-height:\s*var\(--layout-topbar-height\)/);
    expect(css).toMatch(
      /\.topbar__brand,\s*\.topbar__group\s*\{[^}]*min-height:\s*var\(--layout-topbar-height\)/,
    );
    // Row gap zero, or every wrapped row would sit a gap-token apart and the
    // height would stop being a multiple of the row.
    expect(css).toMatch(/\.topbar\s*\{[^}]*row-gap:\s*0/);
    // The bar's own height is the token and nothing else — no hand-tuned
    // pixel value, and in particular no fixed `height`, which is what made a
    // wrapped row overflow its own bar rather than lengthen it. (Glyph boxes
    // inside it — the mark, the health dot — are sized in px legitimately;
    // this looks only at the `.topbar` rule.)
    expect(css).not.toMatch(/\.topbar\s*\{[^}]*[^-]height:\s*\d+px/);
  });

  it('names itself with the authored mark rather than a stand-in glyph', () => {
    // `the-look-has-an-author-now/04`. The product had no logo anywhere — not
    // in the bar, not in the tab — and the brand slot held a generic `Network`
    // icon on an inverted tile, which is what a placeholder looks like. This
    // pins the three things that made it a placeholder, so a later tidy-up
    // that reaches for a lucide glyph again goes red here rather than shipping.
    expect(topbar).toContain('<Mark size={22} />');
    expect(topbar).toMatch(/import \{ Mark \} from '@design\/brand\/Mark';/);
    // The tile is gone: the mark is a line drawing with a hollow node in it,
    // and a filled background closes the hollow.
    expect(css).not.toMatch(/\.topbar__mark\s*\{[^}]*background:/);
  });

  it('carries New, so creating a workflow is not hidden in a panel', () => {
    expect(topbar).toContain('onNewWorkflow');
    expect(topbar).toMatch(/>\s*New\s*</);
  });

  it('routes to the workflow list by name, not by an unlabelled icon', () => {
    expect(topbar).toMatch(/>\s*Workflows\s*</);
    expect(topbar).toContain('onWorkflowsToggle');
  });

  it('keeps Ask in the toolbar rather than beside it', () => {
    expect(topbar).toContain('onAskToggle');
    expect(shell).not.toContain('Ask the workflow');
  });
  it('carries Save, where a person who has just drawn something looks for it', () => {
    // `say-it-on-the-surface` 01. Saving was reachable only from inside the
    // Workflows panel — behind a toggle, with no keyboard path — while the
    // thing filling the gap, autosave, is browser-local and reaches no
    // backend. So the cost of never finding the panel was lost work. Pinned
    // as placement, like Create New above it, because placement has no seam a
    // node-environment test can reach.
    expect(topbar).toContain("import { saveAffordance } from './saveAffordance'");
    expect(topbar).toMatch(/Tooltip content=\{save\.hint\} shortcut="Mod\+S"/);
    expect(topbar).toMatch(/onClick=\{onSave\}/);
    // Run stays the only filled button: a second `primary` means neither is.
    expect(topbar).not.toMatch(/variant="primary"[\s\S]{0,200}onClick=\{onSave\}/);
  });

  it('binds Mod+S in the one table that also feeds the shortcuts drawer', () => {
    // One binding table drives both the dispatcher and the drawer, so a
    // shortcut added anywhere else would work and be undiscoverable.
    expect(shell).toMatch(/keys: 'Mod\+S',\s*\n\s*label: 'Save workflow'/);
    // In a textarea too: a save you must click out of a field to reach is a
    // save you lose work to, and the browser's own dialog fires otherwise.
    expect(shell).toMatch(/keys: 'Mod\+S',[\s\S]{0,200}allowInTextEntry: true/);
  });

  it('presses the panel’s own act rather than reimplementing it', () => {
    // The guard `createNewWorkflow` states, applied to the second verb: a new
    // entry point is a promotion of the manager, never a second save.
    expect(shell).toContain("from './workflow/saveWorkflow'");
    const manager = read('../workflow/WorkflowManager.tsx');
    expect(manager).toContain("from './saveWorkflow'");
    // And the knowledge is in neither surface.
    expect(manager).not.toContain('adoptSlugForDraft');
    expect(topbar).not.toContain('client.create');
  });
});

describe('the workflow list', () => {
  const manager = read('../workflow/WorkflowManager.tsx');

  it('names the three verbs the owner asked to see', () => {
    // Open, not "Load": the panel is a list of workflows, and a person picking
    // one is opening it.
    expect(manager).toMatch(/>\s*Open\s*</);
    expect(manager).toMatch(/wf\.published \? 'Unpublish' : 'Publish'/);
    // Delete was an icon and nothing else — the one destructive verb in the
    // row was the only one with no word on it.
    expect(manager).toMatch(/>\s*Delete\s*</);
  });

  it('uses the shared consequence copy rather than restating it inline', () => {
    expect(manager).toContain('deleteConfirmation');
    expect(manager).toContain('publishedMessage');
    expect(manager).toContain('unpublishedMessage');
    expect(manager).not.toContain('This cannot be undone.');
  });

  it('stays fresh from the catalogue stream rather than a reload', () => {
    // Ticket 05 settled the mechanism: `GET /api/events`, subscribed through
    // the client. Both tickets use the one stream.
    expect(manager).toContain('watchCatalogue');
  });
});

/**
 * `ship-it` 39 — the lifecycle state, on the surface where the work happens.
 *
 * The knowledge is tested where it lives (`publishAffordance.test.ts`): the
 * words, the states, the confirm. What cannot be tested there is that the
 * toolbar renders any of it, and that is precisely the failure this ticket is
 * about — publishing worked perfectly for months in a panel nobody opened. A
 * source assertion for the same reason the rest of this file is one: placement
 * has no seam in a `node` environment, and it is what a later tidy-up undoes.
 */
describe('the toolbar’s lifecycle cluster', () => {
  const topbar = read('./TopBar.tsx');
  const manager = read('../workflow/WorkflowManager.tsx');

  it('is in the document group, beside Save', () => {
    // The pair, and the order: Save answers "is my work on disk", this answers
    // "is my work in front of customers". A cluster docked anywhere else on a
    // bar this wide is a second place to look.
    const group = topbar.split('<div className="topbar__group">')[1] ?? '';
    expect(group).toContain('topbar__lifecycle');
    expect(group.indexOf('save.label')).toBeLessThan(group.indexOf('topbar__lifecycle'));
  });

  it('prints the state and the verb from the affordance, never from here', () => {
    expect(topbar).toContain('usePublishState');
    expect(topbar).toContain('publish.affordance.label');
    expect(topbar).toContain('publish.affordance.actionLabel');
    // No literal lifecycle word in the toolbar: two spellings of one state
    // agree on the day they are written and drift on the first reword.
    expect(topbar).not.toMatch(/>\s*Published\s*</);
    expect(topbar).not.toMatch(/>\s*Unpublish\s*</);
  });

  it('clears the confirm before it ships something other than what is on screen', () => {
    // The ticket's second half, pinned at the gesture. `publishAffordance`
    // decides *whether* one is owed; this is the surface actually asking.
    expect(topbar).toMatch(/confirmation !== null && !confirm\(confirmation\)/);
    // **At press time, not at last render.** Found in the browser, not in a
    // test: `unsavedWork` comes from the autosaved draft, a drag writes that
    // draft, and nothing re-renders the toolbar when it does — so the
    // memoised answer was computed before the edits it warns about and the
    // confirm never fired once.
    expect(topbar).toContain('publish.affordanceNow()');
    expect(topbar).not.toMatch(/confirmation \} = publish\.affordance;/);
  });

  it('says the same two sentences the panel says, from the same module', () => {
    for (const source of [topbar, manager]) {
      expect(source).toContain('publishedMessage');
      expect(source).toContain('unpublishedMessage');
    }
  });
});
