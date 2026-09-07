import { describe, expect, it } from 'vitest';
import {
  EXAMPLES_HINT_KEY,
  ONBOARDED_KEY,
  alreadyAnswered,
  markAnswered,
  type FlagStorage,
} from './onceOnlyFlag';

const fake = (
  seed: Record<string, string> = {},
): FlagStorage & { seen: Record<string, string> } => {
  const seen = { ...seed };
  return {
    seen,
    getItem: (key) => seen[key] ?? null,
    setItem: (key, value) => {
      seen[key] = value;
    },
  };
};

const throwing = (): FlagStorage => ({
  getItem() {
    throw new Error('SecurityError');
  },
  setItem() {
    throw new Error('SecurityError');
  },
});

describe('a once-only hint', () => {
  it('shows on a fresh browser and never again after an answer', () => {
    const storage = fake();
    expect(alreadyAnswered(EXAMPLES_HINT_KEY, storage)).toBe(false);
    markAnswered(EXAMPLES_HINT_KEY, storage);
    expect(alreadyAnswered(EXAMPLES_HINT_KEY, storage)).toBe(true);
  });

  it('keeps its two questions apart', () => {
    const storage = fake();
    markAnswered(ONBOARDED_KEY, storage);
    // Answering the credentials hint says nothing about the examples hint.
    expect(alreadyAnswered(EXAMPLES_HINT_KEY, storage)).toBe(false);
  });

  it('stays quiet when there is nowhere to remember the answer', () => {
    // A hint that cannot be dismissed for good and returns on every load is
    // worse than no hint. Both no-storage shapes take the same branch.
    expect(alreadyAnswered(EXAMPLES_HINT_KEY, null)).toBe(true);
    expect(alreadyAnswered(EXAMPLES_HINT_KEY, throwing())).toBe(true);
  });

  it('does not throw when the answer cannot be written', () => {
    expect(() => markAnswered(EXAMPLES_HINT_KEY, throwing())).not.toThrow();
    expect(() => markAnswered(EXAMPLES_HINT_KEY, null)).not.toThrow();
  });

  it('keeps the credentials key it shipped with, so an install stays answered', () => {
    expect(ONBOARDED_KEY).toBe('openstategraph.onboarded');
  });
});
