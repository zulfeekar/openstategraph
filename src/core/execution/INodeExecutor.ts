import type { IIdentifiable } from '@core/kernel/Registry';
import type { Result } from '@core/kernel/Result';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeId, NodeTypeId } from '@core/model/contracts/node';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import type { ToolSpec, TokenUsage } from '@core/providers/ILLMProvider';

/** Values produced by a node, keyed by the output port they leave on. */
export type PortOutputs = Record<string, unknown>;

/**
 * Reserved key for a value the card should display but no port carries.
 *
 * Sink nodes have no output ports, so without this the engine would have
 * nothing to show on the card that exists precisely to show something.
 * The engine strips it before threading values to downstream inputs.
 */
export const DISPLAY_KEY = '$display';

/**
 * A callable tool, as it travels along a link.
 *
 * Tool nodes don't produce data — they produce *capability*. Emitting a
 * handle on an output port means the ordinary dataflow carries tools to the
 * agent, so the scheduler needs no special case for them and a new tool
 * type is wired up by dragging a link.
 */
export interface ToolHandle {
  readonly nodeId: NodeId;
  readonly spec: ToolSpec;
}

export const isToolHandle = (value: unknown): value is ToolHandle =>
  typeof value === 'object' &&
  value !== null &&
  'nodeId' in value &&
  'spec' in value &&
  typeof (value as ToolHandle).spec?.name === 'string';

/** Everything an executor may read or do during a run. */
export interface ExecutionContext {
  readonly node: AbstractNodeModel;
  readonly workflow: WorkflowModel;
  readonly providers: ProviderRegistry;
  readonly signal: AbortSignal;

  /** Sole value on an input port, or undefined when unconnected. */
  input<T = unknown>(portId: string): T | undefined;
  /** All values on an input port — for ports that accept many links. */
  inputs<T = unknown>(portId: string): readonly T[];
  /** Tool handles arriving on an input port. */
  toolsOn(portId: string): readonly ToolHandle[];

  /** Runs a tool that arrived on one of this node's ports. */
  invokeTool(handle: ToolHandle, args: Record<string, unknown>): Promise<Result<string, string>>;

  /** Appends a line to this node's run log. */
  log(message: string): void;
  /** Attributes token spend to this node and the run total. */
  reportUsage(usage: TokenUsage): void;
}

/**
 * Per-node-type run behaviour.
 *
 * Registered against a node type id, which keeps the engine ignorant of
 * what any particular node actually does — adding a node type means adding
 * an executor, never editing the scheduler.
 */
export interface INodeExecutor extends IIdentifiable {
  /** The node type this executor handles. */
  readonly id: NodeTypeId;
  execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>>;
}

/**
 * Implemented by node types that can be called *by* an agent rather than
 * run in sequence. Kept separate from `INodeExecutor` so a node opts into
 * being a tool without every executor carrying unused methods.
 */
export interface IToolExecutor {
  /** The schema advertised to the model. */
  describeTool(node: AbstractNodeModel): ToolSpec;
  /** Performs the call and returns a string result for the transcript. */
  invokeTool(
    node: AbstractNodeModel,
    args: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Result<string, string>>;
}

export const isToolExecutor = (
  executor: INodeExecutor,
): executor is INodeExecutor & IToolExecutor =>
  typeof (executor as Partial<IToolExecutor>).describeTool === 'function';
