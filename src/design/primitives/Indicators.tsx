import type { ReactNode } from 'react';
import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { Icon, type IconSize } from './Icon';
import { Tooltip } from './Tooltip';
import './Indicators.css';

/* ------------------------------------------------------------------ *
 * StatusDot — the small coloured dot preceding a node title.
 * ------------------------------------------------------------------ */

/**
 * `paused` is deliberately the one non-terminal tone that does not animate:
 * it means "waiting for a person", and a pulse there would say "working".
 */
export type StatusTone = 'idle' | 'ready' | 'running' | 'paused' | 'success' | 'warning' | 'error';

export function StatusDot({ tone = 'idle', label }: { tone?: StatusTone; label?: string }) {
  return (
    <span
      className={clsx('status-dot', tone !== 'idle' && `status-dot--${tone}`)}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}

/* ------------------------------------------------------------------ *
 * Badge
 * ------------------------------------------------------------------ */

/**
 * A short mark beside a name.
 *
 * ## A word on a badge is a claim, and a claim owes the reader a sentence
 *
 * `say-it-on-the-surface` 05. The palette printed **Hidden** beside two
 * packages and the owner, driving the product, asked what it meant. The
 * sentence existed — `HIDDEN_PACKAGE_NOTE`, one constant, deliberately — and
 * it was hung off the *row's* native `title`: a second of delay, anchored at
 * the pointer rather than at the word, invisible to touch and to keyboard
 * focus, and concatenated with the row's own hint so the answer was the second
 * paragraph of a string nobody waited for.
 *
 * The deeper reason nobody fixed it is here, in this component: `Badge` had
 * `tone`, `numeric`, `children` and `className`, and **no way to carry an
 * explanation at all**. A badge was structurally incapable of saying what it
 * meant, so every author who wanted to explain one had to reach past the
 * primitive. The rule and the means now live together:
 *
 * > **A badge whose content is a word takes an `explanation`. A `numeric`
 * > badge — a count beside the thing it counts — does not.**
 *
 * `src/design/badgeExplanations.test.ts` walks every call site and fails on a
 * word badge that explains nothing, so the rule is a red test rather than a
 * paragraph. Exceptions are recorded there, each with its argument.
 *
 * An explained badge is **focusable** (`tabIndex={0}`) and typed `role="note"`.
 * A hover-only explanation is the same defect one input device along, which is
 * the whole complaint restated — so it is not an option this component offers.
 */
export function Badge({
  tone = 'neutral',
  numeric,
  explanation,
  children,
  className,
}: {
  tone?: 'neutral' | 'accent' | 'success' | 'danger';
  numeric?: boolean;
  /**
   * What this mark means, in a sentence. Comes from wherever the claim itself
   * is owned — never re-worded at the call site, for the reason
   * `HIDDEN_PACKAGE_NOTE` records: two spellings of one verdict agree on the
   * day they are written and drift on the first reword.
   */
  explanation?: string;
  children: ReactNode;
  className?: string;
}) {
  const mark = (
    <span
      className={clsx(
        'badge',
        tone !== 'neutral' && `badge--${tone}`,
        numeric && 'badge--numeric',
        explanation && 'badge--explained',
        className,
      )}
      {...(explanation ? { tabIndex: 0, role: 'note' as const } : {})}
    >
      {children}
    </span>
  );
  if (!explanation) return mark;
  return (
    <Tooltip content={explanation} multiline>
      {mark}
    </Tooltip>
  );
}

/* ------------------------------------------------------------------ *
 * IconTile — a node family's glyph on its accent tint.
 * ------------------------------------------------------------------ */

export function IconTile({
  glyph,
  size = 'md',
  iconSize,
  className,
}: {
  glyph: LucideIcon;
  size?: 'sm' | 'md' | 'lg';
  iconSize?: IconSize;
  className?: string;
}) {
  const resolved: IconSize = iconSize ?? (size === 'sm' ? 'sm' : size === 'lg' ? 'lg' : 'md');
  return (
    <span className={clsx('icon-tile', size !== 'md' && `icon-tile--${size}`, className)}>
      <Icon glyph={glyph} size={resolved} />
    </span>
  );
}

/* ------------------------------------------------------------------ *
 * Kbd — renders "Mod+Z" style specs as platform-correct key caps.
 * ------------------------------------------------------------------ */

const IS_APPLE =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad|iPod/.test(navigator.platform || '');

const KEY_GLYPHS: Record<string, string> = {
  mod: IS_APPLE ? '⌘' : 'Ctrl',
  meta: IS_APPLE ? '⌘' : 'Win',
  cmd: '⌘',
  ctrl: IS_APPLE ? '⌃' : 'Ctrl',
  alt: IS_APPLE ? '⌥' : 'Alt',
  shift: IS_APPLE ? '⇧' : 'Shift',
  enter: '↵',
  escape: 'Esc',
  esc: 'Esc',
  backspace: '⌫',
  delete: '⌦',
  arrowup: '↑',
  arrowdown: '↓',
  arrowleft: '←',
  arrowright: '→',
  space: 'Space',
  plus: '+',
  minus: '−',
};

/** "Mod+Shift+Z" → ["⌘", "⇧", "Z"]. Module-local: `Kbd` renders the caps and
 *  `shortcutText` the compact form, so nothing outside needs the array. */
function formatShortcut(spec: string): string[] {
  return spec
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => KEY_GLYPHS[part.toLowerCase()] ?? part.toUpperCase());
}

/** Compact single-string form, for tooltips where caps are too heavy. */
export function shortcutText(spec: string): string {
  const keys = formatShortcut(spec);
  return IS_APPLE ? keys.join('') : keys.join('+');
}

export function Kbd({ keys }: { keys: string }) {
  return (
    <span className="kbd-group">
      {formatShortcut(keys).map((key, index) => (
        <kbd key={`${key}-${index}`} className="kbd">
          {key}
        </kbd>
      ))}
    </span>
  );
}

export { IS_APPLE };
