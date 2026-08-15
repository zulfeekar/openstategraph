import { describe, expect, it } from 'vitest';
import {
  GUARDRAIL_BUILTIN_ENTITIES,
  GUARDRAIL_STRATEGIES,
  GUARDRAIL_TYPE,
  guardrailNode,
  type GuardrailNodeModel,
} from './GuardrailNode';
import { CATEGORIES, CATEGORY, PORT } from '../vocabulary';
import { NODE_TYPE } from '../index';
import { defaultsFrom, resolveOptions, type SelectFieldSchema } from '@core/model/contracts/fields';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * The Guardrail atom — a policy table you can read off the card.
 *
 * The card is where the map's two hardest decisions become visible or fail
 * to: **the unit of policy is `entity x direction`**, and **position is the
 * scope**. The second is what these tests mostly guard: there is no
 * `applyToInput`/`applyToOutput` control here and there must never be one,
 * because a flag that can disagree with the wire is `api/audience.py`'s
 * `advisor` defect drawn on a canvas.
 */
const field = (key: string) => guardrailNode.fields.find((f) => f.key === key);
const ports = (data = defaultsFrom(guardrailNode.fields)) => guardrailNode.ports(data);
const port = (id: string) => ports().find((p) => p.id === id);

describe('the policy table is the card', () => {
  it('carries the table as a field schema, not as prose', () => {
    // One declaration drives the card, the inspector, the defaults and the
    // serialized document — CLAUDE.md's DRY rule for node configuration.
    expect(field('policy')?.kind).toBe('repeatable-group');
  });

  it('offers every entity LangChain detects, and says which are built in', () => {
    expect(GUARDRAIL_BUILTIN_ENTITIES).toEqual([
      'email',
      'credit_card',
      'ip',
      'mac_address',
      'url',
    ]);
  });

  it('offers exactly the strategies the runtime implements', () => {
    // A card offering a fifth strategy the compiler ignores is a card that
    // lies about what is enforced.
    expect(GUARDRAIL_STRATEGIES).toEqual(['pass', 'redact', 'mask', 'hash', 'block']);
  });

  it('lets a developer say "allowed here" rather than leaving a silence', () => {
    // `pass` is the row that makes the owner's requirement legible: email
    // inbound must pass, and an absent row cannot state that on purpose.
    const strategy = (field('policy') as { fields: readonly SelectFieldSchema[] }).fields.find(
      (f) => f.key === 'strategy',
    );
    expect(resolveOptions(strategy!).map((o) => o.value)).toContain('pass');
  });

  it('takes a custom pattern as text, because a regex is data and a lambda is not', () => {
    const detector = (
      field('policy') as { fields: readonly { key: string; kind: string }[] }
    ).fields.find((f) => f.key === 'detector');
    expect(detector?.kind).toBe('text');
  });

  it('lets a developer write the refusal, because that copy is theirs', () => {
    expect(field('blockedMessage')?.kind).toBe('textarea');
  });

  it('shows what the machinery already says, read-only beside the editable part', () => {
    // The prompt-composition rule generalised: a developer writing their own
    // refusal must be able to see the default rather than guess at it, and
    // must not be handed it pre-filled in an editable box (the original
    // RouterNode bug).
    const locked = field('policyNote');
    expect(locked?.kind).toBe('readonly');
    expect(field('blockedMessage')?.defaultValue).toBe('');
  });
});

