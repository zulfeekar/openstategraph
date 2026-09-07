import type { LucideIcon } from 'lucide-react';
import { createElement } from 'react';

/**
 * Icon sizes are a closed set. Free-form pixel values are how icon
 * alignment rots across a UI, so callers pick a step instead.
 */
const ICON_SIZE = {
  xs: 12,
  sm: 14,
  md: 16,
  lg: 18,
  xl: 20,
} as const;

export type IconSize = keyof typeof ICON_SIZE;

interface IconProps {
  glyph: LucideIcon;
  /**
   * Omit it and the icon takes `md`, but *yields* — a control that knows
   * better (a small button, a badge) may size it down from CSS. Name a
   * size and it is stamped with `data-icon-size`, which those rules skip.
   * So a deliberate choice always wins and an absent one adapts.
   */
  size?: IconSize;
  /** Stroke weight. 1.75 reads crisper than lucide's default 2 at 14–16px. */
  strokeWidth?: number;
  className?: string;
  /** Decorative by default; pass a label to expose it to assistive tech. */
  label?: string;
}

export function Icon({ glyph, size, strokeWidth = 1.75, className, label }: IconProps) {
  // Spread rather than declared inline: lucide's prop type has no index
  // signature, so an inline `data-*` key trips the excess-property check.
  const sizeMarker = size ? { 'data-icon-size': size } : {};

  return createElement(glyph, {
    ...sizeMarker,
    size: ICON_SIZE[size ?? 'md'],
    strokeWidth,
    className,
    'aria-hidden': label ? undefined : true,
    'aria-label': label,
    role: label ? 'img' : undefined,
    focusable: false,
  });
}

export { ICON_SIZE };
