import { describe, expect, it } from 'vitest';
import { patrolJobNotice } from './patrolJobNotice';
import type { PatrolStatus } from '@core/runtime/RuntimeClient';

/**
 * The background-job indicator's decision — `kanban-patrol/10`.
 *
 * Four cases, and the fourth is the one the ticket says gets forgotten: a
 * patrol that *failed* must clear the chip too. A chip that only clears on
 * success spins forever the first time a patrol dies, which is worse than no
 * chip — it claims a job is running that is not.
 */

const status = (over: Partial<PatrolStatus>): PatrolStatus => ({
  status: 'idle',
  startedAt: '',
  finishedAt: '',
  error: '',
  filed: 0,
  skipped: 0,
  totalFindings: 0,
  ...over,
});

describe('patrolJobNotice', () => {
  it('shows nothing before anything has been asked', () => {
    expect(patrolJobNotice(null)).toBeNull();
  });

  it('shows nothing when no patrol is running', () => {
    expect(patrolJobNotice(status({ status: 'idle' }))).toBeNull();
  });

  it('names the job while it runs', () => {
    const chip = patrolJobNotice(status({ status: 'running' }));
    expect(chip?.label).toBe('Patrol running');
    // The chip is a word, and a word on a badge owes the reader a sentence
    // (`badgeExplanations.test.ts`). It has to say *what* is running, not
    // merely that something is.
    expect(chip?.hint).toContain('patrol');
  });

  it('clears when the patrol finishes', () => {
    expect(patrolJobNotice(status({ status: 'finished', filed: 2 }))).toBeNull();
  });

  it('clears when the patrol fails — the path that leaves a chip spinning', () => {
    expect(patrolJobNotice(status({ status: 'failed', error: 'boom' }))).toBeNull();
  });
});
