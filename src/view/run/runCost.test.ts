/**
 * `memory-and-replay` 61 — what the run cost, said only as far as it was told.
 */
import { describe, expect, it } from 'vitest';
import { runCost } from './runCost';

const use = (total: number, model = 'gpt-oss:120b-cloud') => ({
  model,
  inputTokens: Math.floor(total / 2),
  outputTokens: total - Math.floor(total / 2),
  totalTokens: total,
});

describe('a finished run', () => {
  it('adds the rows the run reported', () => {
    const cost = runCost({ usage: [use(1200), use(340, 'claude-sonnet')], running: false });
    expect(cost.total).toBe('1,540');
    expect(cost.caption).toContain('2 models');
  });

  it('names the one model when there is only one', () => {
    expect(runCost({ usage: [use(90)], running: false }).caption).toContain('gpt-oss:120b-cloud');
  });

  /** `[]` is a real answer and a different one from `null` — 56. */
  it('says zero when no model was called, rather than a dash', () => {
    const cost = runCost({ usage: [], running: false });
    expect(cost.total).toBe('0');
    expect(cost.caption).toMatch(/no model/i);
  });

  /** `null` means this reader was not told, which is not the same as nothing. */
  it('dashes when the run reported no usage at all', () => {
    const cost = runCost({ usage: null, running: false });
    expect(cost.total).toBe('—');
    expect(cost.total).not.toBe('0');
    expect(cost.caption).toMatch(/did not report/i);
  });
});

describe('a live run', () => {
  /**
   * The whole of 61's second question. Tokens ride the **terminal** frames, so
   * a run in flight has not reported a partial total — it has reported none.
   * A strip that showed a growing number would be inventing the one number a
   * reader is most likely to quote.
   */
  it('does not show a running total, because there is no such number', () => {
    const cost = runCost({ usage: null, running: true });
    expect(cost.total).toBe('—');
    expect(cost.caption).toMatch(/when it finishes/i);
  });

  it('still refuses a total when a stale one is in hand', () => {
    expect(runCost({ usage: [use(999)], running: true }).total).toBe('—');
  });
});
