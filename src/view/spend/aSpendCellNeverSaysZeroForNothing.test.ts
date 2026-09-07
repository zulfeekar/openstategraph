import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { Spend } from '@core/runtime/RuntimeClient';

import { SpendBar } from './SpendBar';

/**
 * The rendered bar, asserted on the one claim it must never make.
 *
 * `stable-beta-public/03`, slice 4. `spendModel.test.ts` proves `cellsFor`
 * turns `null` into `—`; this proves the markup a person actually reads
 * carries that answer through — the gap between them is where a `?? 0`, a
 * `Number(value)` or a `{value || 0}` would sit and where nothing else would
 * catch it.
 *
 * **Rendered on the server, deliberately.** `vite.config.ts` sets
 * `test.environment: 'node'` on purpose (the view layer is proven in the
 * browser, not simulated) and no DOM library is installed. `react-dom/server`
 * needs neither: it turns an element into a string, which is enough to ask
 * what the cell says. The file is `.test.ts` rather than `.test.tsx` because
 * that is the only pattern the suite collects, so the element is built with
 * `createElement` instead of JSX.
 */
const NOTHING_REPORTED = '—';

function markup(spend: Spend | null): string {
  return renderToStaticMarkup(
    createElement(SpendBar, {
      spend,
      error: null,
      onOpen: () => {},
    }),
  );
}

/** The figures a cell prints, in the order the bar prints them. */
function values(html: string): readonly string[] {
  return [...html.matchAll(/spend-bar__value">([^<]*)</g)].map((match) => match[1] ?? '');
}

const NOBODY_REPORTED_A_CACHE: Spend = {
  grandTotal: 1284910,
  cachedTotal: null,
  byModel: [
    {
      model: 'gpt-oss:120b-cloud',
      inputTokens: 1_000_000,
      outputTokens: 284_910,
      totalTokens: 1_284_910,
      cachedTokens: null,
      cacheCreationTokens: null,
      reasoningTokens: null,
      runs: 25,
    },
  ],
  sessionByModel: [],
  sessionTotal: 0,
  sessions: [],
};

describe('the bar as a reader sees it', () => {
  it('prints a dash for a cache figure nobody reported, and never a zero', () => {
    const printed = values(markup(NOBODY_REPORTED_A_CACHE));

    // Total, Cached, This tab, Models — the Cached cell is the subject.
    expect(printed[1]).toBe(NOTHING_REPORTED);
    expect(printed[1]).not.toBe('0');
    // And the claim is about the *rendered* cell, not about a helper: the
    // string '0' must not be what stands where the cache figure goes,
    // whatever route it took to get there.
    expect(markup(NOBODY_REPORTED_A_CACHE)).toContain(
      `<span class="spend-bar__value">${NOTHING_REPORTED}</span>`,
    );
  });

  it('prints a zero when a provider reported one', () => {
    // The other half of the tri-state, and the half a blanket `—` would
    // break: this model *was* asked, and none of it came from cache.
    const printed = values(markup({ ...NOBODY_REPORTED_A_CACHE, cachedTotal: 0 }));

    expect(printed[1]).toBe('0');
  });

  it('says nothing in every cell before the first answer arrives', () => {
    expect(values(markup(null))).toEqual([
      NOTHING_REPORTED,
      NOTHING_REPORTED,
      NOTHING_REPORTED,
      NOTHING_REPORTED,
    ]);
  });
});
