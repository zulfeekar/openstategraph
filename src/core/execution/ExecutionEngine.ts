import { Registry } from '@core/kernel/Registry';
import { EventBus } from '@core/kernel/EventBus';
import type { Unsubscribe } from '@core/kernel/Disposable';
import { Err, Ok, type Result } from '@core/kernel/Result';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { NodeId } from '@core/model/contracts/node';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import { ZERO_USAGE, addUsage, type TokenUsage } from '@core/providers/ILLMProvider';
import type { WorkflowValidator } from '@core/validation/WorkflowValidator';
import {
  DISPLAY_KEY,
  isToolExecutor,
  isToolHandle,
  type ExecutionContext,
  type INodeExecutor,
  type PortOutputs,
  type ToolHandle,
} from './INodeExecutor';

export interface RunEvents extends Record<string, unknown> {
  'run:start': { runId: string };
  'run:node': { nodeId: NodeId; status: 'running' | 'success' | 'error' | 'skipped' };
  'run:usage': { usage: TokenUsage };
  'run:log': { nodeId: NodeId; message: string };
  'run:finish': { runId: string; ok: boolean; usage: TokenUsage; error?: string };
}

export interface RunOutcome {
  readonly ok: boolean;
  readonly usage: TokenUsage;
  readonly error?: string;
}

/**
 * Runs a workflow.
 *
 * A sequential topological walk rather than a parallel one, on purpose: the
 * point of the canvas is that a user can *watch* their graph execute, and
 * nodes lighting up one at a time is legible where four at once is not.
 * Parallelising independent branches is a change to `run` alone — nothing
 * else depends on the ordering.
 *
 * The engine owns no node-specific knowledge. It resolves an executor per
 * node type from the registry, threads outputs to inputs along the model's
 * edges, and writes status back to the model so the canvas can render it.
 */
export class ExecutionEngine {
  readonly executors = new Registry<INodeExecutor>('nodeExecutors');

  private readonly bus = new EventBus<RunEvents>();
  private controller: AbortController | null = null;
  private runCounter = 0;

  constructor(
    private readonly workflow: WorkflowModel,
    private readonly providers: ProviderRegistry,
    private readonly validator: WorkflowValidator,
  ) {}

  get isRunning(): boolean {
    return this.controller != null;
  }

  /** Requests cancellation; the in-flight node settles before stopping. */
  cancel(): void {
    this.controller?.abort();
  }

  async run(): Promise<RunOutcome> {
    if (this.controller) return { ok: false, usage: ZERO_USAGE, error: 'A run is already active' };

    const blocking = this.validator.validate().filter((d) => d.severity === 'error');
    if (blocking.length > 0) {
      // `acyclicGraphRule`'s `error`-severity `cycle` code means the escape
      // check found none — every node in the loop only ever feeds back into
      // it. That is a real bug on *any* engine, backend included, so "try
      // Chat instead" would be actively wrong advice here; an escapable
      // revise loop (a `pass` that exits it) is a `warning`, not an `error`,
      // and never reaches this branch — see the `cycle` check below for that
      // case instead.
      const first = blocking.some((d) => d.code === 'cycle')
        ? 'This graph has a loop with no way out — it can never finish, on this engine or the backend.'
        : (blocking[0]?.message ?? 'Workflow is not runnable');
      return this.rejectBeforeStart(first);
    }

    const { order, cycle } = this.workflow.topologicalOrder();
    if (cycle && cycle.length > 0) {
      // The common path for an *escapable* loop (a revise loop with a `pass`
      // that exits it) — `acyclicGraphRule` reports that shape as a
      // `warning`, not a blocking `error`, so it never reaches the check
      // above. This engine still cannot preview a real cycle regardless of
      // severity, so it is caught here instead, with the same message.
      return this.rejectBeforeStart(
        'This graph has a loop (e.g. a grader revise step) that the canvas preview cannot run — try Chat instead.',
      );
    }

    const runId = `run-${++this.runCounter}`;
    this.controller = new AbortController();
    const signal = this.controller.signal;

    this.resetRuntime();
    this.bus.emit('run:start', { runId });

    /** Output values by `nodeId/portId`, consumed by downstream inputs. */
    const values = new Map<string, unknown>();
    let total = ZERO_USAGE;
    let failure: string | undefined;

    try {
      for (const nodeId of order) {
        if (signal.aborted) {
          failure = 'Run cancelled';
          break;
        }

        const node = this.workflow.node(nodeId);
        if (!node) continue;

        const executor = this.executors.get(node.type);
        if (!executor) {
          // A node with no executor is inert, not fatal — the graph may
          // legitimately contain annotation-like nodes.
          this.markNode(node, 'idle');
          this.bus.emit('run:node', { nodeId, status: 'skipped' });
          continue;
        }

        this.markNode(node, 'running');
        this.bus.emit('run:node', { nodeId, status: 'running' });

        const started = performance.now();
        const ctx = this.contextFor(node, values, signal, (usage) => {
          total = addUsage(total, usage);
          this.bus.emit('run:usage', { usage: total });
        });

        let outcome: Result<PortOutputs, string>;
        try {
          outcome = await executor.execute(ctx);
        } catch (error) {
          // An executor that throws is a bug, but it must not take the run
          // down without attributing the failure to a node.
          outcome = Err(error instanceof Error ? error.message : String(error));
        }

        const durationMs = Math.round(performance.now() - started);

        if (!outcome.ok) {
          this.workflow.setNodeRuntime(nodeId, {
            status: 'error',
            error: outcome.error,
            durationMs,
          });
          this.bus.emit('run:node', { nodeId, status: 'error' });
          failure = outcome.error;
          break;
        }

        for (const [portId, value] of Object.entries(outcome.value)) {
          // The display key is presentation, not dataflow — it must never
          // be visible to a downstream input.
          if (portId === DISPLAY_KEY) continue;
          values.set(`${nodeId}/${portId}`, value);
        }

        const primary = node.primaryOutput;
        this.workflow.setNodeRuntime(nodeId, {
          status: 'success',
          error: null,
          durationMs,
          output: outcome.value[DISPLAY_KEY] ?? (primary ? outcome.value[primary.id] : null),
        });
        this.bus.emit('run:node', { nodeId, status: 'success' });
      }
    } finally {
      this.controller = null;
    }

    const ok = failure == null;
    this.bus.emit('run:finish', {
      runId,
      ok,
      usage: total,
      ...(failure ? { error: failure } : {}),
    });
    return { ok, usage: total, ...(failure ? { error: failure } : {}) };
  }

