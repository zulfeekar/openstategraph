import { useMemo, useState } from 'react';
import { ChevronRight, Keyboard } from 'lucide-react';
import { Icon, Kbd } from '@design/primitives';
import type { Shortcut } from '@canvas/features/KeyboardFeature';
import './overlays.css';

/**
 * The keyboard reference.
 *
 * Rendered from the *same* binding table the keyboard feature dispatches on,
 * so the documentation cannot drift from the behaviour — the usual failure of
 * a hand-maintained shortcut list.
 */
export function ShortcutsDrawer({ shortcuts }: { shortcuts: readonly Shortcut[] }) {
  const [open, setOpen] = useState(false);

  const groups = useMemo(() => {
    const byGroup = new Map<string, Shortcut[]>();
    for (const shortcut of shortcuts) {
      // Several keys can drive the same action (Backspace and Delete both
      // delete); showing both rows is noise, so the first wins per label.
      const bucket = byGroup.get(shortcut.group) ?? [];
      if (!bucket.some((existing) => existing.label === shortcut.label)) {
        bucket.push(shortcut);
      }
      byGroup.set(shortcut.group, bucket);
    }
    return [...byGroup.entries()];
  }, [shortcuts]);

  return (
    <div className="shortcuts">
      <button
        type="button"
        className="shortcuts__trigger"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon glyph={open ? ChevronRight : Keyboard} size="sm" />
        Keyboard shortcuts
      </button>

      {open ? (
        <div className="shortcuts__panel">
          {groups.map(([group, items]) => (
            <section key={group} className="shortcuts__group">
              <h3 className="shortcuts__group-title">{group}</h3>
              {items.map((shortcut) => (
                <div key={`${group}-${shortcut.label}`} className="shortcuts__row">
                  <span>{shortcut.label}</span>
                  <Kbd keys={shortcut.keys} />
                </div>
              ))}
            </section>
          ))}
        </div>
      ) : null}
    </div>
  );
}
