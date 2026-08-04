import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import clsx from 'clsx';
import './Button.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Leading glyph. Sized by the caller via `<Icon>`. */
  icon?: ReactNode;
  /** Trailing glyph — chevrons, external-link marks. */
  iconTrailing?: ReactNode;
  /** Renders the pressed/active look for mode toggles. */
  active?: boolean;
  children?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', icon, iconTrailing, active, className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={clsx('btn', `btn--${variant}`, size !== 'md' && `btn--${size}`, className)}
      data-state={active ? 'on' : undefined}
      aria-pressed={active}
      {...rest}
    >
      {icon}
      {children}
      {iconTrailing}
    </button>
  );
});

interface IconButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  /** Required — an icon-only control is meaningless to a screen reader without it. */
  label: string;
  icon: ReactNode;
  size?: 'xs' | 'sm' | 'md' | 'lg';
  active?: boolean;
  /** Tint the toggled-on state with the inherited accent instead of neutral. */
  accent?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, icon, size = 'md', active, accent, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={clsx(
        'icon-btn',
        size !== 'md' && `icon-btn--${size}`,
        accent && 'icon-btn--accent',
        className,
      )}
      aria-label={label}
      data-state={active ? 'on' : undefined}
      aria-pressed={active}
      {...rest}
    >
      {icon}
    </button>
  );
});
