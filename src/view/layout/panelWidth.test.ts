import { describe, expect, it } from 'vitest';
import {
  PANEL_COLUMN_KEYBOARD_STEP,
  clampPanelColumnWidth,
  panelColumnMaxWidth,
  panelColumnMinWidth,
  panelColumnWidthFromArrow,
  panelColumnWidthFromDrag,
  readPanelColumnWidth,
  rememberPanelColumnWidth,
} from './panelWidth';
import { LAYOUT } from '@design/tokens';

/** In-memory Storage, the injectable pattern `dockHeightMemory.test.ts` uses. */
const memoryStorage = (): Storage => {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k) => map.get(k) ?? null,
    key: (i) => [...map.keys()][i] ?? null,
    removeItem: (k) => void map.delete(k),
    setItem: (k, v) => void map.set(k, String(v)),
  };
};

/** A browser that has decided you may not store anything. */
const hostileStorage = (): Storage =>
  new Proxy(memoryStorage(), {
    get() {
      throw new DOMException('The operation is insecure.', 'SecurityError');
    },
  });

const WIDE = 1600;

describe('how wide the right-hand column may be', () => {
  it('floors at what the open panels are worth today', () => {
    expect(panelColumnMinWidth({ ask: true })).toBe(LAYOUT.inspectorWidth);
    expect(panelColumnMinWidth({ ask: true, inspector: true })).toBe(LAYOUT.inspectorWidth * 2);
  });

  it('ceilings at half the viewport, so the canvas keeps the other half', () => {
    expect(panelColumnMaxWidth(WIDE, LAYOUT.inspectorWidth)).toBe(800);
  });

  it('lets the floor win on a window too narrow to hold both halves', () => {
    // Both panels open on a 1000px window: half the viewport is 500 and the
    // panels are worth 600. A column narrower than the panels it holds is a
    // squeeze nobody asked for, so the floor wins — the same order
    // `dockMaxHeight` keeps against `DOCK_MIN_HEIGHT`.
    const floor = panelColumnMinWidth({ ask: true, inspector: true });
    expect(panelColumnMaxWidth(1000, floor)).toBe(floor);
  });

  it('brings a drag inside both bounds', () => {
    const floor = LAYOUT.inspectorWidth;
    expect(clampPanelColumnWidth(9000, WIDE, floor)).toBe(800);
    expect(clampPanelColumnWidth(10, WIDE, floor)).toBe(floor);
    expect(clampPanelColumnWidth(520, WIDE, floor)).toBe(520);
  });

  it('refuses a width that is not a number', () => {
    // CLAUDE.md: never let a non-finite number reach a stored field.
    expect(clampPanelColumnWidth(Number.NaN, WIDE, 300)).toBe(300);
    expect(clampPanelColumnWidth(Number.POSITIVE_INFINITY, WIDE, 300)).toBe(300);
  });
});

describe('the gesture that moves the column edge', () => {
  it('grows the column as the pointer travels left', () => {
    // The handle is on the column's *left* edge, so the free edge moves
    // against `clientX` — the mirror of the dock's bottom edge.
    expect(panelColumnWidthFromDrag(300, 900, 800)).toBe(400);
    expect(panelColumnWidthFromDrag(300, 900, 950)).toBe(250);
    expect(panelColumnWidthFromDrag(300, 900, 900)).toBe(300);
  });

  it('moves by one step per arrow press, in the direction the arrow points', () => {
    expect(panelColumnWidthFromArrow(300, 'ArrowLeft')).toBe(300 + PANEL_COLUMN_KEYBOARD_STEP);
    expect(panelColumnWidthFromArrow(300, 'ArrowRight')).toBe(300 - PANEL_COLUMN_KEYBOARD_STEP);
  });

  it('has no opinion about any other key, so Tab still leaves the handle', () => {
    expect(panelColumnWidthFromArrow(300, 'ArrowUp')).toBeNull();
    expect(panelColumnWidthFromArrow(300, 'Tab')).toBeNull();
    expect(panelColumnWidthFromArrow(300, 'Enter')).toBeNull();
  });
});

describe('the remembered column width', () => {
  it('has none until somebody sets one', () => {
    expect(readPanelColumnWidth(memoryStorage())).toBeNull();
  });

  it('comes back the way it was left', () => {
    const storage = memoryStorage();
    rememberPanelColumnWidth(612, storage);
    expect(readPanelColumnWidth(storage)).toBe(612);
  });

  it('falls back to no preference on a value that is not a width', () => {
    const storage = memoryStorage();
    storage.setItem('openstategraph.right-panels-width', 'wide');
    expect(readPanelColumnWidth(storage)).toBeNull();
    storage.setItem('openstategraph.right-panels-width', '');
    expect(readPanelColumnWidth(storage)).toBeNull();
    storage.setItem('openstategraph.right-panels-width', 'Infinity');
    expect(readPanelColumnWidth(storage)).toBeNull();
  });

  it('survives a browser that refuses to store or to be read', () => {
    expect(readPanelColumnWidth(hostileStorage())).toBeNull();
    expect(() => rememberPanelColumnWidth(612, hostileStorage())).not.toThrow();
    expect(readPanelColumnWidth(null)).toBeNull();
    expect(() => rememberPanelColumnWidth(612, null)).not.toThrow();
  });
});
