import { CANVAS } from '@design/tokens';
import { IS_APPLE } from '@design/primitives';
import { PaperFeature, type PaperFeatureContext } from './IPaperFeature';
import { hasTextSelection, isTextEntry } from './textClaim';

/** One binding, in the same declarative form the shortcuts drawer renders. */
export interface Shortcut {
  /** "Mod+Z" — `Mod` resolves to ⌘ on Apple platforms, Ctrl elsewhere. */
  readonly keys: string;
  readonly label: string;
  readonly group: string;
  readonly run: (ctx: PaperFeatureContext) => void;
  /** Allow while a text field has focus. Off by default. */
  readonly allowInTextEntry?: boolean;
  /**
   * Stand down while text is selected anywhere in the document.
   *
   * For the three bindings that collide with the browser's own text
   * shortcuts — copy, cut, select-all — which mean something different to a
   * reader with a sentence highlighted than to an author with a node picked.
   * It is a property of the binding rather than a condition in the handler
   * because it is true of three rows and false of the other twenty: undo,
   * the nudges and the zooms mean the same thing either way, and a blanket
   * rule would take them all down with it.
   */
  readonly yieldsToTextSelection?: boolean;
}

/**
 * Keyboard handling.
 *
 * The binding table is data, and the same array feeds both the handler and
 * the shortcuts drawer — so a documented shortcut cannot drift from the one
 * that actually fires, which is the usual failure of hand-written help.
 *
 * Bindings are ignored while a text field has focus unless they opt in.
 * Without that, typing "a" in a prompt would select every node.
 *
 * A handler on `window` that calls `preventDefault` is a decision to own a
 * key for the whole document, so two questions have to be asked before it
 * fires and not one: *is the user typing* (focus) and *is the user reading*
 * (a selection). The second arrived with `launch-readiness` 187 — see
 * `textClaim.ts`, and the instrument in
 * `textSelectionOutranksTheCanvas.test.ts` that fails when a new binding
 * claims the pasteboard without declaring it.
 */
export class KeyboardFeature extends PaperFeature {
  readonly id = 'keyboard';

  constructor(private readonly shortcuts: readonly Shortcut[]) {
    super();
  }

  protected onInstall(ctx: PaperFeatureContext): void {
    this.onDom(window, 'keydown', ((event: KeyboardEvent) => {
      const inText = isTextEntry(event.target);
      // Asked at most once per event, and only for a binding that cares:
      // stringifying the selection on every keystroke would charge the whole
      // table for three rows.
      let selectedText: boolean | undefined;
      for (const shortcut of this.shortcuts) {
        if (!matches(shortcut.keys, event)) continue;
        if (inText && !shortcut.allowInTextEntry) continue;
        if (shortcut.yieldsToTextSelection && (selectedText ??= hasTextSelection())) continue;
        event.preventDefault();
        shortcut.run(ctx);
        return;
      }
    }) as never);
  }

  get bindings(): readonly Shortcut[] {
    return this.shortcuts;
  }
}

/**
 * The default binding set.
 *
 * A factory rather than a constant so the surrounding shell can inject the
 * actions it owns — theme, panels, export — alongside the canvas ones,
 * keeping every shortcut in one table.
 */
