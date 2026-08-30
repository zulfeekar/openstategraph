import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { diskAutosaveTarget } from './diskAutosave';

/**
 * `say-it-on-the-surface/09`, the third question it was asked: **can a slug be
 * minted with no human ever seeing the prompt?**
 *
 * It matters because the prompt is the only place a user is told that the name
 * becomes a frozen directory. A path that reaches `create` without it would
 * make the prompt decorative — present on the surface a reviewer looks at,
 * absent on the one that actually mints.
 *
 * There are exactly three ways a save can happen, and the answer is no for all
 * three:
 *
 * - **The toolbar button** and **`Mod+S`** are the same callback,
 *   `AppShell.saveOpenWorkflow`. The keyboard path is not a quieter variant —
 *   pinned below, because a shortcut that skipped the question is the obvious
 *   shortcut to write and would have been invisible in review.
 * - **The Workflows panel's Save** calls the same `saveWorkflow`, with the
 *   same `promptName`.
 * - **Autosave cannot reach `create` at all**, and this is structural rather
 *   than careful: `diskAutosaveTarget` returns `null` while there is no slug,
 *   so the writer has no address and does not run. Autosave *overwrites a
 *   folder that already exists*; it has never been able to make one. So the
 *   only route to a minted slug runs through a deliberate Save, and
 *   `SaveDeps.promptName` is required with no default, so every such route has
 *   to name how it asks.
 */

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

describe('the only way to mint a slug', () => {
  it('is not autosave, which has no address to write to before the first save', () => {
    vi.stubGlobal('sessionStorage', { getItem: () => null } as unknown as Storage);
    expect(diskAutosaveTarget({ getItem: () => null })).toBeNull();
    expect(diskAutosaveTarget({ getItem: () => '   ' })).toBeNull();
  });

  it('is not a quieter keyboard path beside the button', () => {
    const shell = read('../view/AppShell.tsx');
    // One callback, referenced by the binding table and by the toolbar prop.
    // If `Mod+S` ever grows its own save, this count moves and the test says
    // so.
    const uses = shell.match(/saveOpenWorkflow\(\)/g) ?? [];
    expect(uses.length).toBe(2);
    expect(shell).toMatch(/keys: 'Mod\+S'[\s\S]{0,400}?run: \(\) => void saveOpenWorkflow\(\)/);
    expect(shell).toMatch(/onSave=\{\(\) => void saveOpenWorkflow\(\)\}/);
    // And that one callback asks.
    expect(shell).toMatch(/promptName: \(suggestion\) => window\.prompt\(namePromptMessage\(\)/);
  });

  it('is asked for by every surface that calls the act, because the dep has no default', () => {
    const save = read('../view/workflow/saveWorkflow.ts');
    // No `= ` default and no optional marker on the field: a fourth surface
    // does not compile until it says how it asks.
    expect(save).toMatch(/readonly promptName: \(suggestion: string\) => string \| null;/);
    expect(save).not.toMatch(/promptName\?:/);
  });
});
