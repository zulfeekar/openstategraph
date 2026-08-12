import { dia, shapes } from '@joint/core';
import { DisposableStore, type IDisposable } from '@core/kernel/Disposable';
import { Registry } from '@core/kernel/Registry';
import { CANVAS } from '@design/tokens';
import type { Rect } from '@core/kernel/geometry';
import type { WorkflowController } from '@controller/WorkflowController';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { FlowDirection } from '@core/model/contracts/ports';
import { JointGraphAdapter } from './JointGraphAdapter';
import { Viewport } from './Viewport';
import { AutoLayout } from './AutoLayout';
import { CELL_NAMESPACE, NodeMountRegistry, defineHtmlNodeView, FlowLink } from './shapes/HtmlNode';
import { LINK_CONNECTOR, LINK_ROUTER } from './links/edgeDecoration';
import {
  CLICK_THRESHOLD,
  MAGNET_THRESHOLD,
  MOVE_THRESHOLD,
  snapRadiusAtZoom,
} from './interactionThresholds';
import { RunFollower } from './follow/RunFollower';
import type { IPaperFeature, PaperFeatureContext } from './features/IPaperFeature';
import { PanZoomFeature } from './features/PanZoomFeature';
import { FrameOnLoadFeature } from './features/FrameOnLoadFeature';
import { SelectionFeature } from './features/SelectionFeature';
import { DragCommitFeature } from './features/DragCommitFeature';
import { SnaplinesFeature } from './features/SnaplinesFeature';
import { LinkToolsFeature } from './features/LinkToolsFeature';
import { WaypointCommitFeature } from './features/WaypointCommitFeature';
import { KeyboardFeature, createDefaultShortcuts, type Shortcut } from './features/KeyboardFeature';
import {
  ConnectionFeature,
  createConnectionValidator,
  validateMagnet,
} from './features/ConnectionFeature';

/**
 * The dot grid. `scaleFactor: 2` keeps the dots at a readable density as the
 * canvas zooms out instead of collapsing into a grey wash.
 */
const GRID_OPTIONS: dia.Paper.GridOptions = {
  name: 'dot',
  args: [{ color: 'var(--color-canvas-grid-dot)', thickness: 1.5, scaleFactor: 2 }],
};

export interface PaperControllerOptions {
  /** Extra shortcuts contributed by the shell (theme, panels, export). */
  readonly shortcuts?: readonly Shortcut[];
  /** Additional features, installed after the defaults. */
  readonly features?: readonly IPaperFeature[];
  readonly showGrid?: boolean;
  /** Which way the canvas reads when the paper is built. */
  readonly flowDirection?: FlowDirection;
  /**
   * Whether the camera follows a run from the moment the paper exists.
   * The person's preference (`PreferencesStore.followRun`), passed in the
   * same way `flowDirection` is — the canvas layer reads no storage of its
   * own.
   */
  readonly followRun?: boolean;
}

/**
 * Owns the JointJS paper and everything installed on it.
 *
 * The composition root for the canvas: it builds the graph, the paper, the
 * model→graph adapter and the viewport, then installs behaviour as a list of
 * features. Nothing in here knows about a specific node type, and nothing
 * outside needs to know JointJS exists — the React shell talks to this
 * object's small API.
 */
export class PaperController implements IDisposable {
  readonly graph: dia.Graph;
  readonly paper: dia.Paper;
  readonly adapter: JointGraphAdapter;
  readonly viewport: Viewport;
  readonly autoLayout: AutoLayout;
  /** Ticket 08 — the camera's run-following mode. A collaborator, not methods. */
  readonly follower: RunFollower;
  readonly mounts = new NodeMountRegistry();
  readonly features = new Registry<IPaperFeature>('paperFeatures');

  /** JointJS-owned mount node inside the React container. */
  private readonly surface: HTMLDivElement;

  private readonly disposables = new DisposableStore();
  private readonly keyboard: KeyboardFeature;
  private readonly connection = new ConnectionFeature();
  private gridVisible: boolean;

