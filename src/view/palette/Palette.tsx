import { useMemo, useState, useSyncExternalStore } from 'react';
import clsx from 'clsx';
import { AlertTriangle, Package, RefreshCw, Search, X } from 'lucide-react';
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
import { capabilityWarnings, onCapabilityWarningsChange } from '@app/pluginNodes';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import { resolveIcon } from '@view/icons/iconRegistry';
import { type IAssemblyDefinition } from '@nodes/assemblies';
import {
  HIDDEN_PACKAGE_MARK,
  HIDDEN_PACKAGE_NOTE,
  workflowCatalogue,
} from '@core/runtime/workflowCatalogue';
import { mountAncestry } from '@core/runtime/mountAncestry';
import { assembliesFor, sectionSurvivesSearch } from './paletteSearch';
import { packageRows, type PackageRow } from './packageRows';
import { encodePackageDrag, PALETTE_PACKAGE_DRAG_TYPE } from './packageDrag';
import { SUBGRAPH_TYPE } from '@nodes/compose/SubgraphNode';
import './Palette.css';

/** Custom drag type, so canvas drops can tell a palette drag from a file. */
export const PALETTE_DRAG_TYPE = 'application/x-openstategraph-node-type';

/**
 * A palette drag carrying an **assembly** rather than one node type.
 *
 * A separate MIME on purpose: the canvas has to know before the drop whether
 * it is about to add one node or insert a wired fragment, and overloading the
 * node-type payload would make every reader of it check what kind of id it
 * had. An assembly is not a node type and must never look like one — it is
 * absent from the registry, from `port_specs.json` and from the architect's
 * grammar, which is what keeps it from becoming the `Loop` node three tickets
 * have refused (ticket 21).
 */
export const PALETTE_ASSEMBLY_DRAG_TYPE = 'application/x-openstategraph-assembly';

interface PaletteProps {
  onNotify: (message: string) => void;
}

/**
 * **Drag aims; the keyboard places; a mouse click does neither.**
 *
 * `say-it-on-the-surface` 04, superseding half of `canvas-feels-right` 01.
 * That ticket kept click-to-place on two grounds: an e2e test covered it, and
 * pointer-only placement is an accessibility regression. The second ground is
 * sound and is honoured here. The first was never a reason — a test covers
 * behaviour, it does not argue for it — and the ticket's own requirement, that
 * "the palette says so", never shipped, so click-to-place remained undocumented
 * behaviour a user could only discover by accident.
 *
 * Two facts settled it. The owner hit the same edge twice, months apart, having
 * been told nothing; and the palette already disagreed with itself —
 * `AssemblyItem` had `onDragStart` and no `onClick`, so the Revision loop was
 * drag-only while every atom placed on click. One of the three row kinds
 * already behaved the way the complaint asked for, and nobody had designed
 * that.
 *
 * So the rule is one rule, and every row obeys it:
 *
 * - **Pointer** — drag to the spot you want. A click selects nothing and
 *   places nothing.
 * - **Keyboard** — Tab to a row, press Enter or Space. It lands in the centre
 *   of the view, cascading if that point is taken.
 *
 * `preventDefault` on the keydown matters: a `<button>` synthesises a click
 * from Enter, so without it the placement would fire twice — once here and
 * once through a click handler that no longer exists, or, worse, silently
 * double-place if one were ever restored.
 */
