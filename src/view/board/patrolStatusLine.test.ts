import { describe, expect, it } from 'vitest';
import { patrolStatusLine } from './patrolStatusLine';
import type { PatrolStatus } from '@core/runtime/RuntimeClient';

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

describe('patrolStatusLine', () => {
  it('is silent when nothing has been asked yet', () => {
    expect(patrolStatusLine(null)).toBeNull();
  });

  it('is silent when idle — idle is not news', () => {
    expect(patrolStatusLine(status({ status: 'idle' }))).toBeNull();
  });

  it('says running, plainly', () => {
    expect(patrolStatusLine(status({ status: 'running' }))).toBe('Patrol running…');
  });

  it('says what it filed when it finished with new cards', () => {
    expect(patrolStatusLine(status({ status: 'finished', filed: 3 }))).toBe(
      'Patrol finished — filed 3 new card(s).',
    );
  });

  it('says nothing new when it finished with nothing to file', () => {
    expect(patrolStatusLine(status({ status: 'finished', filed: 0 }))).toBe(
      'Patrol finished — nothing new to file.',
    );
  });

  it("reports a failure with its plain reason — 07's own words", () => {
    expect(patrolStatusLine(status({ status: 'failed', error: 'sqlite disk I/O error' }))).toBe(
      'Patrol failed: sqlite disk I/O error',
    );
  });

  it('a failure with no reason still says something rather than nothing', () => {
    expect(patrolStatusLine(status({ status: 'failed', error: '' }))).toBe(
      'Patrol failed: unknown reason',
    );
  });
});