describe('position is the scope', () => {
  it('offers no direction control at all', () => {
    const keys = guardrailNode.fields.map((f) => f.key);
    for (const forbidden of ['direction', 'applyToInput', 'applyToOutput', 'applyToToolResults']) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it('slots between existing nodes with no new port type', () => {
    expect(port('content')?.type).toBe(PORT.result);
    expect(port('allowed')?.type).toBe(PORT.result);
    expect(port('blocked')?.type).toBe(PORT.result);
  });

  it('accepts plain text in, so it drops straight after an Input', () => {
    expect(port('content')?.accepts ?? []).toBeDefined();
    // `result` already widens to `text` at the port-type level, which is what
    // makes Input -> Guardrail wireable with no special case.
    expect(port('content')?.direction).toBe('in');
  });

  it('never declares a feedback port, so it cannot close a cycle', () => {
    // `feedback` is the only type `acyclicRule` lets a cycle close on, and a
    // guardrail is not a revision loop. Declaring one here would make an
    // accidental cycle drawable for the first time since ticket 09.
    expect(ports().some((p) => p.type === PORT.feedback)).toBe(false);
  });
});

describe('a refusal is a wire you can follow', () => {
  it('has two branch outputs, like the Router and the Grader', () => {
    expect(port('allowed')?.branch).toBe(true);
    expect(port('blocked')?.branch).toBe(true);
  });

  it('describes the blocked wire as going to the user, not back upstream', () => {
    expect(port('blocked')?.description?.toLowerCase()).toMatch(/refus|output|user/);
  });
});

describe('the catalogue registers it honestly', () => {
  it('is registered and reachable by id', () => {
    expect(NODE_TYPE.guardrail).toBe(GUARDRAIL_TYPE);
    expect(makeWorkbench().registry.nodeTypes.get(GUARDRAIL_TYPE)).toBeDefined();
  });

  it('claims a tier its behaviour earns', () => {
    // `vocabulary.test.ts` polices the tier suffix; this polices the choice.
    // One decision step that dispatches on a branch is what `Router`,
    // `Grader` and `Human approval` already are, so it files with them
    // rather than inventing a section whose tier nothing would justify.
    expect(guardrailNode.category).toBe(CATEGORY.agent);
    expect(CATEGORIES.find((c) => c.id === CATEGORY.agent)?.label).toContain('molecules');
  });

  it('is findable by the words someone with this problem would type', () => {
    const words = guardrailNode.keywords ?? [];
    for (const term of ['pii', 'redact', 'guardrail', 'policy']) {
      expect(words).toContain(term);
    }
  });

  it('does not promise injection screening, which it does not do', () => {
    // Ticket 04: these detectors are deterministic shapes. Copy implying
    // otherwise is the exact thing that ticket says the docs must stop doing.
    const copy = `${guardrailNode.label} ${guardrailNode.description}`.toLowerCase();
    expect(copy).not.toMatch(/injection|jailbreak|prompt attack/);
  });
});

describe('the browser preview refuses rather than pretending', () => {
  it('reports that the policy is applied by the Python runtime', async () => {
    const { guardrailExecutor } = await import('./GuardrailNode');
    const outcome = await guardrailExecutor.execute({
      log: () => {},
    } as never);
    expect(outcome.ok).toBe(false);
  });
});

describe('the model reads its own table', () => {
  it('reports the rows a developer configured', () => {
    const workbench = makeWorkbench();
    workbench.controller.nodes.add(GUARDRAIL_TYPE, { x: 0, y: 0 });
    const node = workbench.model
      .nodes()
      .find((n) => n.type === GUARDRAIL_TYPE) as GuardrailNodeModel;

    workbench.controller.nodes.setField(node.id, 'policy', [
      { id: 'r1', entity: 'email', strategy: 'pass', detector: '' },
      { id: 'r2', entity: 'credit_card', strategy: 'block', detector: '' },
    ]);

    const reread = workbench.model.node(node.id) as GuardrailNodeModel;
    expect(reread.policy.map((row) => `${row.entity}:${row.strategy}`)).toEqual([
      'email:pass',
      'credit_card:block',
    ]);
  });

  it('summarises the table on the card subtitle so the policy is readable at a glance', () => {
    const workbench = makeWorkbench();
    workbench.controller.nodes.add(GUARDRAIL_TYPE, { x: 0, y: 0 });
    const node = workbench.model
      .nodes()
      .find((n) => n.type === GUARDRAIL_TYPE) as GuardrailNodeModel;

    workbench.controller.nodes.setField(node.id, 'policy', [
      { id: 'r1', entity: 'email', strategy: 'redact', detector: '' },
    ]);

    expect((workbench.model.node(node.id) as GuardrailNodeModel).subtitle).toContain('email');
  });

  it('says so plainly when nothing is configured', () => {
    const workbench = makeWorkbench();
    workbench.controller.nodes.add(GUARDRAIL_TYPE, { x: 0, y: 0 });
    const node = workbench.model
      .nodes()
      .find((n) => n.type === GUARDRAIL_TYPE) as GuardrailNodeModel;

    // A guardrail with an empty table enforces nothing, and a card that reads
    // like a working guard while enforcing nothing is the worst outcome
    // available here. (Reached by clearing the prebuilt rows, which is a
    // thing a developer does — the shipped default is two rules, following
    // the Grader's prebuilt criteria rather than a blank field.)
    workbench.controller.nodes.setField(node.id, 'policy', []);
    expect((workbench.model.node(node.id) as GuardrailNodeModel).subtitle.toLowerCase()).toMatch(
      /no |nothing|empty/,
    );
  });
});
