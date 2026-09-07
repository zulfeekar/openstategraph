import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { allNodeDefinitions } from '@nodes/portSpecs';
import type { FieldSchema } from '@core/model/contracts/fields';

/**
 * A field that names a live store is a field the renderer follows.
 *
 * The other half of `nodes/liveModelOptions.test.ts`. That one pins that the
 * model and reasoning pickers *declare* where their options come from; this one
 * pins that declaring it does something — that `FieldRenderer` subscribes for a
 * `select` and not only for a `combobox`, which was the whole gap. A card's
 * `<select>` held its first-paint list for the life of the session while the
 * onboarding hint two centimetres away, subscribed directly, updated correctly.
 *
 * A source assertion because `vite.config.ts` runs tests in `node` with no DOM,
 * the same reason `repeatableRows.test.ts` reads this file. What it pins is a
 * relation between two lists in different directories: the kinds the catalogue
 * declares `subscribe` on, and the kinds the renderer honours it for. A
 * `subscribe` the renderer ignores is worse than none — it reads, at the
 * declaration site, as a solved problem.
 */
const source = readFileSync(fileURLToPath(new URL('./FieldRenderer.tsx', import.meta.url)), 'utf8');

/** Every field in the catalogue, rows included. */
function allFields(fields: readonly FieldSchema[]): FieldSchema[] {
  return fields.flatMap((field) =>
    field.kind === 'repeatable-group' ? [field, ...allFields(field.fields)] : [field],
  );
}

const subscribing = [
  ...new Set(
    allNodeDefinitions()
      .flatMap((definition) => allFields(definition.fields ?? []))
      .filter((field) => 'subscribe' in field && field.subscribe)
      .map((field) => field.kind),
  ),
];

describe('a field that names a live store is followed', () => {
  it('finds subscribing fields in the catalogue at all, so this test can fail', () => {
    expect(subscribing.length).toBeGreaterThan(0);
  });

  it('subscribes through one hook, so no kind can be given the seam and miss it', () => {
    expect(source).toContain('function useOptionSource(');
  });

  it.each(subscribing)('honours subscribe on a %s', (kind) => {
    // The component the switch delegates that kind to. A `case` cannot call a
    // hook — hooks may not be conditional — which is exactly why the combobox
    // was extracted, and exactly why the select was not following its store.
    const component = { select: 'SelectField', combobox: 'ComboboxField' }[kind as string];
    expect(
      component,
      `the catalogue declares subscribe on a ${kind} field and this test does not know ` +
        `which component renders it — add the delegate, or the declaration is inert`,
    ).toBeDefined();
    expect(source).toMatch(new RegExp(`<${component}\\b`));
    expect(source).toMatch(new RegExp(`function ${component}\\b`));
  });

  it('resolves the options after the subscription, not before it', () => {
    // Order is the substance here: a component that computed its options above
    // the hook would render the list it was subscribed to *last* time. Both
    // delegates call `resolveOptions` in their body, below `useOptionSource`.
    for (const component of ['SelectField', 'ComboboxField']) {
      const body = source.slice(source.indexOf(`function ${component}`));
      expect(body.indexOf('useOptionSource')).toBeGreaterThan(-1);
      expect(body.indexOf('resolveOptions')).toBeGreaterThan(body.indexOf('useOptionSource'));
    }
  });
});
