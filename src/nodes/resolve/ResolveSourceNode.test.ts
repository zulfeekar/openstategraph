import { describe, expect, it } from 'vitest';
import { CATEGORIES, CATEGORY } from '../vocabulary';
import { NODE_TYPE } from '../index';
import {
  DEFAULT_WHEN_UNDECIDED,
  FIELD_CATALOGUE,
  FIELD_QUANTITY,
  FIELD_WHEN_UNDECIDED,
  RESOLVE_SOURCE_TYPE,
  resolveSourceExecutor,
  resolveSourceNode,
  type ResolveSourceNodeModel,
} from './ResolveSourceNode';
import { resolveVocabularyNode } from './ResolveVocabularyNode';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * `launch-readiness/150` — the editor half.
 *
 * *"In the may number 1664 is given in the table. I do not understand where
 * this number comes from."* Three of seven complaints in one round of user
 * feedback were that failure. These tests pin what makes the node an answer
 * to it: it is placeable, it names what the figures are, and it cannot be
 * configured into silence about which store answered.
 */

const field = (key: string) => resolveSourceNode.fields.find((f) => f.key === key);

describe('resolve.source — placed, not assumed', () => {
  it('is registered in the catalogue under its own id', () => {
    expect(NODE_TYPE.resolveSource).toBe(RESOLVE_SOURCE_TYPE);
    const workbench = makeWorkbench();
    workbench.controller.nodes.add(RESOLVE_SOURCE_TYPE, { x: 0, y: 0 });
    const node = workbench.model
      .nodes()
      .find((n) => n.type === RESOLVE_SOURCE_TYPE) as ResolveSourceNodeModel;
    expect(node).toBeDefined();
    expect(node.subtitle.toLowerCase()).toContain('no source catalogue');
  });

  it('takes one question in and fans its result out', () => {
    const ports = resolveSourceNode.ports({});
    const question = ports.find((p) => p.id === 'question');
    const result = ports.find((p) => p.id === 'result');
    expect(question?.direction).toBe('in');
    // Cardinality belongs to the port: one upstream text, many consumers.
    expect(question?.maxConnections).toBe(1);
    expect(result?.direction).toBe('out');
    expect(result?.maxConnections).toBeNull();
  });

  it('declares no branch port, so it cannot route or abstain on its own', () => {
    // Several live sources and no default is `guardrails/06`'s abstain, which
    // is open and unbuilt. The seam is left rather than a second way to ask
    // being invented here — a resolver decides nothing.
    const ports = resolveSourceNode.ports({});
    expect(ports.filter((p) => p.direction === 'out')).toHaveLength(1);
    expect(ports.map((p) => p.type)).not.toContain('feedback');
  });
});

describe('what a developer may configure', () => {
  it('asks which catalogue it reads, and requires one', () => {
    const catalogue = field(FIELD_CATALOGUE);
    expect(catalogue?.kind).toBe('text');
    expect(catalogue?.required).toBe(true);
    expect(catalogue?.onCard).toBe(true);
  });

  it('asks what the figures are, because “which source” is only answerable about something', () => {
    const quantity = field(FIELD_QUANTITY);
    expect(quantity?.kind).toBe('text');
    // Optional: a catalogue that answers one quantity needs no label.
    expect(quantity?.required).toBeFalsy();
    expect((quantity?.hint ?? '').toLowerCase()).toContain('outages');
  });

  it('lets a developer word the undecided case, and ships a default that says it', () => {
    const undecided = field(FIELD_WHEN_UNDECIDED);
    expect(undecided?.kind).toBe('textarea');
    expect(undecided?.defaultValue).toBe(DEFAULT_WHEN_UNDECIDED);
    expect(String(undecided?.defaultValue).toLowerCase()).toContain('none is declared the default');
  });

  it('offers no switch that turns the coverage report off', () => {
    // The constraint carried over from `135`: a figure with no stated source
    // reads exactly like a figure from the wrong one. A toggle here would be
    // a supported way back into that state.
    for (const schema of resolveSourceNode.fields) {
      expect(schema.kind).not.toBe('toggle');
    }
    expect((field(FIELD_WHEN_UNDECIDED)?.hint ?? '').toLowerCase()).toContain('not optional');
  });
});

describe('where it sits, and what it promises', () => {
  it('is filed under Resolution beside its sibling', () => {
    expect(resolveSourceNode.category).toBe(CATEGORY.resolve);
    expect(resolveVocabularyNode.category).toBe(CATEGORY.resolve);
    const section = CATEGORIES.find((c) => c.id === CATEGORY.resolve);
    expect(section?.label).toContain('molecules');
  });

  it('is a different question from the vocabulary resolver, and says so', () => {
    // Two resolvers in one section is a place a reader can conflate them.
    // One answers "what does this word mean here"; this one answers "which
    // store answered". The copy has to separate them on the card.
    expect(resolveSourceNode.label).not.toBe(resolveVocabularyNode.label);
    expect((resolveSourceNode.description ?? '').toLowerCase()).toContain('alternatives');
    expect((resolveVocabularyNode.description ?? '').toLowerCase()).not.toContain('alternatives');
  });

  it('promises the alternatives, not merely the choice', () => {
    // The payload of this node is what it did *not* use. A card that promised
    // only "names the source" would be describing half the ticket.
    const copy = `${resolveSourceNode.label} ${resolveSourceNode.description}`.toLowerCase();
    expect(copy).toContain('did not take');
  });

  it('says on the card that it costs no model call', () => {
    expect((resolveSourceNode.description ?? '').toLowerCase()).toContain('no model');
  });

  it('refuses in the browser preview rather than inventing a source', async () => {
    const result = await resolveSourceExecutor.execute({ log: () => {} } as never);
    expect(result.ok).toBe(false);
  });
});
