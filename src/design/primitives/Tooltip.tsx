import {
  cloneElement,
  isValidElement,
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';
import clsx from 'clsx';
import { useFloating, type Alignment, type Placement } from './useFloating';
import './Tooltip.css';

interface TooltipProps {
  content: ReactNode;
  /** Keyboard hint rendered dimmed after the label, e.g. "⌘Z". */
  shortcut?: string;
  placement?: Placement;
  align?: Alignment;
  /** Dwell time before showing, in ms. 0 for immediate. */
  delay?: number;
  /** Allow the content to wrap onto multiple lines. */
  multiline?: boolean;
  disabled?: boolean;
  /** Single element that acts as the anchor; receives the event handlers. */
  children: ReactElement<Record<string, unknown>>;
}

export function Tooltip({
  content,
  shortcut,
  placement = 'bottom',
  align = 'center',
  delay = 350,
  multiline,
  disabled,
  children,
}: TooltipProps) {
  const anchorRef = useRef<HTMLElement | null>(null);
  const floatingRef = useRef<HTMLDivElement | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const [open, setOpen] = useState(false);

  const position = useFloating(anchorRef, floatingRef, {
    placement,
    align,
    offset: 8,
    enabled: open,
  });

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const show = () => {
    if (disabled) return;
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setOpen(true), delay);
  };

  const hide = () => {
    window.clearTimeout(timer.current);
    setOpen(false);
  };

  if (!isValidElement(children)) return children;

  // React 19 made `ref` an ordinary prop, so the caller's ref (if any) lives
  // in `props` — reading `element.ref` now warns and returns nothing.
  const forwardedRef = children.props['ref'];

  const anchor = cloneElement(children, {
    ref: (node: HTMLElement | null) => {
      anchorRef.current = node;
      // Preserve whatever ref the caller already put on the child.
      if (typeof forwardedRef === 'function') {
        (forwardedRef as (n: HTMLElement | null) => void)(node);
      } else if (forwardedRef && typeof forwardedRef === 'object') {
        (forwardedRef as { current: HTMLElement | null }).current = node;
      }
    },
    onMouseEnter: (event: MouseEvent) => {
      (children.props['onMouseEnter'] as ((e: MouseEvent) => void) | undefined)?.(event);
      show();
    },
    onMouseLeave: (event: MouseEvent) => {
      (children.props['onMouseLeave'] as ((e: MouseEvent) => void) | undefined)?.(event);
      hide();
    },
    onFocus: (event: FocusEvent) => {
      (children.props['onFocus'] as ((e: FocusEvent) => void) | undefined)?.(event);
      // Focus should surface the hint immediately — a keyboard user has
      // already committed to the control.
      window.clearTimeout(timer.current);
      setOpen(true);
    },
    onBlur: (event: FocusEvent) => {
      (children.props['onBlur'] as ((e: FocusEvent) => void) | undefined)?.(event);
      hide();
    },
    // A click means the user acted; the hint has served its purpose.
    onPointerDown: (event: PointerEvent) => {
      (children.props['onPointerDown'] as ((e: PointerEvent) => void) | undefined)?.(event);
      hide();
    },
  } as Record<string, unknown>);

  return (
    <>
      {anchor}
      {open
        ? createPortal(
            <div
              ref={floatingRef}
              role="tooltip"
              className={clsx('tooltip', multiline && 'tooltip--multiline')}
              style={{
                transform: `translate3d(${position?.x ?? 0}px, ${position?.y ?? 0}px, 0)`,
                visibility: position ? 'visible' : 'hidden',
              }}
            >
              <span>{content}</span>
              {shortcut ? <span className="tooltip__kbd">{shortcut}</span> : null}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
