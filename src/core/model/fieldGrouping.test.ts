import { describe, expect, it } from 'vitest';
import { groupFieldsForInspector, isInInspector } from '@core/model/contracts/fields';
import type { FieldSchema } from '@core/model/contracts/fields';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * Progressive disclosure — ticket 38.
 *
 * The Agent node's config surface is about to be large (ticket 22 counted
 * 60+ plausible fields). A flat "Configuration" list stops working, so the
 * schema itself carries `group` and `advanced`, and the Inspector derives
 * its sections from them — declared once, never per panel.
 */

const field = (key: string, extras: Partial<FieldSchema> = {}): FieldSchema =>
  ({ kind: 'text', key, defaultValue: '', ...extras }) as FieldSchema;

describe('groupFieldsForInspector', () => {
  it('defaults ungrouped fields to Configuration, in declaration order', () => {
    const groups = groupFieldsForInspector([field('a'), field('b')]);
    expect(groups).toEqual([
      { heading: 'Configuration', fields: [field('a'), field('b')], advanced: [] },
    ]);
  });

  it('keeps group order by first appearance', () => {
    const groups = groupFieldsForInspector([
      field('a', { group: 'Prompt' }),
      field('b'),
      field('c', { group: 'Prompt' }),
    ]);
    expect(groups.map((g) => g.heading)).toEqual(['Prompt', 'Configuration']);
    expect(groups[0]!.fields.map((f) => f.key)).toEqual(['a', 'c']);
  });

  it('separates advanced fields inside their group', () => {
    const groups = groupFieldsForInspector([
      field('plain', { group: 'Execution' }),
      field('deep', { group: 'Execution', advanced: true }),
    ]);
    expect(groups[0]!.fields.map((f) => f.key)).toEqual(['plain']);
    expect(groups[0]!.advanced.map((f) => f.key)).toEqual(['deep']);
  });

  it('drops fields the inspector does not show', () => {
    const groups = groupFieldsForInspector([
      field('hidden', { inInspector: false }),
      field('shown'),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.fields.map((f) => f.key)).toEqual(['shown']);
    expect(isInInspector(field('hidden', { inInspector: false }))).toBe(false);
  });
});

describe('the agent node’s config surface', () => {
  const definition = makeWorkbench().registry.nodeTypes.require('agent.llm');

  it('declares tier and systemPrompt — the keys the backend reads', () => {
    const keys = definition.fields.map((f) => f.key);
    expect(keys).toContain('tier');
    expect(keys).toContain('systemPrompt');
  });

  it('keeps the card small: only model and budget render there', () => {
    const onCard = definition.fields.filter((f) => f.onCard ?? true).map((f) => f.key);
    expect(onCard).toEqual(['model', 'tokenBudget']);
  });

  it('files the retry/timeout overrides as advanced Execution fields', () => {
    const retries = definition.fields.find((f) => f.key === 'maxRetries');
    expect(retries?.group).toBe('Execution');
    expect(retries?.advanced).toBe(true);
  });
});
