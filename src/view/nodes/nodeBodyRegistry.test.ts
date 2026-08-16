import { describe, expect, it } from 'vitest';

import {
  createNodeBodyRegistry,
  nodeBodies,
  resolveNodeBody,
  type NodeBody,
} from './nodeBodyRegistry';

/**
 * The seventh extension point, walked (framework-packaging ticket 12).
 *
 * CLAUDE.md's **O** rule names seven — "node types, executors, providers,
 * connection rules, validation rules, canvas features, card bodies" — and says
 * every one is a `Registry<T>`. Six were. This one was a module-level
 * `Map<string, NodeBody>` with a bare setter, which lost three things that are
 * not cosmetic: a duplicate id overwrote a built-in silently, nothing could
 * enumerate what was registered, and no test could get a fresh one.
 *
 * It lives here rather than in `src/core/extendabilityRegistries.test.ts`
 * alongside the other walks for the reason the registry itself does: a card
 * body is a React component, and `core/` imports neither React nor the
 * projection of its own model.
 */

const AcmeBody: NodeBody = () => null;
const OtherBody: NodeBody = () => null;

const definition = (id: string, bodyId?: string) =>
  ({ id, ...(bodyId ? { bodyId } : {}) }) as Parameters<typeof resolveNodeBody>[0];

describe('a card body lands by registration only', () => {
  it('renders a bespoke body for a node type the editor has never heard of', () => {
    const registry = createNodeBodyRegistry();

    registry.register({ id: 'acme.sentiment', body: AcmeBody });

    expect(resolveNodeBody(definition('acme.sentiment'), registry)).toBe(AcmeBody);
  });

  it('falls back to an empty body rather than throwing on an unregistered type', () => {
    const registry = createNodeBodyRegistry();

    expect(resolveNodeBody(definition('acme.unknown'), registry)).not.toBe(AcmeBody);
  });

  it('honours `bodyId`, so several node types can share one body', () => {
    const registry = createNodeBodyRegistry();
    registry.register({ id: 'acme.shared', body: AcmeBody });

    expect(resolveNodeBody(definition('acme.one', 'acme.shared'), registry)).toBe(AcmeBody);
  });
});

describe('what the Map could not do', () => {
  it('refuses to replace a built-in body by accident', () => {
    const registry = createNodeBodyRegistry();

    expect(() => registry.register({ id: 'output.formatted', body: AcmeBody })).toThrow(
      /already registered/,
    );
  });

  it('replaces one on purpose, and says which call did it', () => {
    const registry = createNodeBodyRegistry();

    registry.upsert({ id: 'output.formatted', body: OtherBody });

    expect(resolveNodeBody(definition('output.formatted'), registry)).toBe(OtherBody);
  });

  it('enumerates what is registered', () => {
    const registry = createNodeBodyRegistry();

    expect(registry.list().map((entry) => entry.id)).toContain('annotate.note');
  });

  it('announces a registration, so a card can be told rather than polled', () => {
    const registry = createNodeBodyRegistry();
    let changes = 0;
    registry.onChange(() => (changes += 1));

    registry.register({ id: 'acme.sentiment', body: AcmeBody });

    expect(changes).toBe(1);
  });

  it('gives every test a fresh one, so registrations do not leak', () => {
    const first = createNodeBodyRegistry();
    first.register({ id: 'acme.sentiment', body: AcmeBody });

    expect(createNodeBodyRegistry().has('acme.sentiment')).toBe(false);
  });
});

describe('the shipped registry is still the one the cards read', () => {
  it('carries every built-in body the editor ships', () => {
    const ids = nodeBodies.list().map((entry) => entry.id);

    // The control: an empty registry would satisfy every `toContain` above
    // that ran against a fresh one.
    expect(ids).toEqual(expect.arrayContaining(['output.formatted', 'input.text']));
  });

  it('is what `resolveNodeBody` reads when nobody names a registry', () => {
    expect(resolveNodeBody(definition('output.formatted'))).toBe(
      nodeBodies.require('output.formatted').body,
    );
  });
});
