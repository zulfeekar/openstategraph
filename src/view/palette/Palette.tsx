import { useMemo, useState, useSyncExternalStore } from 'react';
import clsx from 'clsx';
import { Search, X } from 'lucide-react';
import {
  Icon,
  IconButton,
  IconTile,
  Panel,
  PanelBody,
  PanelEmpty,
  PanelHeader,
  PanelSection,
  TextInput,
} from '@design/primitives';
import { matchesQuery } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import { useController, usePaperController, useWorkbench } from '@app/WorkbenchContext';
import { resolveIcon } from '@view/icons/iconRegistry';
import './Palette.css';

/** Custom drag type, so canvas drops can tell a palette drag from a file. */
export const PALETTE_DRAG_TYPE = 'application/x-dyflow-node-type';

interface PaletteProps {
  onNotify: (message: string) => void;
}

/**
 * The node palette — the open-source stand-in for the commercial stencil.
 *
 * Contents come entirely from the registry, so it is never out of date with
 * what the engine can actually run. Two ways to add a node, because both
 * habits are common: drag onto the canvas for placement control, or click to
 * drop one into the middle of the current view.
 */
export function Palette({ onNotify }: PaletteProps) {
  const workbench = useWorkbench();
  const controller = useController();
  const paper = usePaperController();
  const [query, setQuery] = useState('');

  // Node types are not only registered once at startup: workflow-scoped
  // node types (Chinook's tools) are registered and unregistered as the
  // current document changes (`syncWorkflowScopedNodes`), so the palette
  // has to be reactive to the registry, not just to a query string —
  // otherwise a workflow-scoped type would never appear until a full
  // reload, which would make the fix that added it invisible.
  useSyncExternalStore(
    (onStoreChange) => workbench.registry.nodeTypes.onChange(onStoreChange),
    () => workbench.registry.nodeTypes.size,
  );

  const sections = useMemo(() => {
    const all = workbench.registry.paletteSections();
    if (!query.trim()) return all;
    return all
      .map((section) => ({
        ...section,
        nodes: section.nodes.filter((definition) => matchesQuery(definition, query)),
      }))
      .filter((section) => section.nodes.length > 0);
    // Recomputed on every render this component takes, including the ones
    // `useSyncExternalStore` above forces — `workbench.registry` itself
    // never changes identity, so it cannot be a dependency that triggers this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workbench, query, workbench.registry.nodeTypes.size]);

  const add = (definition: INodeDefinition) => {
    const at = paper?.viewportCenter() ?? { x: 120, y: 120 };
    const outcome = controller.nodes.add(definition.id, at);
    if (!outcome.ok && outcome.message) onNotify(outcome.message);
  };

  return (
    <Panel side="left" className="palette" style={{ width: 'var(--layout-palette-width)' }}>
      <PanelHeader>
        <TextInput
          value={query}
          placeholder="Search nodes…"
          aria-label="Search nodes"
          prefix={<Icon glyph={Search} size="sm" />}
          onChange={(event) => setQuery(event.target.value)}
          suffix={
            query ? (
              <IconButton
                size="xs"
                label="Clear search"
                icon={<Icon glyph={X} size="xs" />}
                onClick={() => setQuery('')}
              />
            ) : undefined
          }
        />
      </PanelHeader>

      <PanelBody>
        {sections.length === 0 ? (
          <PanelEmpty
            glyph={Search}
            title="No matches"
            body={`Nothing in the palette matches “${query}”.`}
          />
        ) : (
          sections.map((section) => (
            <PanelSection key={section.category.id} heading={section.category.label}>
              {section.nodes.map((definition) => (
                <PaletteItem
                  key={definition.id}
                  definition={definition}
                  disabled={isAtLimit(workbench, definition)}
                  onActivate={() => add(definition)}
                />
              ))}
            </PanelSection>
          ))
        )}
      </PanelBody>
    </Panel>
  );
}

function PaletteItem({
  definition,
  disabled,
  onActivate,
}: {
  definition: INodeDefinition;
  disabled: boolean;
  onActivate: () => void;
}) {
  return (
    <button
      type="button"
      className={clsx('palette-item', disabled && 'palette-item--disabled')}
      data-accent={definition.accent}
      // Native HTML5 drag rather than pointer events: it gives the OS drag
      // image, the copy cursor and drop-target semantics for free.
      draggable={!disabled}
      aria-disabled={disabled}
      title={disabled ? `Only one ${definition.label} is allowed` : definition.description}
      onDragStart={(event) => {
        if (disabled) {
          event.preventDefault();
          return;
        }
        event.dataTransfer.setData(PALETTE_DRAG_TYPE, definition.id);
        event.dataTransfer.effectAllowed = 'copy';
      }}
      onClick={() => {
        if (!disabled) onActivate();
      }}
    >
      <IconTile glyph={resolveIcon(definition.iconId)} size="md" iconSize="sm" />
      <span className="palette-item__text">
        <span className="palette-item__title">{definition.label}</span>
        <span className="palette-item__description">{definition.description}</span>
      </span>
    </button>
  );
}

function isAtLimit(
  workbench: ReturnType<typeof useWorkbench>,
  definition: INodeDefinition,
): boolean {
  if (definition.maxInstances == null) return false;
  return workbench.model.countOfType(definition.id) >= definition.maxInstances;
}
