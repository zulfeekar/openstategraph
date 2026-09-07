import { DisposableStore, type Unsubscribe } from '@core/kernel/Disposable';
import { CommandStack } from '@core/commands/CommandStack';
import type { CommandContext } from '@core/commands/ICommand';
import { MountEditScope } from '@core/commands/editScope';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { ConnectionValidator } from '@core/validation/ConnectionValidator';
import type { WorkflowValidator } from '@core/validation/WorkflowValidator';
import type { WorkflowSerializer } from '@core/serialization/WorkflowSerializer';
import { ClipboardService } from './ClipboardService';
import { SelectionModel } from './SelectionModel';
import { ClipboardController } from './ClipboardController';
import { DocumentController } from './DocumentController';
import { EdgeEditor } from './EdgeEditor';
import { GroupingController } from './GroupingController';
import { HistoryController } from './HistoryController';
import { NodeEditor } from './NodeEditor';
import { SelectionActions } from './SelectionActions';
import type {
  EditingContext,
  IClipboardController,
  IDocumentController,
  IEdgeEditor,
  IGroupingController,
  IHistoryController,
  INodeEditor,
  ISelectionActions,
} from './contracts';

export interface WorkflowControllerDeps {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
  readonly connectionValidator: ConnectionValidator;
  readonly workflowValidator: WorkflowValidator;
  readonly serializer: WorkflowSerializer;
}

/**
 * The editor's composition root.
 *
 * It wires the editing collaborators together and owns the one concern none of
 * them can: keeping selection valid as the graph changes. It **implements no
 * editing operation itself** — every gesture lives on a collaborator, reached as
 * `controller.nodes.add(...)`, `controller.history.undo()` and so on.
 *
 * That is the point of the shape. This class was 41 public members mixing seven
 * responsibilities, which meant the inspector, the topbar and every canvas
 * feature each imported the whole editor to use one part of it. It is
 * deliberately *not* a façade that forwards those 41 methods — a forwarding
 * façade is the same god class with an extra layer, and it would leave every
 * consumer still depending on everything.
 *
 * Ten public members, one reason to change: which collaborators exist.
 *
 * The rule that made all of this possible is unchanged — every mutation goes
 * through the command stack, which is what makes undo generic, keeps the React
 * tree free of graph logic, and means a shortcut, a menu and a future scripting
 * API drive one code path rather than three.
 */
export class WorkflowController {
  readonly model: WorkflowModel;
  /** Selection *state*. The gestures that act on it are `selectionActions`. */
  readonly selection = new SelectionModel();

  readonly nodes: INodeEditor;
  readonly edges: IEdgeEditor;
  readonly grouping: IGroupingController;
  readonly clipboard: IClipboardController;
  readonly history: IHistoryController;
  readonly document: IDocumentController;
  readonly selectionActions: ISelectionActions;

  private readonly commands: CommandStack;
  private readonly disposables = new DisposableStore();

  constructor(deps: WorkflowControllerDeps) {
    this.model = deps.model;

    // Constructed here and handed to two collaborators: the stack asks it
    // before running anything, and `document` is what moves it in and out of
    // an instance (ticket 42). Not an eleventh public member — the scope is
    // machinery, and "which document is this" already belongs to `document`.
    const editScope = new MountEditScope();
    // `mounts` is a getter, not a value: the context object is built once and
    // the instance being displayed changes on every load. Reading through the
    // scope keeps one holder of that fact rather than two that can disagree.
    const ctx: CommandContext = {
      model: deps.model,
      registry: deps.registry,
      editScope,
      get mounts() {
        return editScope.mounts;
      },
    };
    this.commands = new CommandStack(ctx);

    const editing: EditingContext = {
      model: deps.model,
      registry: deps.registry,
      commands: this.commands,
    };

    // Construction order follows the dependency arrows, which run one way:
    // grouping <- nodes <- selectionActions <- clipboard. No cycles.
    this.grouping = new GroupingController(editing, this.selection);
    this.nodes = new NodeEditor(editing, this.selection, this.grouping);
    this.selectionActions = new SelectionActions(editing, this.selection, this.nodes);
    this.clipboard = new ClipboardController(
      editing,
      new ClipboardService(deps.model, deps.registry),
      this.selection,
      this.selectionActions,
      this.grouping,
    );
    this.edges = new EdgeEditor(editing, deps.connectionValidator);
    this.history = new HistoryController(this.commands);
    this.document = new DocumentController(
      deps.model,
      this.commands,
      this.selection,
      deps.serializer,
      deps.workflowValidator,
      editScope,
    );

    // Selection outlives the things it points at — a delete, an undo of an add,
    // or an import all invalidate ids. Pruning centrally is why no caller has
    // to remember to do it, and it is the one behaviour that belongs here
    // rather than on a collaborator: it spans all of them.
    this.disposables.addFn(this.model.on('node:removed', () => this.pruneSelection()));
    this.disposables.addFn(this.model.on('edge:removed', () => this.pruneSelection()));
    this.disposables.addFn(this.model.on('workflow:reset', () => this.selection.clear()));
  }

  /**
   * Fires on any change that could affect derived UI state — the toolbar's
   * enablement, the inspector's contents, the diagnostics count.
   */
  onChange(handler: () => void): Unsubscribe {
    const store = new DisposableStore();
    store.addFn(this.model.onAny(() => handler()));
    store.addFn(this.selection.on(() => handler()));
    store.addFn(this.commands.on('changed', () => handler()));
    return () => store.dispose();
  }

  dispose(): void {
    this.disposables.dispose();
    this.commands.dispose();
    this.selection.dispose();
  }

  private pruneSelection(): void {
    this.selection.prune(
      (id) => this.model.hasNode(id),
      (id) => this.model.edge(id) != null,
    );
  }
}
