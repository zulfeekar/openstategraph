import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { subgraphNode } from './SubgraphNode';

/**
 * **A slug is a machine name, and until now nobody was told what it was.**
 *
 * `say-it-on-the-surface` 03. The word was on five surfaces and defined on
 * one: the mount field's own label, every Packages palette row's description,
 * the Workflows panel, the create toast, and `?w=` in the address bar. Only
 * the panel explained it — and a user who never opens that panel meets a
 * required field asking for a machine name nobody introduced.
 *
 * What is *not* in dispute and is deliberately not tested here as if it were:
 * the slug is minted by the backend at first save and frozen from then on,
 * because a slug that moves renames a directory. That behaviour is right. This
 * is about the word.
 */
describe('the mount field', () => {
  const field = subgraphNode.fields.find((entry) => entry.key === 'workflow');

  it('names the thing, not the identifier', () => {
    // "Workflow slug" made the label carry a word the user had not met. The
    // field asks for a workflow; how it is named is the hint's job.
    expect(field?.label).toBe('Workflow');
  });

  it('says what the identifier is, where the field is', () => {
    const hint = field && 'hint' in field ? (field.hint as string) : '';
    expect(hint).toContain('slug');
    // The two places the same string appears, so a reader can connect this
    // field to the folder and to the link they were sent.
    expect(hint).toContain('workflows/<slug>/');
    expect(hint).toContain('?w=');
  });

  it('does not imply the list is exhaustive', () => {
    // A combobox and not a listbox, decided rather than defaulted: mounting a
    // package you have not built yet is a real way to work, and copy reading
    // "pick one of these" would outlaw that order in prose while the control
    // still allowed it.
    const hint = field && 'hint' in field ? (field.hint as string) : '';
    expect(hint).toMatch(/type the slug of a package you have not built yet/);
  });

  it('is introduced once in the palette, where the same string is printed', () => {
    // Every package row prints its slug in code type. Nothing anywhere said
    // what that string was — and it is the string this field asks for, so a
    // reader who cannot connect the two cannot use either surface.
    const palette = readFileSync(
      fileURLToPath(new URL('../../view/palette/Palette.tsx', import.meta.url)),
      'utf8',
    );
    expect(palette).toMatch(/The name in code type is the <strong>slug<\/strong>/);
    expect(palette).toMatch(/what the mount field asks for/);
  });
});
