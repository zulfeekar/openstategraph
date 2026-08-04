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
  size?: IconSize;
  /** Stroke weight. 1.75 reads crisper than lucide's default 2 at 14–16px. */
  strokeWidth?: number;
  className?: string;
  /** Decorative by default; pass a label to expose it to assistive tech. */
  label?: string;
}

export function Icon({ glyph, size = 'md', strokeWidth = 1.75, className, label }: IconProps) {
  return createElement(glyph, {
    size: ICON_SIZE[size],
    strokeWidth,
    className,
    'aria-hidden': label ? undefined : true,
    'aria-label': label,
    role: label ? 'img' : undefined,
    focusable: false,
  });
}

export { ICON_SIZE };