function onKeyboardActivate(activate: () => void) {
  return (event: { key: string; preventDefault: () => void }) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    activate();
  };
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
          // A section survives if it still holds a matching **node type** or a
          // matching **assembly**. Nodes alone was the test, and it made the
          // Revision loop unreachable by search: no node type matches "loop"
          // or "revise", so the whole `compose` section was dropped before its
          // assemblies were ever consulted — and those two words are exactly
          // the ones somebody looking for a revision loop types.
          .filter((section) => sectionSurvivesSearch(section, query))
      : all;

    const scopedNodes: INodeDefinition[] = [];
    const rest: { category: INodeCategory; nodes: readonly INodeDefinition[] }[] = [];
    for (const section of visible) {
      const app = section.nodes.filter((definition) => definition.scope !== 'workflow');
      for (const definition of section.nodes) {
        if (definition.scope === 'workflow') scopedNodes.push(definition);
      }
      // Assemblies again: a section whose only match is one must survive this
      // second gate too, or the first filter is undone three lines later —
      // which is exactly what kept "loop" returning nothing after the first
      // attempt at this fix.
      if (app.length > 0 || assembliesFor(section.category.id, query).length > 0) {
        rest.push({ ...section, nodes: app });
      }
    }
    return {
      scoped: scopedNodes,
      appSections: rest,
      // Assemblies count too — a search that finds only an assembly must not
      // report "no matches" above the thing it just found.
      matchCount:
        scopedNodes.length +
        rest.reduce((n, s) => n + s.nodes.length + assembliesFor(s.category.id, query).length, 0),
    };
    // Recomputed on every render this component takes, including the ones
    // `useSyncExternalStore` above forces — `workbench.registry` itself
    // never changes identity, so it cannot be a dependency that triggers this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workbench, query, workbench.registry.nodeTypes.size]);

  const searching = query.trim().length > 0;

  // The saved packages, subscribed exactly as the registry is above — the
  // catalogue is live (a package saved two minutes ago must be draggable), and
  // it is a different store from the node-type registry, so it needs its own
  // subscription rather than a second reason for that one to fire.
  const catalogue = useSyncExternalStore(
    (onStoreChange) => workflowCatalogue.onChange(onStoreChange),
    // Safe as a snapshot: `WorkflowCatalogue.set` replaces the array only when
    // the slug list actually changed, so the reference is stable between
    // changes and this cannot loop.
    () => workflowCatalogue.list(),
  );

  // `mountAncestry()` is a **reader**, asked here every render rather than
  // remembered — the same decision, for the same reason, as the mount field's
  // `validate` (ticket 42). A stored trail would go stale on a drill, a pop or
  // a load, and a stale trail greys out a package that is perfectly legal to
  // mount, which is the one failure this must not have. Deliberately not
  // memoised for that reason: the trail is not among the values a dependency
  // array could watch, and a memo keyed on the two that are would hold a
  // refusal from the workflow before this one. It is a filter over a handful
  // of rows.
  const packages = packageRows(catalogue, mountAncestry(), query);

  // The capability-warning channel, subscribed the same way the registry is:
  // warnings arrive after a load or a Refresh, long after this first painted.
  const warnings = useSyncExternalStore(onCapabilityWarningsChange, capabilityWarnings);

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

  // A click has no drop point, so the canvas has to choose one: the centre of
  // what the user is currently looking at. That much was already right.
  //
  // The cascade is the fix for what happened on the *second* click — three
  // clicks put three nodes at exactly (314, 501), one visible card with two
  // buried underneath and nothing to say so (canvas-feels-right ticket 01).
  // Someone who clicks again because the first click looked like it did
  // nothing ends up owning the node they think they failed to create.
  //
  // Only the click path needs this. A **drag** carries the point the pointer
  // was released on, and placing the node exactly there is its whole contract.
  const add = (definition: INodeDefinition) => {
    const preferred = paper?.viewport.center ?? { x: 120, y: 120 };
    const outcome = controller.nodes.add(definition.id, preferred, { avoidOverlap: true });
    if (!outcome.ok && outcome.message) onNotify(outcome.message);
  };

  // The click half of a package row, so it behaves like every other row in
  // this panel. Same call the canvas's drop makes, differing only in where —
  // a click names no point, so it cascades like the one above.
  const mount = (row: PackageRow) => {
    if (row.refusal) return;
    const preferred = paper?.viewport.center ?? { x: 120, y: 120 };
    const outcome = controller.nodes.add(SUBGRAPH_TYPE, preferred, {
      avoidOverlap: true,
      data: { workflow: row.slug },
    });
    if (!outcome.ok && outcome.message) onNotify(outcome.message);
  };

  // The keyboard half of an assembly, using the same command the canvas's drop
  // uses (`clipboard.insertFragment`) — a fragment, never a node type, because
  // an assembly is an arrangement of several nodes and the edges between them.
  // A keystroke names no point, so it lands where the other two land.
  const drop = (assembly: IAssemblyDefinition) => {
    const preferred = paper?.viewport.center ?? { x: 120, y: 120 };
    const outcome = controller.clipboard.insertFragment(assembly.fragment, preferred);
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
        {/* **The palette says how a component gets onto the canvas.**
            `canvas-feels-right` 01 resolved that click-to-place would stay
            "and the palette says so"; the mechanical half shipped and this
            half did not, so the rule lived only in a source comment and every
            user met it by accident. One line, in the header rather than under
            a section, because it is true of every row below it — and hidden
            while searching, for the same reason the sections' own notes are:
            a filtered palette is a lookup, not a first visit. */}
        {!searching ? (
          <p className="palette-howto">
            Drag any of these onto the canvas to place it where you want it. From the keyboard:
            Tab to one and press Enter.
          </p>
        ) : null}
      </PanelHeader>

      <PanelBody>
        {/* The half-authored error, and everything else discovery could not
            deliver (register PK-06). Shown here rather than as a toast because
            it is a *standing* condition — a Python tool with no editor card is
            still cardless after a toast fades, and the developer who needs to
            read it may not have been looking when it appeared. Hidden while
            searching: a filtered palette is a lookup. */}
        {!searching && warnings.length > 0 ? (
          <div className="palette-warnings" role="status">
            <p className="palette-warnings__title">
              <Icon glyph={AlertTriangle} size="xs" />
              {warnings.length === 1
                ? 'A capability needs attention'
                : `${warnings.length} capabilities need attention`}
            </p>
            <ul className="palette-warnings__list">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {/* Packages count as matches. Assemblies taught this lesson once
            already: a section filtered out before its own items are consulted
            makes the palette report "no matches" directly above the thing it
            just found. */}
        {matchCount === 0 && packages.length === 0 ? (
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

        {/* Packages — the reusable definitions a mount points at, one drag
            each (ticket 11). Above "Always available" and outside it, because
            that label promises "in every workflow" and this list is the user's
            own: it grows when they save one and shrinks when they delete one.
            Hidden entirely when a search matches none of them; a section that
            ignored the filter would read as a bug.

            Open, unlike the Examples shelf, and the difference is the whole of
            that shelf's reasoning: it is closed by default because a fresh
            install otherwise showed one empty section of your own work above
            twenty-three workflows of somebody else's. Every row here is the
            user's own, and on a fresh install there are none — so the argument
            for collapsing does not reach this list. */}
        {packages.length > 0 || !searching ? (
          <PanelSection
            className="palette-section--packages"
            heading="Packages"
            aside={packages.length > 0 ? <Badge numeric>{packages.length}</Badge> : undefined}
          >
            {!searching ? (
              <p className="palette-note">
                Your saved workflows, each mounted as one isolated step — task in, answer out.
                Mounted <em>by reference</em>: change the package and every mount of it changes.
                {/* The word under each name, said once where the section is
                    introduced (`say-it-on-the-surface` 03). Every row printed
                    its slug in a `<code>` and nothing anywhere told a reader
                    what that string was — and it is the string the mount field
                    asks for, so a reader who cannot connect the two cannot use
                    either surface. */}{' '}
                The name in code type is the <strong>slug</strong>: the package’s folder on the
                backend, and what the mount field asks for.
              </p>
            ) : null}
            {packages.length > 0 ? (
              packages.map((row) => (
                <PackageItem
                  key={row.slug}
                  row={row}
                  onActivate={() => mount(row)}
                  onRefuse={onNotify}
                />
              ))
            ) : (
              <p className="palette-note">
                No saved workflows yet — save one, and it appears here as a node you can drop into
                another.
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
                {/* Assemblies sit in their category beside the node types,
                    because to a reader choosing what to drag they are the
                    same question. They are a different *kind* of item, so
                    they carry their own drag type and their own component. */}
                {assembliesFor(section.category.id, query).map((assembly) => (
                  <AssemblyItem
                    key={assembly.id}
                    assembly={assembly}
                    onActivate={() => drop(assembly)}
                  />
                ))}
              </PanelSection>
            ))}
          </>
        ) : null}

        {searching && matchCount + packages.length > 0 ? (
          <div className="palette-footnote">
            {/* "results", not "nodes". A package is emphatically not a node
                type in this lexicon — it is the definition a mount points at —
                and the count now includes them. */}
            <span>
              {matchCount + packages.length}{' '}
              {matchCount + packages.length === 1 ? 'result' : 'results'} for &ldquo;{query}&rdquo;
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

/**
 * One saved package in the palette — a drag that lands a mount already bound
 * to it, rather than a generic mount you then have to go and configure.
 *
 * Its own component beside `PaletteItem` and `AssemblyItem`, for the reason
 * those two are separate from each other: a package has no node definition, no
 * instance cap and no scope, and it carries a refusal none of them has. Sharing
 * one widened component would give all three a branch each for the other two.
 *
 * **A refused row is greyed, not hidden** — ticket 42's half that a native
 * `<datalist>` could not do. The gesture is unavailable, and the reason is the
 * compiler's own sentence, which is the same one the mount field shows and the
 * same one a failed compile would have printed later.
 *
 * **A hidden package is marked, not greyed** (ticket 57) — a different fact
 * about a different thing, and the two are independent: `concierge` is hidden
 * on disk and is a perfectly legal mount from anywhere but inside itself.
 * Marking it is what the editor surface promised to do with the flag it asks
 * for; without it, a package no customer will ever be offered looked exactly
 * like one they will.
 */
function PackageItem({
  row,
  onActivate,
  onRefuse,
}: {
  row: PackageRow;
  onActivate: () => void;
  onRefuse: (message: string) => void;
}) {
  const refused = row.refusal != null;
  // **Said once, on the gesture that was refused.** The row looked disabled and
  // `button.disabled` was `false`, so dragging it was cancelled in silence: the
  // canvas panned and nothing happened, which reads as a broken palette rather
  // than as a rule (consistency-sweep ticket 10). Not `disabled`, deliberately
  // — a disabled button fires no mouse events, so it would also swallow the
  // hover text, which is the compiler's own sentence and the best thing here.
  const refuse = (event: { preventDefault: () => void }) => {
    event.preventDefault();
    if (row.refusal) onRefuse(row.refusal);
  };
  // Both, when both apply: the refusal is why this gesture will not work, and
  // the note is what the package is. A row can be either, neither or both.
  const hint = row.refusal ?? `Mount ${row.name} — task in, answer out.`;
  return (
    <button
      type="button"
      className={clsx('palette-item', refused && 'palette-item--disabled')}
      data-accent="violet"
      draggable={!refused}
      aria-disabled={refused}
      // The row's own hint only. The hidden note used to be concatenated on
      // here with a `\n\n`, which put the answer to "what does Hidden mean"
      // in the second paragraph of a native tooltip anchored at the pointer —
      // so the word a reader was looking at explained nothing and the sentence
      // arrived somewhere else, a second later, if at all
      // (`say-it-on-the-surface` 05). It now hangs off the mark itself.
      title={hint}
      onDragStart={(event) => {
        if (refused) {
          refuse(event);
          return;
        }
        event.dataTransfer.setData(PALETTE_PACKAGE_DRAG_TYPE, encodePackageDrag(row.slug));
        event.dataTransfer.effectAllowed = 'copy';
      }}
      // A refused row still speaks when clicked — that is not placement, it is
      // the compiler's own sentence, and silencing it would restore
      // `consistency-sweep` 10's "the canvas panned and nothing happened".
      // A row that is *not* refused does nothing on click, like every other
      // row in this palette.
      onClick={(event) => {
        if (refused) refuse(event);
      }}
      onKeyDown={onKeyboardActivate(() => {
        if (refused) {
          if (row.refusal) onRefuse(row.refusal);
          return;
        }
        onActivate();
      })}
    >
      <IconTile glyph={resolveIcon('node-subgraph')} size="md" iconSize="sm" />
      <span className="palette-item__text">
        <span className="palette-item__title">
          {row.name}
          {/* A word, not an icon: "hidden" is a claim about who can see this
              package, and the scoped rows next door already spend the glyph
              vocabulary on provenance. The sentence behind it hangs off the
              mark itself, keyboard-reachable, rather than off the row. */}
          {row.hidden ? (
            <Badge className="palette-item__mark" explanation={HIDDEN_PACKAGE_NOTE}>
              {HIDDEN_PACKAGE_MARK}
            </Badge>
          ) : null}
        </span>
        <span className="palette-item__description">
          {/* The slug, because it is what the document stores and what a
              developer types into the mount field — the name alone leaves a
              reader unable to connect this row to `workflows/<slug>/`. */}
          {refused ? row.refusal : <code className="palette-item__slug">{row.slug}</code>}
        </span>
      </span>
    </button>
  );
}

/**
 * One assembly in the palette.
 *
 * Deliberately not `PaletteItem` with a widened prop: an assembly has no
 * instance cap, no scope and no node id, so half of that component's
 * behaviour would be dead here and the other half would need a branch.
 */
function AssemblyItem({
  assembly,
  onActivate,
}: {
  assembly: IAssemblyDefinition;
  onActivate: () => void;
}) {
  return (
    <button
      type="button"
      className="palette-item"
      data-accent="violet"
      draggable
      title={assembly.description}
      onDragStart={(event) => {
        event.dataTransfer.setData(PALETTE_ASSEMBLY_DRAG_TYPE, assembly.id);
        event.dataTransfer.effectAllowed = 'copy';
      }}
      // This row had **no** activation handler at all until
      // `say-it-on-the-surface` 04 — it was drag-only by omission, not by
      // design, which is how the palette came to hold two placement rules. It
      // now obeys the same one as every other row, keyboard included.
      onKeyDown={onKeyboardActivate(onActivate)}
    >
      <IconTile glyph={resolveIcon(assembly.iconId)} size="md" iconSize="sm" />
      <span className="palette-item__text">
        <span className="palette-item__title">{assembly.label}</span>
        <span className="palette-item__description">{assembly.description}</span>
      </span>
    </button>
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
      // No `onClick`: a click aims at nothing, so it places nothing. The
      // element stays a `<button>` because that is what makes it reachable by
      // Tab and what gives Enter and Space their meaning — the keyboard path
      // the accessibility argument was always about.
      onKeyDown={onKeyboardActivate(() => {
        if (!disabled) onActivate();
      })}
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
