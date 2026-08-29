import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { IS_APPLE } from '@design/primitives';
import type { PaperFeatureContext } from './IPaperFeature';
import { KeyboardFeature, createDefaultShortcuts, type Shortcut } from './KeyboardFeature';

/**
 * `launch-readiness` 187 — "user cannot copy any text content from the UI, it
 * gives the JSON".
 *
 * `KeyboardFeature` installs on `window` and stood down only when focus was in
 * a text *field*. Selected text in a `<div>` is not a field, so selecting an
 * answer, a SQL statement or an error message and pressing ⌘C reached the
 * `Mod+C` binding, which called `preventDefault()` and put the *node* clipboard
 * — JSON — on the pasteboard instead of the selection.
 *
 * The assertion that matters is `preventDefault`, not the clipboard call: the
 * defect is the canvas claiming a key the browser was about to handle. A unit
 * test of `matches()` passes in both worlds and would have proved nothing.
 *
 * The browser half of this — a real selection over a real `<div>`, a real
 * ⌘C — is `e2e/copyTextOutOfTheEditor.spec.ts`. This half runs in the gate.
 */

interface Fired {
  readonly prevented: boolean;
  readonly ran: readonly string[];
}

/** What the handler sees: `window`, and the selection it asks `window` for. */
class FakeWindow implements EventTarget {
  handler: ((event: unknown) => void) | null = null;
  selected = '';

  addEventListener(_type: string, handler: EventListenerOrEventListenerObject | null): void {
    this.handler = handler as (event: unknown) => void;
  }
  removeEventListener(): void {
    this.handler = null;
  }
  dispatchEvent(): boolean {
    return true;
  }

  getSelection(): { isCollapsed: boolean; toString: () => string } {
    return { isCollapsed: this.selected === '', toString: () => this.selected };
  }
}

const saved = new Map<string, unknown>();

beforeEach(() => {
  for (const name of ['window', 'document', 'HTMLElement']) {
    saved.set(name, (globalThis as Record<string, unknown>)[name]);
  }
});

afterEach(() => {
  for (const [name, before] of saved) {
    if (before === undefined) delete (globalThis as Record<string, unknown>)[name];
    else (globalThis as Record<string, unknown>)[name] = before;
  }
});

/** Installs the real default table against a recording controller. */
function harness(shortcuts: readonly Shortcut[] = createDefaultShortcuts()): {
  window: FakeWindow;
  press: (key: string, target?: unknown) => Fired;
} {
  const fake = new FakeWindow();
  (globalThis as Record<string, unknown>).window = fake;
  (globalThis as Record<string, unknown>).document = { activeElement: null };
  // `isTextEntry` narrows with `instanceof HTMLElement`, which the node
  // environment does not have. Nothing here is one, so an unpopulated class is
  // exactly the answer the predicate needs.
  (globalThis as Record<string, unknown>).HTMLElement = class {};

  const ran: string[] = [];
  const record = (name: string) => (): void => {
    ran.push(name);
  };
  const ctx = {
    controller: {
      clipboard: {
        copy: record('copy'),
        cut: record('cut'),
        paste: record('paste'),
        duplicate: record('duplicate'),
      },
      selectionActions: {
        selectAll: record('selectAll'),
        nudge: record('nudge'),
        deleteSelection: record('delete'),
        bounds: () => ({ x: 0, y: 0, width: 0, height: 0 }),
      },
      selection: { nodes: [], clear: record('clear') },
      history: { undo: record('undo'), redo: record('redo') },
      model: { bounds: () => ({ x: 0, y: 0, width: 0, height: 0 }) },
    },
    viewport: {
      visibleRect: { x: 0, y: 0, width: 100, height: 100 },
      zoomIn: record('zoomIn'),
      zoomOut: record('zoomOut'),
      resetZoom: record('resetZoom'),
      fit: record('fit'),
    },
  } as unknown as PaperFeatureContext;

  new KeyboardFeature(shortcuts).install(ctx);

  return {
    window: fake,
    press(key: string, target: unknown = null): Fired {
      ran.length = 0;
      let prevented = false;
      fake.handler?.({
        key: key.toLowerCase(),
        code: `Key${key.toUpperCase()}`,
        metaKey: IS_APPLE,
        ctrlKey: !IS_APPLE,
        shiftKey: false,
        altKey: false,
        target,
        preventDefault: () => {
          prevented = true;
        },
      });
      return { prevented, ran: [...ran] };
    },
  };
}

describe('a live text selection outranks the canvas', () => {
  it.each([
    ['C', 'copy'],
    ['X', 'cut'],
    ['A', 'selectAll'],
  ])('Mod+%s leaves the browser alone while text is selected', (key, action) => {
    const h = harness();
    h.window.selected = 'Run failed: connection refused';

    const fired = h.press(key);

    expect(fired.prevented).toBe(false);
    expect(fired.ran).not.toContain(action);
  });

  it.each([
    ['C', 'copy'],
    ['X', 'cut'],
    ['A', 'selectAll'],
  ])('Mod+%s still acts on nodes when nothing is selected', (key, action) => {
    const h = harness();
    h.window.selected = '';

    const fired = h.press(key);

    expect(fired.prevented).toBe(true);
    expect(fired.ran).toContain(action);
  });

  it('ignores a selection that yields no text', () => {
    // A range can span `user-select: none` content — which is every node on
    // the canvas, because JointJS sets it inline on the cells layer — and be
    // non-collapsed while carrying nothing a user could have copied. Reading
    // the text rather than the collapsed flag is what keeps ⌘C on the canvas
    // working, and it is a cheaper containment check than walking the tree.
    const h = harness();
    h.window.selected = '   ';

    expect(h.press('C').ran).toContain('copy');
  });

  it('leaves the bindings that mean the same thing either way alone', () => {
    const h = harness();
    h.window.selected = 'some prose in a panel';

    expect(h.press('Z').ran).toContain('undo');
    expect(h.press('D').ran).toContain('duplicate');
  });
});

/**
 * The instrument the table was missing.
 *
 * The binding table's docstring guarantees that a *documented* shortcut cannot
 * drift from the one that fires. It says nothing about whether the binding
 * should have fired at all, and that is the question 187 was: two different
 * properties, only one of which had a test. This is the other one.
 */
describe('a binding cannot claim a browser text shortcut without saying so', () => {
  /** What the browser itself does with these while text is selected. */
  const NATIVE_TEXT_KEYS = ['Mod+C', 'Mod+X', 'Mod+A'];

  it.each(NATIVE_TEXT_KEYS)('%s yields to a text selection', (keys) => {
    for (const shortcut of createDefaultShortcuts().filter((s) => s.keys === keys)) {
      expect(shortcut.yieldsToTextSelection, `${keys} (${shortcut.label})`).toBe(true);
    }
  });

  it('every binding that reaches the pasteboard declares it', () => {
    const offenders = createDefaultShortcuts()
      .filter((s) => /clipboard\s*\.\s*(copy|cut)\b/.test(s.run.toString()))
      .filter((s) => s.yieldsToTextSelection !== true)
      .map((s) => `${s.keys} (${s.label})`);

    expect(offenders).toEqual([]);
  });

  it('is looking at bindings that exist', () => {
    // Guards the two tests above: both pass vacuously against an empty table.
    const table = createDefaultShortcuts();
    expect(table.filter((s) => NATIVE_TEXT_KEYS.includes(s.keys)).length).toBe(3);
    expect(table.filter((s) => /clipboard\s*\.\s*(copy|cut)\b/.test(s.run.toString())).length).toBe(
      2,
    );
  });
});
