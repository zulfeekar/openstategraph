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

/**
 * production-ready ticket 02.
 *
 * Two violet cards, the same glyph, the same ports, the same category,
 * labelled "Workflow" and "Team". Research had already established there is
 * **no compilation difference at all** — one backend builder serves both — so
 * the honest fix was never to invent a difference, only to make the contract
 * each one offers legible.
 *
 * These assert *properties* of the copy, not its exact words: a test that
 * freezes marketing text makes improving it a failure. What must stay true is
 * that each says what it is, that Team's extra is named, and that neither
 * claims something the compiler does not do.
 */
describe('an organism states the contract it offers', () => {
  const workflow = subgraphNode.description ?? '';
  const team = teamNode.description ?? '';

  it('gives the two organisms different glyphs', () => {
    // The single visual channel available, and it was spent on making them
    // look identical.
    expect(subgraphNode.iconId).not.toBe(teamNode.iconId);
  });

  it('says a mounted workflow is isolated — the thing a user cannot guess', () => {
    // Isolation is the whole mechanism: the child sees a task and reports a
    // result, and never the parent's state or messages.
    expect(workflow.toLowerCase()).toMatch(/isolat|its own|task in/);
  });

  it('names what Team adds, rather than restating what Workflow already is', () => {
    expect(team.toLowerCase()).toContain('outcome');
  });

  it('never calls a Team parallel or multi-agent', () => {
    // The badge is earned from the child's grader wiring, not from the label.
    // A grader-less document can be mounted as a Team today (ticket 03), so
    // the copy must not promise a shape the child may not have.
    for (const text of [team, teamNode.label]) {
      expect(text.toLowerCase()).not.toMatch(/parallel|multi-agent|concurrent/);
    }
  });

  it('does not promise a revision loop on a plain mounted workflow', () => {
    // A mounted workflow loops only if the child does. Claiming it here would
    // be the same false claim the tiering bug made, one level down.
    expect(workflow.toLowerCase()).not.toContain('loop');
  });

  it('says the same of the category, which covers both', () => {
    const compose = CATEGORIES.find((c) => c.id === CATEGORY.compose)?.description ?? '';
    expect(compose.toLowerCase()).not.toContain('revision loop');
  });

  it('tells a reader that a mount stays linked to its original', () => {
    // The distinction ticket 01 left to this one: mounting keeps the link,
    // starting from a template severs it at creation.
    const compose = CATEGORIES.find((c) => c.id === CATEGORY.compose)?.description ?? '';
    expect(`${compose} ${workflow}`.toLowerCase()).toMatch(/every instance|stays linked|reference/);
  });

  it('keeps both descriptions short enough to read in a palette', () => {
    for (const text of [workflow, team]) {
      expect(text.length).toBeGreaterThan(40);
      expect(text.length).toBeLessThanOrEqual(200);
    }
  });
});

/**
 * production-ready ticket 03 — the copy half.
 *
 * `Expected outcome` never reaches the compiler: `_subgraph` reads `workflow`
 * and `overrides` and nothing else. Its placeholder said "enforced by its
 * grader", so a user wrote a constraint, reasonably believed it bound the run,
 * and got no signal that it did not.
 *
 * That is the RouterNode lesson in a different field — a surface presenting a
 * machine-owned promise as if it were configuration.
 */
describe('the Team outcome field does not claim an enforcement it has not got', () => {
  const outcome = teamNode.fields.find((field) => field.key === 'outcome');

  it('still exists and still shows on the card', () => {
    // The fix is not to hide it: a reader of the card wants to know what the
    // box is for, and it is genuinely useful documentation.
    expect(outcome).toBeDefined();
    expect(outcome?.onCard).toBe(true);
  });

  it('never says enforced, required or must', () => {
    const copy = `${outcome?.label ?? ''} ${outcome?.placeholder ?? ''}`.toLowerCase();
    expect(copy).not.toMatch(/enforc|required|must deliver/);
  });

  it('names itself as documentation where a user reads the label', () => {
    expect((outcome?.label ?? '').toLowerCase()).toContain('documentation');
  });

  it('points at where enforcement actually lives', () => {
    // Naming the real mechanism is what stops the misunderstanding from
    // recurring — "it is not enforced" alone leaves nowhere to go.
    expect((outcome?.hint ?? '').toLowerCase()).toMatch(/grader/);
    expect((outcome?.hint ?? '').toLowerCase()).toMatch(/child|workflow/);
  });
});