export function createDefaultShortcuts(extra: readonly Shortcut[] = []): readonly Shortcut[] {
  const nudge = (dx: number, dy: number, big: boolean) => (ctx: PaperFeatureContext) => {
    const step = big ? CANVAS.gridSize * 5 : CANVAS.gridSize;
    ctx.controller.selectionActions.nudge(dx * step, dy * step);
  };

  return [
    {
      keys: 'Mod+Z',
      label: 'Undo',
      group: 'Edit',
      allowInTextEntry: true,
      run: (ctx) => ctx.controller.history.undo(),
    },
    {
      keys: 'Mod+Shift+Z',
      label: 'Redo',
      group: 'Edit',
      allowInTextEntry: true,
      run: (ctx) => ctx.controller.history.redo(),
    },
    {
      keys: 'Mod+A',
      label: 'Select all',
      group: 'Edit',
      yieldsToTextSelection: true,
      run: (ctx) => ctx.controller.selectionActions.selectAll(),
    },
    {
      keys: 'Mod+C',
      label: 'Copy',
      group: 'Edit',
      yieldsToTextSelection: true,
      run: (ctx) => ctx.controller.clipboard.copy(),
    },
    {
      keys: 'Mod+X',
      label: 'Cut',
      group: 'Edit',
      yieldsToTextSelection: true,
      run: (ctx) => ctx.controller.clipboard.cut(),
    },
    {
      keys: 'Mod+V',
      label: 'Paste',
      group: 'Edit',
      // Pasted nodes land in the middle of what the user is looking at,
      // not at the coordinates they were copied from.
      run: (ctx) => {
        const visible = ctx.viewport.visibleRect;
        ctx.controller.clipboard.paste({
          x: visible.x + visible.width / 2,
          y: visible.y + visible.height / 2,
        });
      },
    },
    {
      keys: 'Mod+D',
      label: 'Duplicate',
      group: 'Edit',
      run: (ctx) => ctx.controller.clipboard.duplicate(ctx.controller.selection.nodes),
    },
    {
      keys: 'Backspace',
      label: 'Delete selection',
      group: 'Edit',
      run: (ctx) => ctx.controller.selectionActions.deleteSelection(),
    },
    {
      keys: 'Delete',
      label: 'Delete selection',
      group: 'Edit',
      run: (ctx) => ctx.controller.selectionActions.deleteSelection(),
    },
    {
      keys: 'Escape',
      label: 'Clear selection',
      group: 'Edit',
      allowInTextEntry: true,
      run: (ctx) => {
        // Escape from a field should return focus to the canvas rather than
        // clearing the selection out from under the user.
        if (isTextEntry(document.activeElement)) {
          (document.activeElement as HTMLElement).blur();
          return;
        }
        ctx.controller.selection.clear();
      },
    },

    { keys: 'ArrowUp', label: 'Nudge up', group: 'Arrange', run: nudge(0, -1, false) },
    { keys: 'ArrowDown', label: 'Nudge down', group: 'Arrange', run: nudge(0, 1, false) },
    { keys: 'ArrowLeft', label: 'Nudge left', group: 'Arrange', run: nudge(-1, 0, false) },
    { keys: 'ArrowRight', label: 'Nudge right', group: 'Arrange', run: nudge(1, 0, false) },
    { keys: 'Shift+ArrowUp', label: 'Nudge up ×5', group: 'Arrange', run: nudge(0, -1, true) },
    { keys: 'Shift+ArrowDown', label: 'Nudge down ×5', group: 'Arrange', run: nudge(0, 1, true) },
    { keys: 'Shift+ArrowLeft', label: 'Nudge left ×5', group: 'Arrange', run: nudge(-1, 0, true) },
    {
      keys: 'Shift+ArrowRight',
      label: 'Nudge right ×5',
      group: 'Arrange',
      run: nudge(1, 0, true),
    },

    {
      keys: 'Mod+Plus',
      label: 'Zoom in',
      group: 'View',
      run: (ctx) => ctx.viewport.zoomIn(),
    },
    {
      keys: 'Mod+Minus',
      label: 'Zoom out',
      group: 'View',
      run: (ctx) => ctx.viewport.zoomOut(),
    },
    {
      keys: 'Mod+0',
      label: 'Reset zoom',
      group: 'View',
      run: (ctx) => ctx.viewport.resetZoom(),
    },
    {
      keys: 'Mod+1',
      label: 'Fit to screen',
      group: 'View',
      run: (ctx) => ctx.viewport.fit(ctx.controller.model.bounds()),
    },
    {
      keys: 'Mod+Shift+1',
      label: 'Fit to selection',
      group: 'View',
      run: (ctx) => ctx.viewport.fit(ctx.controller.selectionActions.bounds()),
    },

    ...extra,
  ];
}

/**
 * Matches a "Mod+Shift+Z" spec against a keyboard event.
 *
 * Compares against `event.code` for letters and digits rather than `key`, so
 * a binding survives a non-US layout and an active modifier (on macOS,
 * ⌥-combinations rewrite `key` entirely).
 */
function matches(spec: string, event: KeyboardEvent): boolean {
  const parts = spec.split('+').map((part) => part.trim().toLowerCase());
  const key = parts[parts.length - 1] ?? '';

  const wantsMod = parts.includes('mod');
  const wantsShift = parts.includes('shift');
  const wantsAlt = parts.includes('alt');

  const modPressed = IS_APPLE ? event.metaKey : event.ctrlKey;
  // The mod key must not be held when the binding doesn't ask for it, or
  // Cmd-R would trigger the plain "R" binding.
  if (wantsMod !== modPressed) return false;
  if (wantsShift !== event.shiftKey) return false;
  if (wantsAlt !== event.altKey) return false;

  const code = event.code.toLowerCase();
  switch (key) {
    case 'plus':
      return code === 'equal' || code === 'numpadadd' || event.key === '+' || event.key === '=';
    case 'minus':
      return code === 'minus' || code === 'numpadsubtract' || event.key === '-';
    case 'escape':
      return code === 'escape';
    case 'backspace':
      return code === 'backspace';
    case 'delete':
      return code === 'delete';
    case 'arrowup':
    case 'arrowdown':
    case 'arrowleft':
    case 'arrowright':
      return code === key;
    default:
      if (key.length === 1 && key >= 'a' && key <= 'z') return code === `key${key}`;
      if (key.length === 1 && key >= '0' && key <= '9') return code === `digit${key}`;
      return event.key.toLowerCase() === key;
  }
}
