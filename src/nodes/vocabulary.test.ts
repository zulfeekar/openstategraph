import { describe, expect, it } from 'vitest';
import { CATEGORIES, CATEGORY } from './vocabulary';
import { teamNode } from './compose/TeamNode';
import { subgraphNode } from './compose/SubgraphNode';
import { createOrchestratorNode } from './orchestrate/OrchestratorNode';
import { formattedOutputNode } from './output/FormattedOutputNode';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';

/**
 * Materialised once per file. The definition is now built from the
 * `ProviderRegistry` — every model-driven family carries the shared model
 * picker (`../modelField`) — so the tests build one the same way the
 * catalogue does rather than asserting against a shape nothing registers.
 */
const orchestratorNode = createOrchestratorNode(new ProviderRegistry(new CredentialStore(false)));

/**
 * The palette's tiering is a claim about the catalogue, so it is a claim
 * that can be wrong — and was: `Team` and `Workflow`, each an entire
 * compiled workflow mounted as one step, sat under a section labelled
 * `Agents · molecules`. These tests exist so that regression is a red test
 * rather than a design review someone has to remember to hold.
 */
describe('palette tiering', () => {
  const label = (id: string) => CATEGORIES.find((c) => c.id === id)?.label ?? '';
  const orderOf = (id: string) => CATEGORIES.find((c) => c.id === id)?.order ?? -1;

  it('names a tier in every section label, so none can quietly imply the wrong one', () => {
    for (const category of CATEGORIES) {
      expect(category.label).toMatch(/· (atoms|molecules|organisms|no tier)$/);
    }
  });

  it('runs atoms before molecules before organisms', () => {
    const tierOf = (id: string) => label(id).split('· ')[1];
    const rank = { atoms: 0, molecules: 1, organisms: 2, 'no tier': 3 } as const;
    const ranks = CATEGORIES.slice()
      .sort((a, b) => a.order - b.order)
      .map((c) => rank[(tierOf(c.id) ?? 'no tier') as keyof typeof rank]);
    expect(ranks).toEqual(ranks.slice().sort((a, b) => a - b));
  });

  it('files a mounted workflow as an organism — it brings its own nodes, state and loop', () => {
    expect(teamNode.category).toBe(CATEGORY.compose);
    expect(subgraphNode.category).toBe(CATEGORY.compose);
    expect(label(CATEGORY.compose)).toContain('organisms');
  });

  it('keeps a lone supervisor a molecule — the organism is supervisor + workers + join', () => {
    expect(orchestratorNode.category).toBe(CATEGORY.agent);
    expect(label(CATEGORY.agent)).toContain('molecules');
  });

  it('keeps a plain sink an atom', () => {
    expect(formattedOutputNode.category).toBe(CATEGORY.output);
    expect(label(CATEGORY.output)).toContain('atoms');
  });

  it('explains each tier once, under its heading', () => {
    for (const category of CATEGORIES) {
      expect(category.description?.length ?? 0).toBeGreaterThan(0);
    }
  });

  it('orders organisms after every atom section', () => {
    for (const atom of [CATEGORY.inputs, CATEGORY.tools, CATEGORY.output]) {
      expect(orderOf(atom)).toBeLessThan(orderOf(CATEGORY.compose));
    }
  });
});
