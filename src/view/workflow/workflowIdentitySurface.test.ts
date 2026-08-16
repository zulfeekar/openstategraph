import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

/**
 * The-editor-makes-a-real-package 07 — *the slug is the identity, the name is
 * a label*, and every surface where two saved workflows appear together has to
 * act like it.
 *
 * The review found two rows reading
 *
 *     AI Workflow      Draft        16/08/2026    Open · Publish · …
 *     AI Workflow      Published    16/08/2026    Open · Unpublish · …
 *
 * with the same name, the same date, and nothing else — while the panel's own
 * hint text three lines above promised *"a second workflow of the same name
 * gets its own [slug]"*. The Packages palette had it right all along
 * (`palette-item__slug`), which is why this pins the drawer against the
 * palette rather than inventing a new rule.
 *
 * A source assertion, for the reason `mcpPanelSurface.test.ts` records:
 * placement is exactly what a later tidy-up undoes without noticing, and there
 * is no seam in a `node` environment that would catch it.
 */
const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const drawer = read('./WorkflowManager.tsx');
const drawerCss = read('./WorkflowManager.css');
const palette = read('../palette/Palette.tsx');

describe('the Workflows drawer', () => {
  it('prints the slug on every row, as the palette already does', () => {
    expect(drawer).toContain('workflow-manager__slug');
    expect(drawer).toMatch(/className="workflow-manager__slug"[^>]*>\s*\{wf\.slug\}/);
    expect(palette).toContain('palette-item__slug');
  });

  it('gives the slug somewhere to go rather than letting it truncate', () => {
    // The longer of the two strings and the one that must survive: a slug cut
    // to "ai-workflo…" tells two rows apart no better than the name did.
    expect(drawerCss).toContain('.workflow-manager__slug');
    expect(drawerCss).toContain('overflow-wrap: anywhere');
  });

  it('warns before minting a second package of a name that already has one', () => {
    expect(drawer).toContain('duplicateNameConfirmation');
    // Only on a create. An overwrite of the workflow you already have open is
    // not a collision with anything.
    const guard = drawer.split('const open = getOpenSlug();')[1]?.split('setBusy(true);')[0] ?? '';
    expect(guard).toContain('if (!open)');
    expect(guard).toContain('duplicateNameConfirmation');
  });
});
