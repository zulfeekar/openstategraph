import { describe, expect, it } from 'vitest';
import { assessContrast, contrastRatio, requiredRatio, type TextSample } from './contrastAudit';

/**
 * The contrast check, and the false pass it used to give.
 *
 * **Check accessibility** reported *"Body text contrast is 17.9:1 — Meets WCAG
 * AA"* and six green ticks. Measured against the same background at the same
 * moment (reviews-2026-08-14 ticket 05):
 *
 *     body text                    17.9:1   passes
 *     11px palette descriptions     3.85:1  FAILS
 *     "in every workflow" label     2.44:1  FAILS
 *
 * It read two CSS variables — `--color-text-primary` on `--color-bg-surface` —
 * and reported the *page* as passing. The text most likely to fail, and most
 * of what is actually on screen, was never sampled.
 *
 * A green report is worse than no report: it is the thing someone points at to
 * say the product is accessible.
 */
const sample = (over: Partial<TextSample> = {}): TextSample => ({
  label: 'body',
  color: '#14171d',
  background: '#ffffff',
  fontSizePx: 14,
  bold: false,
  ...over,
});

describe('the ratio WCAG AA actually requires', () => {
  it('asks 4.5:1 of normal text', () => {
    expect(requiredRatio({ fontSizePx: 14, bold: false })).toBe(4.5);
    expect(requiredRatio({ fontSizePx: 11, bold: false })).toBe(4.5);
  });

  it('asks only 3:1 of large text — 24px, or 18.66px when bold', () => {
    // 18pt and 14pt-bold, in the px the browser reports.
    expect(requiredRatio({ fontSizePx: 24, bold: false })).toBe(3);
    expect(requiredRatio({ fontSizePx: 19, bold: true })).toBe(3);
  });

  it('does not let bold alone excuse small text', () => {
    // A common misreading of the rule: bold matters only from 18.66px up.
    expect(requiredRatio({ fontSizePx: 12, bold: true })).toBe(4.5);
  });
});

describe('measuring a pair of colours', () => {
  it('agrees with the known extremes', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 1);
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
  });

  it('reads rgb() as well as hex, because that is what the DOM returns', () => {
    expect(contrastRatio('rgb(0, 0, 0)', 'rgb(255,255,255)')).toBeCloseTo(21, 1);
  });

  it('says so rather than guessing when a colour cannot be parsed', () => {
    expect(contrastRatio('color-mix(in srgb, red, blue)', '#fff')).toBeNull();
  });
});

describe('what the report says', () => {
  it('passes only when every sample passes', () => {
    const finding = assessContrast([sample(), sample({ label: 'heading', fontSizePx: 20 })]);

    expect(finding.severity).toBe('pass');
  });

  it('fails on the smallest text even when body text is excellent', () => {
    // The exact reported situation: 17.9:1 body, 2.44:1 on an 11px label.
    const finding = assessContrast([
      sample({ label: 'body text', color: '#14171d', background: '#ffffff' }),
      sample({
        label: 'palette description',
        color: '#a9adb6',
        background: '#ffffff',
        fontSizePx: 11,
      }),
    ]);

    expect(finding.severity).toBe('fail');
    // Names the offender, so the report is actionable rather than a verdict.
    expect(finding.title + finding.detail).toContain('palette description');
  });

  it('reports the worst offender, not merely the first', () => {
    const finding = assessContrast([
      sample({ label: 'nearly ok', color: '#767b85', background: '#ffffff', fontSizePx: 12 }),
      sample({ label: 'much worse', color: '#c9ccd2', background: '#ffffff', fontSizePx: 11 }),
    ]);

    expect(finding.title + finding.detail).toContain('much worse');
  });

  it('counts how many distinct places fall short', () => {
    const finding = assessContrast([
      sample({ label: 'a', color: '#c9ccd2', fontSizePx: 11 }),
      sample({ label: 'b', color: '#c9ccd2', fontSizePx: 11 }),
      sample({ label: 'ok', color: '#14171d' }),
    ]);

    expect(finding.detail).toMatch(/2/);
  });

  it('never claims a pass it did not measure', () => {
    // Nothing sampled means nothing proven. The old check's whole defect was
    // reporting a page-wide verdict from one measurement.
    const finding = assessContrast([]);

    expect(finding.severity).not.toBe('pass');
  });

  it('warns rather than fails when a colour could not be read', () => {
    const finding = assessContrast([
      sample({ label: 'exotic', color: 'color-mix(in srgb, a, b)' }),
    ]);

    expect(finding.severity).toBe('warn');
  });

  it('holds large text to 3:1, so a big pale heading is not a false failure', () => {
    const finding = assessContrast([
      sample({ label: 'hero', color: '#767b85', background: '#ffffff', fontSizePx: 32 }),
    ]);

    expect(finding.severity).toBe('pass');
  });
});
