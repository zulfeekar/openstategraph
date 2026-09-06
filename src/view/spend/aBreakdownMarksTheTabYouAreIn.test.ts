import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import type { Spend } from '@core/runtime/RuntimeClient';

import { SpendBreakdown } from './SpendDialog';

/**
 * The breakdown's markup, asserted on the two claims it must carry through.
 *
 * `stable-beta-public/03`, slice 5. `spendDialogModel.test.ts` proves the
 * rows are decided correctly; this proves the tables a person actually reads
 * say the same thing — the gap between them is where a `?? 0` or a lost
 * `current` flag would sit and where nothing else would catch it.
 *
 * **`SpendBreakdown` rather than `SpendDialog`.** `Dialog` renders through
 * `createPortal(…, document.body)` and the suite runs in `node` on purpose
 * (`vite.config.ts`), so there is no `document` to portal into. The body is
 * therefore its own component: the dialog is the frame, this is the content,
 * and the content is the half with claims in it. `.test.ts` rather than
 * `.test.tsx` because that is the only pattern the suite collects, so the
 * element is built with `createElement` (slice 4's note).
 */
const NOTHING_REPORTED = '—';

const TWO_SITTINGS: Spend = {
  grandTotal: 1_284_910,
  cachedTotal: null,
  byModel: [
    {
      model: 'gpt-oss:120b-cloud',
      inputTokens: 804_100,
      outputTokens: 210_300,
      totalTokens: 1_014_400,
      cachedTokens: null,
      cacheCreationTokens: null,
      reasoningTokens: null,
      runs: 20,
    },
  ],
  sessionByModel: [
    {
      model: 'gpt-oss:120b-cloud',
      inputTokens: 30_000,
      outputTokens: 11_900,
      totalTokens: 41_900,
      cachedTokens: 0,
      cacheCreationTokens: null,
      reasoningTokens: null,
      runs: 5,
    },
  ],
  sessionTotal: 41_900,
  sessions: [
    {
      sessionId: 'tab-b',
      firstAt: '2026-09-04T09:12:03+02:00',
      lastAt: '2026-09-04T11:30:41+02:00',
      runs: 14,
      totalTokens: 201_880,
    },
    {
      sessionId: 'tab-a',
      firstAt: '2026-09-03T16:05:00+02:00',
      lastAt: '2026-09-03T18:40:00+02:00',
      runs: 6,
      totalTokens: 48_210,
    },
  ],
};

function markup(currentSessionId: string): string {
  return renderToStaticMarkup(
    createElement(SpendBreakdown, { spend: TWO_SITTINGS, currentSessionId }),
  );
}

describe('the breakdown as a reader sees it', () => {
  it('marks the row for the tab you are in, and only that one', () => {
    const html = markup('tab-a');

    // One marked row, addressed the way the rest of the app addresses
    // "the one you are on" — an ARIA state, not a colour.
    expect([...html.matchAll(/aria-current="true"/g)]).toHaveLength(1);
    // And it is the right row: the mark sits in the same `<tr>` as its span.
    const marked = /<tr[^>]*aria-current="true"[^>]*>(.*?)<\/tr>/s.exec(html);
    expect(marked?.[1]).toContain('2026-09-03 16:05 — 18:40');
    expect(marked?.[1]).toContain('this tab');
  });

  it('marks nothing when this tab has no recorded sitting yet', () => {
    expect(markup('tab-never-run')).not.toContain('aria-current');
  });

  it('prints a dash where nobody reported a figure and a zero where one did', () => {
    const html = markup('tab-a');

    // The all-time model reported no cache figure at all; this sitting's
    // model reported one and it was nothing. Both must survive the markup.
    expect(html).toContain(NOTHING_REPORTED);
    const cells = [...html.matchAll(/spend-table__number">([^<]*)</g)].map((match) => match[1]);
    expect(cells).toContain(NOTHING_REPORTED);
    expect(cells).toContain('0');
    // The figure nobody reported is never rendered as a zero on its way here.
    expect(html).not.toContain('>null<');
    expect(html).not.toContain('>NaN<');
  });

  it('shows every model and every sitting the answer carried', () => {
    const html = markup('tab-a');

    expect(html).toContain('gpt-oss:120b-cloud');
    expect(html).toContain('1,284,910');
    expect(html).toContain('2026-09-04 09:12 — 11:30');
    expect(html).toContain('2026-09-03 16:05 — 18:40');
  });
});
