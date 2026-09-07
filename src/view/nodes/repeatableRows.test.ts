import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { allNodeDefinitions } from '@nodes/portSpecs';
import type { FieldSchema, RepeatableGroupSchema } from '@core/model/contracts/fields';

/**
 * Every control a row can declare is a control the row renderer draws.
 *
 * This is ticket 26's defect generalised. A row's `combobox` rendered
 * **nothing at all** — the case was simply missing from the switch — so the
 * Guardrail's Entity control was an empty gap on the card and a rule could not
 * be told what it was about. The Grader's `required` toggle had the same
 * shape. Neither raised anything; a missing case in a chain of `&&` renders
 * false, and false renders nothing.
 *
 * A source assertion because `vite.config.ts` runs tests in `node` with no DOM
 * — the same reason `mcpPanelSurface.test.ts` reads a file. What it pins is a
 * relation between two lists that live in different files and would otherwise
 * drift silently: the kinds the catalogue puts *inside* rows, and the kinds
 * `RepeatableGroupField` knows how to draw.
 */
const source = readFileSync(fileURLToPath(new URL('./FieldRenderer.tsx', import.meta.url)), 'utf8');

/** The row group of every node type that declares one. */
function rowGroups(fields: readonly FieldSchema[]): RepeatableGroupSchema[] {
  return fields.flatMap((field) =>
    field.kind === 'repeatable-group' ? [field, ...rowGroups(field.fields)] : [],
  );
}

const groups = allNodeDefinitions().flatMap((definition) =>
  rowGroups(definition.fields ?? []).map((group) => ({ type: definition.id, group })),
);

describe('a row draws every control a row may declare', () => {
  it('finds row groups in the catalogue at all, so this test can fail', () => {
    expect(groups.length).toBeGreaterThan(0);
  });

  it.each([...new Set(groups.flatMap(({ group }) => group.fields.map((f) => f.kind)))])(
    'renders a %s inside a row',
    (kind) => {
      expect(
        source,
        `a row field of kind ${kind} is declared somewhere in the catalogue and ` +
          `FieldRenderer's row switch has no case for it — it will render nothing, silently`,
      ).toContain(`field.kind === '${kind}'`);
    },
  );

  it('runs a row field’s own validator, where it declares one', () => {
    // The MCP card's credential variable is the case: a row that accepted
    // what the flat field refuses would be a second answer to "is this a
    // variable name or the credential itself".
    const validated = groups.flatMap(({ type, group }) =>
      group.fields
        .filter((field) => 'validate' in field && field.validate)
        .map((f) => [type, f.key]),
    );
    expect(validated.length, 'no row field declares a validator any more').toBeGreaterThan(0);
    expect(source).toContain('rowError(field, row[field.key])');
  });

  it('probes a row only when the group asks for one', () => {
    // On demand, never on render: a probe opens a connection, and a group
    // that checked every row on every keystroke would hammer a server from a
    // text box.
    expect(source).toContain('schema.rowProbe');
    expect(source).not.toMatch(/useEffect\([^)]*probe/);
  });
});
