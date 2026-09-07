import clsx from 'clsx';
import './Tabs.css';

export interface TabDefinition<Id extends string = string> {
  id: Id;
  label: string;
}

interface TabsProps<Id extends string> {
  tabs: readonly TabDefinition<Id>[];
  active: Id;
  onChange: (id: Id) => void;
  className?: string;
}

/**
 * A row of mutually-exclusive tabs. Renders only the tablist — the caller
 * decides what each tab shows and switches on `active` itself. Kept this
 * narrow (no built-in panel) so a consumer with framework-specific content
 * (a form, a list backed by a fetch) is never forced through a generic
 * `children` shape it does not need.
 *
 * Generic over the tab id union so a caller with a closed set of tab ids
 * (e.g. `'new' | 'saved' | 'examples'`) gets that type back from `onChange`
 * rather than a widened `string` a `useState<TabId>` setter cannot accept.
 */
export function Tabs<Id extends string>({ tabs, active, onChange, className }: TabsProps<Id>) {
  return (
    <div className={clsx('tabs', className)} role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={tab.id === active}
          className={clsx('tabs__tab', tab.id === active && 'tabs__tab--active')}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
