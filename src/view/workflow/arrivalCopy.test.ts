import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import {
  ARRIVAL_DISMISS,
  ARRIVAL_EMPTY_HINT,
  ARRIVAL_EMPTY_TITLE,
  ARRIVAL_NEW,
  ARRIVAL_SUBTITLE,
  START_PANEL_OPEN,
  START_PANEL_RECENT,
  START_PANEL_START,
  arrivalRecencyLine,
} from './arrivalCopy';
import { arrivalChoices } from '@core/runtime/arrivalChoices';

/**
 * `install-experience` 28 — what the arrival offer says, held apart from the
 * component that shows it.
 *
 * Same division `emptyStateCopy.ts` draws and for the same reason: a string
 * inside JSX has no way to fail, and the sentences here make promises the rest
 * of the product has to keep.
 */

const read = (relative: string) =>
  readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf8');

const dialog = read('../overlays/ArrivalDialog.tsx');
const startPanel = read('../canvas/StartPanel.tsx');

describe('the words', () => {
  it('names the two clocks it sorts by, so the order is arguable', () => {
    expect(ARRIVAL_SUBTITLE).toMatch(/opened/i);
    expect(ARRIVAL_SUBTITLE).toMatch(/edited/i);
  });

  it('offers to make one when the project has none', () => {
    expect(ARRIVAL_EMPTY_TITLE).toMatch(/no workflows/i);
    expect(ARRIVAL_NEW).toMatch(/new workflow/i);
  });

  it('does not promise the first save keeps the name it was given', () => {
    // A slug is minted by the backend and frozen. Copy that implies a folder
    // follows a rename is the defect `say-it-on-the-surface` 03 removed from
    // five other surfaces; this is the sixth and it starts clean.
    expect(`${ARRIVAL_EMPTY_HINT} ${ARRIVAL_SUBTITLE}`).not.toMatch(/rename/i);
  });

  it('says nothing is opened by dismissing', () => {
    expect(ARRIVAL_DISMISS).not.toMatch(/cancel/i);
  });

  it('gives the start panel the two headings every editor already uses', () => {
    expect(START_PANEL_START).toBe('Start');
    expect(START_PANEL_RECENT).toBe('Recent');
    expect(START_PANEL_OPEN).toMatch(/open/i);
  });
});

describe('arrivalRecencyLine', () => {
  const now = Date.parse('2026-08-31T12:00:00Z');

  it('says opened when this browser opened it more recently than the file moved', () => {
    const [choice] = arrivalChoices(
      [
        {
          slug: 'lens-qa',
          name: 'Lens QA',
          savedAt: '2026-08-01T00:00:00Z',
          nodeCount: 3,
          edgeCount: 2,
          published: true,
          hidden: false,
          findings: [],
          digest: '',
        },
      ],
      { 'lens-qa': '2026-08-31T10:00:00Z' },
    );

    expect(arrivalRecencyLine(choice!, now)).toBe('Opened 2 h ago');
  });

  it('says edited when the file is the newer of the two', () => {
    const [choice] = arrivalChoices(
      [
        {
          slug: 'concierge',
          name: 'Concierge',
          savedAt: '2026-08-31T11:00:00Z',
          nodeCount: 3,
          edgeCount: 2,
          published: true,
          hidden: false,
          findings: [],
          digest: '',
        },
      ],
      {},
    );

    expect(arrivalRecencyLine(choice!, now)).toBe('Edited 1 h ago');
  });

  it('admits when neither clock knows anything', () => {
    const [choice] = arrivalChoices(
      [
        {
          slug: 'archive',
          name: 'Archive',
          savedAt: '',
          nodeCount: 0,
          edgeCount: 0,
          published: true,
          hidden: false,
          findings: [],
          digest: '',
        },
      ],
      {},
    );

    expect(arrivalRecencyLine(choice!, now)).toBe('Not opened in this browser');
  });
});

describe('the surfaces', () => {
  it('reuses the credentials dialog’s container rather than answering height, scroll and dismissal a second time', () => {
    // The ticket's own instruction. `Dialog` already owns Escape, the focus
    // trap, the backdrop that only closes on a press *and* release of its own,
    // and the bounded scrolling body — four decisions with a reason each, and
    // a second copy of them is the duplication this repository keeps paying
    // for.
    expect(dialog).toMatch(/from '\.\/Dialog'/);
    expect(dialog).toContain('<Dialog');
    for (const reinvented of ['dialog-backdrop', 'createPortal', "'Escape'", 'aria-modal']) {
      expect(dialog).not.toContain(reinvented);
    }
  });

  it('opens nothing by itself', () => {
    // 23's rule, intact: a workflow reaches this canvas because somebody
    // clicked its row. The dialog therefore has no effect at all — nothing in
    // it can fire on mount, which is the shape an "already selected" default
    // would have needed and the reason the ticket preferred a list to an
    // automatic open.
    expect(dialog).not.toContain('useEffect');
  });

  it('keeps its sentences in the copy module', () => {
    expect(dialog).toContain('arrivalCopy');
    expect(startPanel).toContain('arrivalCopy');
  });

  it('draws its rules and insets from the tokens the design system already has', () => {
    const css = read('../canvas/StartPanel.css');
    expect(css).not.toMatch(/--color-rule/);
    expect(css).not.toMatch(/^\s*--[a-z-]+:/m);
  });
});
