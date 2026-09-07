import { useMemo, useState } from 'react';
import { ChevronRight, Keyboard } from 'lucide-react';
import { Icon, Kbd } from '@design/primitives';
import type { Shortcut } from '@canvas/features/KeyboardFeature';
import type { IPortTypeDefinition } from '@core/model/contracts/ports';
import './overlays.css';

/**
 * The keyboard reference, plus the canvas legend.
 *
 * Shortcut rows are rendered from the *same* binding table the keyboard
 * feature dispatches on, so the documentation cannot drift from the
 * behaviour — the usual failure of a hand-maintained shortcut list. That rule
 * is untouched here: this drawer still reads the table and never restates it.
 *
 * The edge legend obeys the same discipline one level over: it is rendered
 * from the registered port types, so a plugin that registers a port type gets
 * a legend row for free and nothing here names a node type or a colour.
 * Housed in this drawer rather than a fourth floating box because the canvas
 * corner already carries three, and a legend is reference material — exactly
 * what this surface is for.
 */
export function ShortcutsDrawer({
  shortcuts,
  portTypes = [],
}: {
  shortcuts: readonly Shortcut[];
  portTypes?: readonly IPortTypeDefinition[];
}) {
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
        Shortcuts &amp; legend
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

          {portTypes.length > 0 ? (
            <section className="shortcuts__group">
              <h3 className="shortcuts__group-title">Edge colours</h3>
              {portTypes.map((portType) => (
                <div key={portType.id} className="shortcuts__row">
                  <span>{portType.label}</span>
                  {/* The swatch is drawn with the same accent variable and
                      the same dash signature the canvas uses, so the legend
                      cannot describe a line the canvas does not draw. */}
                  <span
                    className="legend__swatch"
                    data-accent={portType.accent}
                    data-port-type={portType.id}
                    aria-hidden="true"
                  />
                </div>
              ))}
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
