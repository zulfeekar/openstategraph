import { useCallback, useEffect, useRef, useState, type RefObject } from 'react';
import { createPortal } from 'react-dom';
import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { Icon } from './Icon';
import { useFloating, type Alignment, type Placement } from './useFloating';
import './Menu.css';

export interface MenuItem {
  kind?: 'item';
  id: string;
  label: string;
  icon?: LucideIcon;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export interface MenuSeparator {
  kind: 'separator';
  id: string;
}

export interface MenuLabel {
  kind: 'label';
  id: string;
  label: string;
}

export type MenuEntry = MenuItem | MenuSeparator | MenuLabel;

const isItem = (entry: MenuEntry): entry is MenuItem => (entry.kind ?? 'item') === 'item';

interface MenuProps {
  /** The control the menu hangs off; also the click-outside exemption. */
  anchorRef: RefObject<HTMLElement | null>;
  entries: readonly MenuEntry[];
  open: boolean;
  onClose: () => void;
  placement?: Placement;
  align?: Alignment;
}

/**
 * A portal-rendered dropdown with roving keyboard focus.
 *
 * Rendered into `document.body` rather than in place, so a menu opened
 * from a node inside the SVG canvas is never clipped by the paper's
 * viewport or scaled by its transform.
 */
export function Menu({
  anchorRef,
  entries,
  open,
  onClose,
  placement = 'bottom',
  align = 'end',
}: MenuProps) {
  const floatingRef = useRef<HTMLDivElement | null>(null);
  const [highlighted, setHighlighted] = useState(-1);

  const position = useFloating(anchorRef, floatingRef, {
    placement,
    align,
    offset: 4,
    enabled: open,
  });

  const selectable = entries.filter((entry) => isItem(entry) && !entry.disabled) as MenuItem[];

  useEffect(() => {
    if (!open) setHighlighted(-1);
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (floatingRef.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      switch (event.key) {
        case 'Escape':
          event.preventDefault();
          onClose();
          break;
        case 'ArrowDown':
          event.preventDefault();
          setHighlighted((i) => (i + 1) % Math.max(selectable.length, 1));
          break;
        case 'ArrowUp':
          event.preventDefault();
          setHighlighted((i) => (i <= 0 ? selectable.length - 1 : i - 1));
          break;
        case 'Enter':
        case ' ': {
          const item = selectable[highlighted];
          if (item) {
            event.preventDefault();
            item.onSelect();
            onClose();
          }
          break;
        }
      }
    };

    // Capture phase: the canvas installs its own document-level pointer
    // handlers, and the menu must win the race to close first.
    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose, anchorRef, selectable, highlighted]);

  if (!open) return null;

  let itemIndex = -1;

  return createPortal(
    <div
      ref={floatingRef}
      role="menu"
      className="menu"
      style={{
        transform: `translate3d(${position?.x ?? 0}px, ${position?.y ?? 0}px, 0)`,
        visibility: position ? 'visible' : 'hidden',
      }}
    >
      {entries.map((entry) => {
        if (entry.kind === 'separator') {
          return <div key={entry.id} role="separator" className="menu__separator" />;
        }
        if (entry.kind === 'label') {
          return (
            <div key={entry.id} className="menu__label">
              {entry.label}
            </div>
          );
        }
        if (!entry.disabled) itemIndex += 1;
        const index = entry.disabled ? -1 : itemIndex;
        return (
          <button
            key={entry.id}
            type="button"
            role="menuitem"
            className={clsx('menu__item', entry.danger && 'menu__item--danger')}
            data-highlighted={index >= 0 && index === highlighted ? 'true' : undefined}
            disabled={entry.disabled}
            onMouseEnter={() => setHighlighted(index)}
            onClick={() => {
              entry.onSelect();
              onClose();
            }}
          >
            {entry.icon ? (
              <span className="menu__item-icon">
                <Icon glyph={entry.icon} size="sm" />
              </span>
            ) : null}
            <span className="menu__item-label">{entry.label}</span>
            {entry.shortcut ? <span className="menu__item-shortcut">{entry.shortcut}</span> : null}
          </button>
        );
      })}
    </div>,
    document.body,
  );
}

/**
 * Open/close plumbing for a menu attached to a single trigger.
 *
 * `triggerProps` stops propagation because these menus usually hang off a
 * node card sitting on the canvas, and the click must not also reach the
 * paper's selection handler.
 */
export function useMenu<T extends HTMLElement = HTMLButtonElement>() {
  const anchorRef = useRef<T | null>(null);
  const [open, setOpen] = useState(false);

  const close = useCallback(() => setOpen(false), []);

  return {
    open,
    anchorRef,
    close,
    toggle: useCallback(() => setOpen((v) => !v), []),
    triggerProps: {
      onClick: useCallback((event: React.MouseEvent) => {
        event.stopPropagation();
        setOpen((v) => !v);
      }, []),
      onPointerDown: useCallback((event: React.PointerEvent) => {
        event.stopPropagation();
      }, []),
    },
  };
}
