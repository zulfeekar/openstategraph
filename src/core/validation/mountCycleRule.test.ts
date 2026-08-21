import { describe, expect, it } from 'vitest';
import { mountCycleRefusal, mountGestureRefusal } from './mountCycleRule';

describe('mountCycleRefusal', () => {
  it('refuses the document you are standing in, in the compiler’s own words', () => {
    expect(mountCycleRefusal('concierge', ['concierge'])).toBe(
      "Workflow 'concierge' mounts itself " +
        '(concierge -> concierge); a mount cycle can never terminate',
    );
  });

  it('refuses an ancestor several levels up the drill trail', () => {
    // Three deep: the cycle a user would create is not with the document in
    // front of them, which is the whole reason ancestry is a list.
    expect(mountCycleRefusal('concierge', ['concierge', 'chinook-assistant', 'sql-analyst'])).toBe(
      "Workflow 'concierge' mounts itself " +
        '(concierge -> chinook-assistant -> sql-analyst -> concierge); ' +
        'a mount cycle can never terminate',
    );
  });

  it('spells the chain with the whole trail, not just the matching rung', () => {
    const refusal = mountCycleRefusal('b', ['a', 'b', 'c']);
    expect(refusal).toContain('(a -> b -> c -> b)');
  });

  it('allows a package that is nowhere on the trail', () => {
    expect(mountCycleRefusal('chinook-assistant', ['concierge'])).toBeNull();
    expect(mountCycleRefusal('anything', [])).toBeNull();
  });

  it('keeps a forward reference legal — free text names packages not built yet', () => {
    expect(mountCycleRefusal('not-built-yet', ['concierge', 'chinook-assistant'])).toBeNull();
  });

  it('says nothing about an unnamed package', () => {
    expect(mountCycleRefusal('', ['concierge'])).toBeNull();
    expect(mountCycleRefusal('   ', ['concierge'])).toBeNull();
  });

  it('compares trimmed slugs, so a stray space cannot smuggle a cycle past it', () => {
    expect(mountCycleRefusal('  concierge  ', ['concierge'])).not.toBeNull();
    expect(mountCycleRefusal('concierge', ['  concierge  '])).not.toBeNull();
  });

  it('ignores blank rungs rather than matching an empty slug against them', () => {
    expect(mountCycleRefusal('x', ['', '  '])).toBeNull();
  });
});

/**
 * `workflow-gallery` 65. The sentence above is the *compiler's*, and it is a
 * statement of fact about a document that already declares the mount — which
 * is exactly right where a mount node exists and a slug has been typed into
 * it, and exactly wrong on a palette row, where nothing has been dropped yet.
 * A freshly scaffolded package with no mount node in it was told, on the first
 * screen after `new`, that it mounts itself.
 *
 * So the palette asks a different question — *what would this gesture do?* —
 * and gets a conditional answer. Same path, same closing clause, same
 * vocabulary; the difference is tense, and the tense is the whole defect.
 */
describe('mountGestureRefusal', () => {
  it('speaks of the gesture, never of the document as it stands', () => {
    const refusal = mountGestureRefusal('routed-demo', ['routed-demo']);
    expect(refusal).toBe(
      "Mounting 'routed-demo' here would make it mount itself " +
        '(routed-demo -> routed-demo); a mount cycle can never terminate',
    );
    // The accusation a mountless package was reading about itself.
    expect(refusal).not.toContain("Workflow 'routed-demo' mounts itself");
  });

  it('still spells the path out, which is what makes a true refusal useful', () => {
    expect(mountGestureRefusal('concierge', ['concierge', 'chinook-assistant'])).toContain(
      '(concierge -> chinook-assistant -> concierge)',
    );
  });

  it('closes on the compiler’s own clause, so both readings share a vocabulary', () => {
    expect(mountGestureRefusal('a', ['a'])).toContain('a mount cycle can never terminate');
  });

  it('refuses exactly what the compiler’s rule refuses, and nothing more', () => {
    // Widening or narrowing here would let the editor and the server disagree,
    // which is the one failure this whole family must not have.
    const cases: ReadonlyArray<readonly [string, readonly string[]]> = [
      ['concierge', ['concierge']],
      ['concierge', ['a', 'concierge', 'b']],
      ['not-built-yet', ['concierge']],
      ['', ['concierge']],
      ['  ', ['concierge']],
      ['  concierge  ', ['concierge']],
      ['x', ['', '  ']],
      ['anything', []],
    ];
    for (const [candidate, ancestry] of cases) {
      expect([candidate, ancestry, mountGestureRefusal(candidate, ancestry) === null]).toEqual([
        candidate,
        ancestry,
        mountCycleRefusal(candidate, ancestry) === null,
      ]);
    }
  });
});
