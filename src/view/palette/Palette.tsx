import { useMemo, useState, useSyncExternalStore } from 'react';
import clsx from 'clsx';
import { Package, RefreshCw, Search, X } from 'lucide-react';
import {
  Badge,
  Button,
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
import type { INodeCategory, INodeDefinition } from '@core/model/contracts/node';
import { useController, usePaperController, useWorkbench } from '@app/WorkbenchContext';
import { refreshWorkflowCapabilities } from '@app/capabilityRefresh';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { resolveIcon } from '@view/icons/iconRegistry';
import './Palette.css';

/** Custom drag type, so canvas drops can tell a palette drag from a file. */
export const PALETTE_DRAG_TYPE = 'application/x-openstategraph-node-type';

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
  const [refreshing, setRefreshing] = useState(false);

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

  // Two provenances, presented as two different things — the problem this
  // split exists to fix is that a Chinook tool and the Agent node looked
  // identical in the palette, so nothing told a developer that one of them
  // vanishes the moment they open a different workflow. Workflow-scoped
  // types are lifted out of their categories into a single leading section
  // (they are few, and *where they came from* matters more than which
  // category they'd land in); everything else keeps its normal sectioning.
  const { scoped, appSections, matchCount } = useMemo(() => {
    const all = workbench.registry.paletteSections();
    const searching = query.trim().length > 0;
    const visible = searching
      ? all
          .map((section) => ({
            ...section,
            nodes: section.nodes.filter((definition) => matchesQuery(definition, query)),
          }))
          .filter((section) => section.nodes.length > 0)
      : all;

    const scopedNodes: INodeDefinition[] = [];
    const rest: { category: INodeCategory; nodes: readonly INodeDefinition[] }[] = [];
    for (const section of visible) {
      const app = section.nodes.filter((definition) => definition.scope !== 'workflow');
      for (const definition of section.nodes) {
        if (definition.scope === 'workflow') scopedNodes.push(definition);
      }
      if (app.length > 0) rest.push({ ...section, nodes: app });
    }
    return {
      scoped: scopedNodes,
      appSections: rest,
      matchCount: scopedNodes.length + rest.reduce((n, s) => n + s.nodes.length, 0),
    };
    // Recomputed on every render this component takes, including the ones
    // `useSyncExternalStore` above forces — `workbench.registry` itself
    // never changes identity, so it cannot be a dependency that triggers this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workbench, query, workbench.registry.nodeTypes.size]);

  const searching = query.trim().length > 0;

  // Hot discovery, on demand. Writing a `tools/*.py` file changes nothing
  // `workflow.json`'s watcher looks at, and polling the discovery endpoint
  // every few seconds to catch an event that happens a handful of times a
  // session is a bad trade — so the author, who already knows the moment
  // they saved the file, asks. The registry is an external store the
  // palette already subscribes to, so a successful refresh repaints this
  // list with no extra state.
  const refresh = async () => {
    setRefreshing(true);
    try {
      const outcome = await refreshWorkflowCapabilities(
        sessionStorage.getItem(CURRENT_SLUG_KEY),
        workbench.registry,
        workbench.engine.executors,
      );
      switch (outcome.kind) {
        case 'no-workflow':
          onNotify('Save this workflow first — tools are discovered from its own folder.');
          break;
        case 'changed':
          // A change with nothing added is a *removal* — a tool file that
          // was deleted or stopped exporting a tool. Saying "0 new tools"
          // would report the one thing that did not happen.
          onNotify(
            outcome.added.length === 0
              ? 'Tools refreshed — one is no longer discovered.'
              : outcome.added.length === 1
                ? `Discovered a new tool: ${outcome.added[0]}`
                : `Discovered ${outcome.added.length} new tools`,
          );
          break;
        case 'unchanged':
          onNotify(
            outcome.total === 0
              ? 'No tools found in this workflow’s tools/ folder.'
              : 'Tools are up to date.',
          );
          break;
      }
    } finally {
      setRefreshing(false);
    }
  };

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
        {matchCount === 0 ? (
          <PanelEmpty
            glyph={Search}
            title="No matches"
            body={`Nothing in the palette matches “${query}”.`}
          />
        ) : null}

        {matchCount > 0 && (searching ? scoped.length > 0 : true) ? (
          <PanelSection
            className="palette-section--scoped"
            heading="This workflow"
            aside={
              <span className="palette-scoped-aside">
                {scoped.length > 0 ? (
                  <Badge tone="accent" numeric>
                    {scoped.length}
                  </Badge>
                ) : null}
                <IconButton
                  size="xs"
                  label={refreshing ? 'Refreshing tools' : 'Refresh tools'}
                  disabled={refreshing}
                  icon={
                    <Icon
                      glyph={RefreshCw}
                      size="xs"
                      className={refreshing ? 'palette-refresh--spinning' : undefined}
                    />
                  }
                  onClick={() => void refresh()}
                />
              </span>
            }
          >
            {scoped.length > 0 ? (
              <>
                <p className="palette-note">
                  From this workflow&rsquo;s own package — they leave the palette when you open
                  another one.
                </p>
                {scoped.map((definition) => (
                  <PaletteItem
                    key={definition.id}
                    definition={definition}
                    disabled={isAtLimit(workbench, definition)}
                    onActivate={() => add(definition)}
                  />
                ))}
              </>
            ) : (
              <p className="palette-note">
                This workflow has no tools of its own yet. Python tools in its <code>tools/</code>{' '}
                folder show up here as nodes you can wire in — just added one? Press Refresh.
              </p>
            )}
          </PanelSection>
        ) : null}

        {appSections.length > 0 ? (
          <>
            <div className="palette-group-label">
              Always available
              <span className="palette-group-label__hint">in every workflow</span>
            </div>
            {appSections.map((section) => (
              <PanelSection
                key={section.category.id}
                heading={section.category.label}
                aside={searching ? <Badge numeric>{section.nodes.length}</Badge> : undefined}
              >
                {/* The tier's meaning, once per section — the label says
                    *which* tier, this says what makes something belong to
                    it. Hidden while searching: a filtered palette is a
                    lookup, not a lesson. */}
                {!searching && section.category.description ? (
                  <p className="palette-note">{section.category.description}</p>
                ) : null}
                {section.nodes.map((definition) => (
                  <PaletteItem
                    key={definition.id}
                    definition={definition}
                    disabled={isAtLimit(workbench, definition)}
                    onActivate={() => add(definition)}
                  />
                ))}
              </PanelSection>
            ))}
          </>
        ) : null}

        {searching && matchCount > 0 ? (
          <div className="palette-footnote">
            <span>
              {matchCount} {matchCount === 1 ? 'node' : 'nodes'} match &ldquo;{query}&rdquo;
            </span>
            <Button size="sm" variant="ghost" onClick={() => setQuery('')}>
              Show all
            </Button>
          </div>
        ) : null}
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
  const scoped = definition.scope === 'workflow';
  return (
    <button
      type="button"
      className={clsx(
        'palette-item',
        disabled && 'palette-item--disabled',
        scoped && 'palette-item--scoped',
      )}
      data-accent={definition.accent}
      // Native HTML5 drag rather than pointer events: it gives the OS drag
      // image, the copy cursor and drop-target semantics for free.
      draggable={!disabled}
      aria-disabled={disabled}
      title={
        disabled
          ? `Only one ${definition.label} is allowed`
          : scoped
            ? `${definition.description}\n\nBelongs to this workflow — not available in others.`
            : definition.description
      }
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
        <span className="palette-item__title">
          {definition.label}
          {scoped ? (
            // A per-card mark as well as the section header: search results
            // and a full palette both scroll, and a header three rows up is
            // not an answer to "does this one travel with my workflow?".
            <span className="palette-item__scope" role="img" aria-label="Scoped to this workflow">
              <Icon glyph={Package} size="xs" />
            </span>
          ) : null}
        </span>
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
