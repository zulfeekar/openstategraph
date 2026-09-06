import { describe, expect, it } from 'vitest';
import { CATEGORIES, CATEGORY } from '../vocabulary';
import { NODE_TYPE } from '../index';
import {
  DEFAULT_MAX_ENTRIES,
  DEFAULT_WHEN_UNCOVERED,
  FIELD_MAX_ENTRIES,
  FIELD_SOURCE,
  FIELD_WHEN_UNCOVERED,
  RESOLVE_VOCABULARY_TYPE,
  resolveVocabularyExecutor,
  resolveVocabularyNode,
  type ResolveVocabularyNodeModel,
} from './ResolveVocabularyNode';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * `launch-readiness/135` — the editor half.
 *
 * The capability existed and could not be placed: a package function wired by
 * hand-editing `workflow.json`. These tests pin the three things lifting it
 * into a node type was for — it is placeable, it is configurable, and it
 * cannot be configured into silence about its own coverage.
 */

const field = (key: string) => resolveVocabularyNode.fields.find((f) => f.key === key);

describe('resolve.vocabulary — placed, not hand-wired', () => {
  it('is registered in the catalogue under its own id', () => {
    expect(NODE_TYPE.resolveVocabulary).toBe(RESOLVE_VOCABULARY_TYPE);
    const workbench = makeWorkbench();
    workbench.controller.nodes.add(RESOLVE_VOCABULARY_TYPE, { x: 0, y: 0 });
    const node = workbench.model
      .nodes()
      .find((n) => n.type === RESOLVE_VOCABULARY_TYPE) as ResolveVocabularyNodeModel;
    expect(node).toBeDefined();
    expect(node.subtitle.toLowerCase()).toContain('no vocabulary source');
  });

  it('takes one question in and fans its result out', () => {
    const ports = resolveVocabularyNode.ports({});
    const question = ports.find((p) => p.id === 'question');
    const result = ports.find((p) => p.id === 'result');
    expect(question?.direction).toBe('in');
    // Cardinality belongs to the port: one upstream text, many consumers.
    expect(question?.maxConnections).toBe(1);
    expect(result?.direction).toBe('out');
    expect(result?.maxConnections).toBeNull();
  });

  it('declares no `feedback` port, so it cannot close a loop', () => {
    // A resolver decides nothing, so it must not be able to route or revise.
    const types = resolveVocabularyNode.ports({}).map((p) => p.type);
    expect(types).not.toContain('feedback');
  });
});

describe('what a developer may configure', () => {
  it('asks which source it reads, and requires one', () => {
    const source = field(FIELD_SOURCE);
    expect(source?.kind).toBe('text');
    expect(source?.required).toBe(true);
    expect(source?.onCard).toBe(true);
  });

  it('caps how many entries reach the model, after the ranking', () => {
    const cap = field(FIELD_MAX_ENTRIES);
    expect(cap?.kind).toBe('slider');
    expect(cap?.defaultValue).toBe(DEFAULT_MAX_ENTRIES);
    // The hint has to say the ranking runs first: `launch-readiness/130` was
    // a cap applied to an arrival order, which let thread scheduling pick the
    // axis before the model ran.
    expect((cap?.hint ?? '').toLowerCase()).toContain('rank');
  });

  it('lets a developer word the uncovered case, and ships a default that says it', () => {
    const uncovered = field(FIELD_WHEN_UNCOVERED);
    expect(uncovered?.kind).toBe('textarea');
    expect(uncovered?.defaultValue).toBe(DEFAULT_WHEN_UNCOVERED);
    expect(String(uncovered?.defaultValue ?? '')).not.toHaveLength(0);
    expect(String(uncovered?.defaultValue).toLowerCase()).toContain('unambiguous');
  });

  it('offers no switch that turns the coverage report off', () => {
    // The constraint that made this ticket `L`: a prefetch that finds nothing
    // looks exactly like a term that is not ambiguous. A toggle here would be
    // a supported way back into that state.
    for (const schema of resolveVocabularyNode.fields) {
      expect(schema.kind).not.toBe('toggle');
    }
    expect((field(FIELD_WHEN_UNCOVERED)?.hint ?? '').toLowerCase()).toContain('not optional');
  });
});

describe('where it sits, and what it promises', () => {
  it('is filed under Resolution rather than Reasoning & control', () => {
    // A resolver decides nothing. Filing it under the reasoning heading would
    // make that heading false — the same argument that gave Memory its own.
    expect(resolveVocabularyNode.category).toBe(CATEGORY.resolve);
    const section = CATEGORIES.find((c) => c.id === CATEGORY.resolve);
    expect(section?.label).toContain('molecules');
    expect((section?.description ?? '').toLowerCase()).toContain('covered');
  });

  it('never claims to discover tables or columns', () => {
    // Measured 2026-08-27: the index behind the original function overlapped
    // its domain's lenses on 3 tables of 38. Vocabulary ports; table coverage
    // does not, and the card must not sell the one as the other.
    const copy = `${resolveVocabularyNode.label} ${resolveVocabularyNode.description}`;
    expect(copy.toLowerCase()).not.toMatch(/table|column|schema/);
  });

  it('says on the card that it costs no model call', () => {
    expect((resolveVocabularyNode.description ?? '').toLowerCase()).toContain('no model');
  });

  it('refuses in the browser preview rather than inventing a resolution', async () => {
    const result = await resolveVocabularyExecutor.execute({
      log: () => {},
    } as never);
    expect(result.ok).toBe(false);
  });
});
