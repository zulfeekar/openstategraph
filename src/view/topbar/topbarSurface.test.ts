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
