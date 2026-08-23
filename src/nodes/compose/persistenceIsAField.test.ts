import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { subgraphNode } from './SubgraphNode';

/**
 * **A mount says how long its child remembers — `organisms-first-class` 30.**
 *
 * The backend tri-state (`compile/mount_persistence.py`) is LangGraph's own
 * `.compile(checkpointer=None|True|False)`. This pins the half a person meets:
 * the option set matches the backend's, the default is the behaviour every
 * document saved before the field already had, and the copy carries the doc's
 * conflict warning rather than presenting per-thread as the upgrade.
 *
 * The words are checked, not just the values, because this field changes the
 * promise the node's own description makes — "one isolated step — task in,
 * answer out". A mount that remembers is a different promise, and a surface
 * that does not say so is the defect.
 */
describe('the mount persistence field', () => {
  const field = subgraphNode.fields.find((entry) => entry.key === 'persistence');
  const options = field && 'options' in field && Array.isArray(field.options) ? field.options : [];
  const hint = field && 'hint' in field ? ((field.hint as string) ?? '') : '';

  it('offers exactly the three values the backend resolves', () => {
    // The Python side is the authority — `MOUNT_PERSISTENCE_MODES` — and an
    // option it does not know is silently resolved back to the default, which
    // is a control that lies. Kept in the doc's own order.
    expect(options.map((option) => option.value)).toEqual([
      'per-invocation',
      'per-thread',
      'stateless',
    ]);
  });

  it('defaults to the behaviour every existing document already has', () => {
    // The isolation inverse, on this side: `data.persistence` is a new
    // serialised key, so its absence must mean exactly what a mount meant
    // before it existed.
    expect(field && 'defaultValue' in field ? field.defaultValue : undefined).toBe(
      'per-invocation',
    );
    expect(options[0]?.label).toContain('default');
  });

  it('warns that two of them at once conflict', () => {
    // `langgraph/use-subgraphs.mdx`: stateful subgraphs write to one
    // checkpoint namespace, so parallel calls to the same subgraph conflict.
    // Carried at the field, in the field's own vocabulary.
    expect(hint).toContain('conflict');
  });

  it('does not repeat the claim that a stateless mount cannot pause', () => {
    // `organisms-first-class` 65, measured: a mount is a closure, so the
    // child's `interrupt()` is held by the *parent's* checkpointer. A
    // stateless mount pauses, resumes and answers — the label and the hint
    // both said it could not, which is the surface a person actually reads.
    const words = `${options.map((option) => option.label).join(' ')} ${hint}`.toLowerCase();
    expect(words).not.toContain('cannot pause');
    expect(words).not.toContain('can never wait');
  });

  it('says what answering an approval inside a stateless mount costs', () => {
    // The cost is the fact: nothing was kept, so answering runs the mounted
    // workflow again from its first step and everything before the approval
    // happens a second time. The compiler reports the same thing before the
    // run (`Finding.STATELESS_MOUNT_REDOES`); one fact, two surfaces.
    const words = `${options.map((option) => option.label).join(' ')} ${hint}`.toLowerCase();
    expect(words).toContain('approval');
    expect(words).toContain('first step');
    expect(words).toContain('second time');
  });

  it('never offers remembering as the better option', () => {
    // The doc calls per-thread the exception. Copy that reads as an upgrade
    // is how an exception becomes the default anyway.
    for (const word of ['better', 'recommended', 'upgrade', 'improved']) {
      expect(hint.toLowerCase()).not.toContain(word);
    }
  });

  it('is a field of its own, never smuggled into the overrides editor', () => {
    // `docs/decisions/mount-overrides.md`: an override *narrows* a mount. A
    // persistence mode redefines the child's lifecycle, which is a different
    // kind of thing and gets a different control.
    const overrides = subgraphNode.fields.find((entry) => entry.key === 'overrides');
    expect(overrides).toBeDefined();
    expect(field).toBeDefined();
    expect(field).not.toBe(overrides);
    const decision = readFileSync(
      fileURLToPath(new URL('../../../docs/decisions/mount-overrides.md', import.meta.url)),
      'utf8',
    );
    expect(decision).toContain('deliberately not an override');
  });
});
