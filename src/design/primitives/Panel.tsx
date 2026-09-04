import type { ReactNode } from 'react';
import clsx from 'clsx';
import type { LucideIcon } from 'lucide-react';
import { Icon } from './Icon';
import './Panel.css';

interface PanelProps {
  side?: 'left' | 'right';
  className?: string;
  style?: React.CSSProperties;
  children: ReactNode;
}

export function Panel({ side, className, style, children }: PanelProps) {
  return (
    <aside className={clsx('panel', side && `panel--${side}`, className)} style={style}>
      {children}
    </aside>
  );
}

export function PanelHeader({
  title,
  actions,
  bordered,
  children,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  bordered?: boolean;
  children?: ReactNode;
}) {
  return (
    <header className={clsx('panel__header', bordered && 'panel__header--bordered')}>
      {title ? <h2 className="panel__title">{title}</h2> : null}
      {children}
      {actions}
    </header>
  );
}

export function PanelBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx('panel__body', className)}>{children}</div>;
}

export function PanelFooter({
  className,
  children,
  ...rest
}: React.ComponentPropsWithoutRef<'footer'> & { className?: string; children: ReactNode }) {
  return (
    <footer className={clsx('panel__footer', className)} {...rest}>
      {children}
    </footer>
  );
}

export function PanelSection({
  heading,
  aside,
  className,
  children,
}: {
  heading?: string;
  aside?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={clsx('panel-section', className)}>
      {heading ? (
        <div className="panel-section__heading">
          <span>{heading}</span>
          {aside}
        </div>
      ) : null}
      <div className="panel-section__items">{children}</div>
    </section>
  );
}

export function PanelEmpty({
  glyph,
  title,
  body,
}: {
  glyph?: LucideIcon;
  title: string;
  body?: string;
}) {
  return (
    <div className="panel-empty">
      {glyph ? (
        <span className="panel-empty__icon">
          <Icon glyph={glyph} size="lg" />
        </span>
      ) : null}
      <span className="panel-empty__title">{title}</span>
      {body ? <span className="panel-empty__body">{body}</span> : null}
    </div>
  );
}
