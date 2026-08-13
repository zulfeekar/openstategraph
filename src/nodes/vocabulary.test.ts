import { describe, expect, it } from 'vitest';
import { CATEGORIES, CATEGORY } from './vocabulary';
import { NODE_TYPE } from './index';
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

  it('files a mounted workflow as an organism — it brings its own nodes and state', () => {
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
 * production-ready tickets 02 and 16.
 *
 * There were two violet cards — "Workflow" and "Team" — with the same glyph,
 * the same ports and the same category, and research had already established
 * they **compile identically**: one backend builder, no branch.
 *
 * Ticket 02 made each state its contract, which is what let 16 see there was
 * only one contract: Team's whole difference was a glyph, an `outcome` field
 * that turned out to be documentation, and a census note the *child document*
 * earns. Schema v3 collapsed it away, so the palette now offers one organism
 * and the loop is learned from the badge rather than from picking the right
 * card.
 *
 * These assert *properties* of the copy, not its exact words: a test that
 * freezes marketing text makes improving it a failure.
 */
describe('the one organism states the contract it offers', () => {
  const workflow = subgraphNode.description ?? '';

  it('is the only mount the palette offers', () => {
    // Registering the collapsed id as well would let a user create a node that
    // documents are migrated *away* from.
    expect(NODE_TYPE.subgraph).toBe('workflow.subgraph');
    expect(Object.values(NODE_TYPE)).not.toContain('team.workflow');
  });

  it('says a mounted workflow is isolated — the thing a user cannot guess', () => {
    // Isolation is the whole mechanism: the child sees a task and reports a
    // result, and never the parent's state or messages.
    expect(workflow.toLowerCase()).toMatch(/isolat|its own|task in/);
  });

  it('never calls a mount parallel or multi-agent', () => {
    // Whatever shape the child has is the child's, and the census reads it.
    expect(`${workflow} ${subgraphNode.label}`.toLowerCase()).not.toMatch(
      /parallel|multi-agent|concurrent/,
    );
  });

  it('does not promise a revision loop on the card itself', () => {
    // The badge is earned from the mounted document by `summarizeComposition`;
    // asserting it here would be the same fact said twice, with one of the two
    // eventually wrong.
    expect(workflow.toLowerCase()).not.toContain('loop');
  });

  it('says the same of the category, which covers it', () => {
    const compose = CATEGORIES.find((c) => c.id === CATEGORY.compose)?.description ?? '';
    expect(compose.toLowerCase()).not.toContain('revision loop');
  });

  it('tells a reader that a mount stays linked to its original', () => {
    const compose = CATEGORIES.find((c) => c.id === CATEGORY.compose)?.description ?? '';
    expect(`${compose} ${workflow}`.toLowerCase()).toMatch(/every instance|stays linked|reference/);
  });

  it('keeps the description short enough to read in a palette', () => {
    expect(workflow.length).toBeGreaterThan(40);
    expect(workflow.length).toBeLessThanOrEqual(200);
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
describe('the mount outcome field does not claim an enforcement it has not got', () => {
  // Moved from the collapsed `team.workflow` to the one mount type, on purpose:
  // `MIGRATIONS[2]` carries authored outcome prose across, and it would have
  // had nowhere to land if the field had gone with the node (ticket 16).
  const outcome = subgraphNode.fields.find((field) => field.key === 'outcome');

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

/**
 * production-ready ticket 05 — the mount's slug is chosen, not typed.
 *
 * It was `kind: 'text'` with a placeholder: nothing populated it, nothing
 * validated it, and nothing told a developer what existed. A typo produced a
 * mount that resolved to nothing.
 */
describe('the mount slug field offers what exists', () => {
  const slugField = subgraphNode.fields.find((field) => field.key === 'workflow');

  it('is a combobox — pick what exists, type what does not yet', () => {
    // Decided rather than defaulted, which is what the ticket asked for. A
    // listbox would make a typo unreachable *and* make it impossible to mount
    // a package you have not built yet; drafting parent-first is a real way
    // to work, so the suggestions keep typos off the normal path instead of
    // outlawing the order.
    expect(slugField?.kind).toBe('combobox');
  });

  it('still writes the same value a text box wrote', () => {
    // `data.workflow` is a serialised contract read by the compiler; changing
    // the control must not change what lands in the document.
    expect(slugField?.key).toBe('workflow');
    expect(slugField?.defaultValue).toBe('');
  });

  it('draws its suggestions from the live catalogue, not a literal', () => {
    const options = slugField && 'options' in slugField ? slugField.options : undefined;
    expect(typeof options).toBe('function');
  });

  it('says what to do when there is nothing to suggest', () => {
    // An empty dropdown with no explanation reads as broken.
    expect(String((slugField as { emptyHint?: string } | undefined)?.emptyHint ?? '')).not.toBe('');
  });
});