  /**
   * A run that never gets to start still needs to *say so* — found live: a
   * pre-flight rejection (a blocking diagnostic, a loop) used to bypass the
   * event bus entirely, so the toolbar's own `run:finish` listener (which
   * already turns a failure into a toast) never fired, and pressing "Run" on
   * an unrunnable graph produced no observable feedback at all.
   */
  private rejectBeforeStart(error: string): RunOutcome {
    const runId = `run-${++this.runCounter}`;
    this.bus.emit('run:start', { runId });
    this.bus.emit('run:finish', { runId, ok: false, usage: ZERO_USAGE, error });
    return { ok: false, usage: ZERO_USAGE, error };
  }

  on<K extends keyof RunEvents & string>(
    type: K,
    handler: (payload: RunEvents[K]) => void,
  ): Unsubscribe {
    return this.bus.on(type, handler);
  }

  dispose(): void {
    this.cancel();
    this.bus.dispose();
  }

  /* ================================================================ *
   * Internals
   * ================================================================ */

  private resetRuntime(): void {
    this.workflow.transact(() => {
      for (const node of this.workflow.nodes()) {
        this.workflow.setNodeRuntime(node.id, {
          status: 'idle',
          error: null,
          output: null,
          tokens: 0,
          durationMs: null,
          log: [],
        });
      }
    });
  }

  private markNode(node: AbstractNodeModel, status: 'idle' | 'running'): void {
    this.workflow.setNodeRuntime(node.id, { status });
  }

  /**
   * Builds the sandbox a single node executes in.
   *
   * Input resolution walks the model's edges rather than being pushed by
   * upstream nodes, so a node reads exactly what is wired to it at the
   * moment it runs — and an unconnected optional port simply yields
   * `undefined` instead of needing a placeholder.
   */
  private contextFor(
    node: AbstractNodeModel,
    values: Map<string, unknown>,
    signal: AbortSignal,
    onUsage: (usage: TokenUsage) => void,
  ): ExecutionContext {
    const readPort = (portId: string): unknown[] =>
      this.workflow
        .edgesInto({ nodeId: node.id, portId })
        .map((edge) => values.get(`${edge.source.nodeId}/${edge.source.portId}`))
        .filter((value) => value !== undefined);

    const ctx: ExecutionContext = {
      node,
      workflow: this.workflow,
      providers: this.providers,
      signal,

      input: <T>(portId: string) => readPort(portId)[0] as T | undefined,
      inputs: <T>(portId: string) => readPort(portId) as readonly T[],
      toolsOn: (portId: string) => readPort(portId).filter(isToolHandle),

      invokeTool: async (handle: ToolHandle, args: Record<string, unknown>) => {
        const toolNode = this.workflow.node(handle.nodeId);
        if (!toolNode) return Err(`Tool node ${handle.nodeId} is gone`);

        const executor = this.executors.get(toolNode.type);
        if (!executor || !isToolExecutor(executor)) {
          return Err(`${toolNode.title} can't be called as a tool`);
        }

        // The tool briefly takes over the status dot so the canvas shows
        // which tool the agent is waiting on.
        this.workflow.setNodeRuntime(toolNode.id, { status: 'running' });
        const toolCtx = this.contextFor(toolNode, values, signal, onUsage);
        const result = await executor.invokeTool(toolNode, args, toolCtx);
        this.workflow.setNodeRuntime(toolNode.id, {
          status: result.ok ? 'success' : 'error',
          error: result.ok ? null : result.error,
        });
        return result;
      },

      log: (message: string) => {
        const current = this.workflow.node(node.id)?.runtime.log ?? [];
        this.workflow.setNodeRuntime(node.id, { log: [...current, message] });
        this.bus.emit('run:log', { nodeId: node.id, message });
      },

      reportUsage: (usage: TokenUsage) => {
        const current = this.workflow.node(node.id)?.runtime.tokens ?? 0;
        this.workflow.setNodeRuntime(node.id, { tokens: current + usage.totalTokens });
        onUsage(usage);
      },
    };

    return ctx;
  }

  /** Convenience used by tests and the run controller. */
  static ok(outputs: PortOutputs): Result<PortOutputs, string> {
    return Ok(outputs);
  }
}
