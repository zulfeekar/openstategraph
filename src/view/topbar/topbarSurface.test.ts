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
    // last two controls floated on the canvas background.
    expect(css).toMatch(/\.topbar\s*\{[^}]*flex:\s*1 1 auto/);
    expect(css).not.toMatch(/\.topbar\s*\{[^}]*flex:\s*none/);
    expect(shellCss).not.toContain('app-shell__workflow-btn');
    expect(shell).not.toContain('app-shell__topbar-row');
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
