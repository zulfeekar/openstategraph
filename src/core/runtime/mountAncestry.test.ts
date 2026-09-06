import { afterEach, describe, expect, it } from 'vitest';
import { mountAncestry, provideMountAncestry } from './mountAncestry';

let restore: (() => void) | null = null;

afterEach(() => {
  restore?.();
  restore = null;
});

function install(reader: () => readonly string[]): void {
  const previous = provideMountAncestry(reader);
  restore = () => void provideMountAncestry(previous);
}

describe('mountAncestry', () => {
  it('refuses nothing until something installs a reader', () => {
    expect(mountAncestry()).toEqual([]);
  });

  it('answers from the installed reader', () => {
    install(() => ['concierge', 'chinook-assistant']);
    expect(mountAncestry()).toEqual(['concierge', 'chinook-assistant']);
  });

  it('asks every time rather than remembering, so a drill-in is seen at once', () => {
    let trail: readonly string[] = ['concierge'];
    install(() => trail);
    expect(mountAncestry()).toEqual(['concierge']);
    trail = ['concierge', 'chinook-assistant'];
    expect(mountAncestry()).toEqual(['concierge', 'chinook-assistant']);
  });

  it('costs the refusal rather than the card when the reader throws', () => {
    install(() => {
      throw new Error('sessionStorage is unavailable');
    });
    expect(mountAncestry()).toEqual([]);
  });

  it('hands back the previous reader so a caller can put it back', () => {
    const first = () => ['a'];
    const previous = provideMountAncestry(first);
    const second = provideMountAncestry(() => ['b']);
    expect(second).toBe(first);
    provideMountAncestry(previous);
    expect(mountAncestry()).toEqual([]);
  });
});
