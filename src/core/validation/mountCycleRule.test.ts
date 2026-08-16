import { describe, expect, it } from 'vitest';
import { mountCycleRefusal } from './mountCycleRule';

describe('mountCycleRefusal', () => {
  it('refuses the document you are standing in, in the compiler’s own words', () => {
    expect(mountCycleRefusal('concierge', ['concierge'])).toBe(
      "Workflow 'concierge' includes itself through its subgraphs " +
        '(concierge -> concierge); a subgraph cycle can never terminate',
    );
  });

  it('refuses an ancestor several levels up the drill trail', () => {
    // Three deep: the cycle a user would create is not with the document in
    // front of them, which is the whole reason ancestry is a list.
    expect(mountCycleRefusal('concierge', ['concierge', 'chinook-assistant', 'sql-analyst'])).toBe(
      "Workflow 'concierge' includes itself through its subgraphs " +
        '(concierge -> chinook-assistant -> sql-analyst -> concierge); ' +
        'a subgraph cycle can never terminate',
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