  constructor(
    private readonly container: HTMLElement,
    private readonly controller: WorkflowController,
    registry: ModelRegistry,
    options: PaperControllerOptions = {},
  ) {
    this.gridVisible = options.showGrid ?? true;

    // `shapes` is included in the namespace so a graph containing standard
    // shapes (from a hand-written import) still deserializes.
    this.graph = new dia.Graph({}, { cellNamespace: { ...shapes, ...CELL_NAMESPACE } });

    // The paper gets a div of its own, created here and never touched by
    // React. `paper.remove()` deletes whatever element the paper was given —
    // handing it the React-rendered container would rip that node out of the
    // tree on teardown, and React would go on rendering into a detached DOM.
    this.surface = document.createElement('div');
    this.surface.className = 'canvas-surface';
    container.appendChild(this.surface);

    this.paper = new dia.Paper({
      el: this.surface,
      model: this.graph,
      // The paper fills its container and the canvas is transformed, rather
      // than the paper being oversized and scrolled.
      width: '100%',
      height: '100%',
      background: { color: 'transparent' },
      gridSize: CANVAS.gridSize,
      drawGrid: this.gridVisible ? GRID_OPTIONS : false,

      cellViewNamespace: { ...shapes, ...CELL_NAMESPACE },
      elementView: defineHtmlNodeView(this.mounts),

      // ---- interaction ----
      // Async rendering keeps a large graph from blocking the first paint.
      async: true,
      sorting: dia.Paper.sorting.APPROX,
      // Clicks land as clicks rather than 1px drags on a trackpad. The units
      // are not the same for all three — see `interactionThresholds.ts`, which
      // is where that cost a working connection gesture.
      clickThreshold: CLICK_THRESHOLD,
      moveThreshold: MOVE_THRESHOLD,
      magnetThreshold: MAGNET_THRESHOLD,
      // A dropped link lands on the nearest *legal* port rather than only on
      // the one under the pointer. See `interactionThresholds.ts` for why a
      // bigger hit circle is not the same fix, and why the radius is kept in
      // step with the zoom below.
      snapLinks: { radius: snapRadiusAtZoom(1) },
      preventDefaultViewAction: false,
      // Selection needs the native pointer sequence on blank canvas.
      preventDefaultBlankAction: false,
      snapLabels: true,

      // ---- links ----
      defaultLink: () => new FlowLink(),
      defaultConnector: LINK_CONNECTOR,
      defaultRouter: LINK_ROUTER,
      defaultAnchor: { name: 'center' },
      defaultConnectionPoint: { name: 'boundary', args: { offset: 2 } },
      // A half-finished link is never a valid document state.
      linkPinning: false,
      // `markAvailable` is deliberately *not* set. It was, with a
      // `magnetAvailability: { name: 'addClass', … }` highlighter, and it put
      // no class on any element in the document — `dia.HighlighterView` is an
      // mvc view, so `options.className` became the class of the highlighter's
      // own detached `<g>`. `ConnectionFeature` marks the legal targets itself,
      // from the same `canConnect` that governs the drop; the measurement is
      // recorded in `features/portAffordance.ts`.
      validateMagnet,
      validateConnection: createConnectionValidator((source, target) =>
        controller.edges.canConnect(source, target),
      ),

      // ---- embedding ----
      // JointJS moves children with their parent, but membership itself is
      // decided by the controller on drop, so the model stays authoritative.
      embeddingMode: false,

      // ---- highlighting ----
      // Every built-in highlight is off: the canvas expresses selection,
      // availability and the run through its own classes and stylesheet, so a
      // second, JointJS-shaped visual vocabulary would only compete with it.
      highlighting: {
        magnetAvailability: false,
        elementAvailability: false,
        default: false,
      },

      // Dragging must not start from a form control inside a card.
      guard: (event) => {
        const target = event.target as HTMLElement | null;
        return Boolean(target?.closest?.('[data-no-drag]'));
      },
    });

    this.adapter = new JointGraphAdapter(
      controller.model,
      this.graph,
      registry,
      options.flowDirection ?? 'horizontal',
    );
    this.viewport = new Viewport(this.paper, container);
    this.autoLayout = new AutoLayout(this.graph, controller);
    this.follower = new RunFollower(
      this.viewport,
      this.graph,
      container,
      options.followRun ?? true,
    );

    // The snap radius is a distance for the *hand*, so it is held constant in
    // screen pixels rather than in the local units JointJS stores it in.
    const syncSnapRadius = (zoom: number) => {
      const options = this.paper.options as { snapLinks?: { radius: number } };
      if (options.snapLinks) options.snapLinks.radius = snapRadiusAtZoom(zoom);
    };
    syncSnapRadius(this.viewport.zoom);
    this.disposables.addFn(this.viewport.onChange(({ zoom }) => syncSnapRadius(zoom)));

    const panZoom = new PanZoomFeature();
    this.keyboard = new KeyboardFeature(createDefaultShortcuts(options.shortcuts ?? []));

    this.installAll([
      panZoom,
      new SelectionFeature(panZoom),
      new DragCommitFeature(),
      new SnaplinesFeature(),
      new FrameOnLoadFeature(),
      this.connection,
      new LinkToolsFeature(),
      new WaypointCommitFeature(),
      this.keyboard,
      ...(options.features ?? []),
    ]);

    // `paper.remove()` takes the surface div with it; the React container it
    // was appended to is left untouched.
    this.disposables.addFn(() => this.paper.remove());
    this.disposables.addFn(() => this.viewport.dispose());
    this.disposables.addFn(() => this.adapter.dispose());
    this.disposables.addFn(() => this.follower.dispose());
    this.disposables.addFn(() => this.mounts.clear());
  }

  get shortcuts(): readonly Shortcut[] {
    return this.keyboard.bindings;
  }

  get isGridVisible(): boolean {
    return this.gridVisible;
  }

  setGridVisible(visible: boolean): void {
    if (this.gridVisible === visible) return;
    this.gridVisible = visible;
    this.paper.setGrid(visible ? GRID_OPTIONS : false);
  }

  /** Surfaces connection rejections so the shell can toast them. */
  observeConnectionRejections(handler: (reason: string | null) => void): void {
    this.connection.observeRejections(handler);
  }

  /** Frames the whole graph. */
  fitToContent(): void {
    this.viewport.fit(this.controller.model.bounds());
  }

  /** Bounding box of everything on the canvas, for framing and export. */
  contentBounds(): Rect | null {
    return this.controller.model.bounds();
  }

  /** Model coordinates at the centre of the current view. */
  viewportCenter(): { x: number; y: number } {
    const rect = this.viewport.visibleRect;
    return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
  }

  /** Converts a drop event's client coordinates into model space. */
  clientToLocal(clientX: number, clientY: number): { x: number; y: number } {
    return this.viewport.clientToLocal(clientX, clientY);
  }

  get element(): HTMLElement {
    return this.container;
  }

  dispose(): void {
    for (const feature of this.features.list()) feature.dispose();
    this.disposables.dispose();
  }

  private installAll(features: readonly IPaperFeature[]): void {
    const ctx: PaperFeatureContext = {
      paper: this.paper,
      graph: this.graph,
      adapter: this.adapter,
      controller: this.controller,
      viewport: this.viewport,
      container: this.container,
    };
    for (const feature of features) {
      this.features.register(feature);
      feature.install(ctx);
    }
  }
}
