import type { ReactNode } from 'react';
import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { Icon, type IconSize } from './Icon';
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

export function Badge({
  tone = 'neutral',
  numeric,
  children,
  className,
}: {
  tone?: 'neutral' | 'accent' | 'success' | 'danger';
  numeric?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={clsx(
        'badge',
        tone !== 'neutral' && `badge--${tone}`,
        numeric && 'badge--numeric',
        className,
      )}
    >
      {children}
    </span>
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
