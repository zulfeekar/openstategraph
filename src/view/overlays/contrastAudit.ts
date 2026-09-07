/**
 * Text contrast, measured against what is actually on screen.
 *
 * The check this replaces read two CSS variables — `--color-text-primary` on
 * `--color-bg-surface` — and reported the **page** as passing. It said *"Body
 * text contrast is 17.9:1 — Meets WCAG AA"* on a screen whose 11px palette
 * descriptions were 3.85:1 and whose section labels were 2.44:1
 * (reviews-2026-08-14 ticket 05).
 *
 * Two things were wrong and only one of them was the number. The check
 * sampled the text *least* likely to fail — large, primary, high-emphasis —
 * and then generalised from it. A green report is worse than no report,
 * because it is the thing someone points at to say the product is accessible.
 *
 * So: sample many places, hold each to the threshold its own size earns, and
 * report the worst. Pure, and separate from the overlay, because the maths is
 * the part worth testing and a React component is not where it can be.
 */

/** One piece of rendered text, as the DOM reports it. */
export interface TextSample {
  /** Human name for the report — "palette description", not a selector. */
  readonly label: string;
  readonly color: string;
  readonly background: string;
  readonly fontSizePx: number;
  readonly bold: boolean;
}

export interface ContrastFinding {
  readonly severity: 'pass' | 'warn' | 'fail';
  readonly title: string;
  readonly detail: string;
}

/**
 * WCAG AA's threshold for one piece of text.
 *
 * 4.5:1 normally; 3:1 for **large** text, which the guideline defines as 18pt
 * — 24px — or 14pt bold, which is 18.66px. Bold alone does not lower the bar:
 * that is the common misreading, and it would excuse exactly the small dense
 * labels this check exists to catch.
 */
export function requiredRatio({ fontSizePx, bold }: { fontSizePx: number; bold: boolean }): number {
  const large = fontSizePx >= 24 || (bold && fontSizePx >= 18.66);
  return large ? 3 : 4.5;
}

/** WCAG relative-luminance contrast, or `null` if a colour cannot be read. */
export function contrastRatio(a: string, b: string): number | null {
  const first = luminance(a);
  const second = luminance(b);
  if (first == null || second == null) return null;
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * The report for a set of samples: the worst shortfall, named.
 *
 * "Worst" is by **shortfall against its own threshold**, not by raw ratio — a
 * 3.2:1 body label is further from passing than a 3.1:1 heading that only
 * needs 3:1, and the body label is the one to fix.
 */
export function assessContrast(samples: readonly TextSample[]): ContrastFinding {
  if (samples.length === 0) {
    // Nothing measured is not the same as nothing wrong, and saying otherwise
    // is the whole defect this replaces.
    return {
      severity: 'warn',
      title: 'Text contrast was not measured',
      detail: 'No rendered text was found to sample, so nothing can be claimed about it.',
    };
  }

  const measured = samples.map((sample) => ({
    sample,
    ratio: contrastRatio(sample.color, sample.background),
    needs: requiredRatio(sample),
  }));

  const unreadable = measured.filter((entry) => entry.ratio == null);
  const failing = measured.filter((entry) => entry.ratio != null && entry.ratio < entry.needs);

  if (failing.length > 0) {
    const worst = failing.reduce((left, right) =>
      right.needs - (right.ratio ?? 0) > left.needs - (left.ratio ?? 0) ? right : left,
    );
    const others = failing.length > 1 ? ` ${failing.length} places fall short in total.` : '';
    return {
      severity: 'fail',
      title: `${worst.sample.label} contrast is only ${(worst.ratio ?? 0).toFixed(1)}:1`,
      detail:
        `WCAG AA needs ${worst.needs}:1 at ${Math.round(worst.sample.fontSizePx)}px.` + others,
    };
  }

  if (unreadable.length > 0) {
    return {
      severity: 'warn',
      title: 'Some text contrast could not be measured',
      detail: `${unreadable.length} colour(s) are not in a form this check can parse, so they are unproven.`,
    };
  }

  const tightest = measured.reduce((left, right) =>
    (right.ratio ?? 0) - right.needs < (left.ratio ?? 0) - left.needs ? right : left,
  );
  return {
    severity: 'pass',
    title: `Text contrast passes, tightest ${(tightest.ratio ?? 0).toFixed(1)}:1`,
    detail: `${measured.length} places sampled, including the smallest text on screen. Closest to the limit: ${tightest.sample.label}, which needs ${tightest.needs}:1.`,
  };
}

function luminance(color: string): number | null {
  const rgb = parseColor(color);
  if (!rgb) return null;
  const [r, g, b] = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function parseColor(color: string): [number, number, number] | null {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (hex?.[1]) {
    const digits =
      hex[1].length === 3
        ? hex[1]
            .split('')
            .map((char) => char + char)
            .join('')
        : hex[1];
    return [
      Number.parseInt(digits.slice(0, 2), 16),
      Number.parseInt(digits.slice(2, 4), 16),
      Number.parseInt(digits.slice(4, 6), 16),
    ];
  }

  const rgb = /rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)/i.exec(color);
  if (rgb?.[1] && rgb[2] && rgb[3]) {
    return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
  }
  return null;
}
