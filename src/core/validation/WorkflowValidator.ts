import { Registry, type IIdentifiable } from '@core/kernel/Registry';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import { validateFields } from '@core/model/contracts/fields';
import type { NodeId } from '@core/model/contracts/node';

/** True if a path exists from `start` back to itself, staying within `candidates`. */
function canReachSelf(model: WorkflowModel, candidates: ReadonlySet<NodeId>, start: NodeId): boolean {
  const stack: NodeId[] = [start];
  const visited = new Set<NodeId>();
  while (stack.length > 0) {
    const current = stack.pop();
    if (current == null) continue;
    for (const edge of model.edgesOf(current)) {
      if (edge.source.nodeId !== current) continue;
      const next = edge.target.nodeId;
      if (!candidates.has(next)) continue;
      if (next === start) return true;
      if (!visited.has(next)) {
        visited.add(next);
        stack.push(next);
      }
    }
  }
  return false;
}

export type DiagnosticSeverity = 'error' | 'warning' | 'info';

export interface Diagnostic {
  readonly code: string;
  readonly severity: DiagnosticSeverity;
  readonly message: string;
  /** Node the problem is attached to, when it has one. */
  readonly nodeId?: NodeId;
  /** Field key within that node, when the problem is a specific input. */
  readonly fieldKey?: string;
}

export interface WorkflowRuleContext {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
}

export interface IWorkflowRule extends IIdentifiable {
  readonly id: string;
  check(ctx: WorkflowRuleContext): readonly Diagnostic[];
}

/**
 * Whole-graph checks, run before a workflow executes and continuously to
 * drive per-node status dots.
 *
 * Separate from `ConnectionValidator`, which answers a local question
 * about one prospective link. This answers "is the document runnable",
 * which is a different lifecycle and a different set of rules.
 */
export class WorkflowValidator {
  readonly rules = new Registry<IWorkflowRule>('workflowRules');

  constructor(
    private readonly model: WorkflowModel,
    private readonly registry: ModelRegistry,
  ) {}

  validate(): readonly Diagnostic[] {
    const ctx: WorkflowRuleContext = { model: this.model, registry: this.registry };
    const diagnostics: Diagnostic[] = [];
    for (const rule of this.rules.list()) {
      try {
        diagnostics.push(...rule.check(ctx));
      } catch (error) {
        // A broken rule must not block a run; report it as a diagnostic.
        diagnostics.push({
          code: 'rule-failed',
          severity: 'warning',
          message: `Validation rule "${rule.id}" failed: ${String(error)}`,
        });
      }
    }
    return diagnostics;
  }

  /** Diagnostics grouped by node, for rendering status on the cards. */
  byNode(): Map<NodeId, Diagnostic[]> {
    const grouped = new Map<NodeId, Diagnostic[]>();
    for (const diagnostic of this.validate()) {
      if (!diagnostic.nodeId) continue;
      const bucket = grouped.get(diagnostic.nodeId);
      if (bucket) bucket.push(diagnostic);
      else grouped.set(diagnostic.nodeId, [diagnostic]);
    }
    return grouped;
  }

  get isRunnable(): boolean {
    return !this.validate().some((d) => d.severity === 'error');
  }
}

/* ================================================================== *
 * Default rules
 * ================================================================== */

/** Every port marked `required` must be wired. */
export const requiredInputsRule: IWorkflowRule = {
  id: 'required-inputs',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      if (node.kind !== 'standard') continue;
      for (const port of node.ports) {
        if (port.direction !== 'in' || !port.required) continue;
        const connected = model.edgesInto({ nodeId: node.id, portId: port.id }).length > 0;
        if (!connected) {
          diagnostics.push({
            code: 'required-input-missing',
            severity: 'error',
            nodeId: node.id,
            message: `${node.title} needs a "${port.label}" input`,
          });
        }
      }
    }
    return diagnostics;
  },
};

/** Field-level validators declared in each node type's schema. */
export const fieldValidationRule: IWorkflowRule = {
  id: 'fields',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      const errors = validateFields(node.definition.fields, node.data);
      for (const [fieldKey, message] of Object.entries(errors)) {
        diagnostics.push({
          code: 'field-invalid',
          severity: 'error',
          nodeId: node.id,
          fieldKey,
          message: `${node.title}: ${message}`,
        });
      }
    }
    return diagnostics;
  },
};

/**
 * Cycles.
 *
 * `ConnectionValidator` already refuses to draw one, but a document can
 * arrive cyclic from an import or a hand-edited file, so the runnable check
 * cannot assume acyclicity.
 *
 * Not every cycle is the same *kind* of problem. CLAUDE.md's own rule: "a
 * cycle must contain at least one conditional edge — an all-static cycle
 * can never terminate." A grader's `revise` port looping back to its own
 * agent is exactly the valid case — the same node also has a `pass` port
 * that escapes the cycle, so the loop terminates the moment the grader
 * passes. That shape is legitimate for the backend LangGraph compiler,
 * just unrunnable by this engine's local, sequential DAG preview.
 *
 * A cycle with **no** escaping edge at all — every node in it only ever
 * feeds back into the cycle, never out — is the other case: an accidental,
 * genuinely infinite loop, which is a real bug regardless of which engine
 * runs it. Flagging both identically as `error` made a legitimate,
 * intentional revise loop (in a graph that runs correctly through the
 * backend) look exactly as broken as one that can never produce an answer
 * on any engine. Only the second kind should block a static "is this
 * runnable" check; the first is a `warning` — noteworthy, not broken.
 */
export const acyclicGraphRule: IWorkflowRule = {
  id: 'acyclic-graph',
  check({ model }) {
    const { cycle: blocked } = model.topologicalOrder();
    if (!blocked || blocked.length === 0) return [];

    // `topologicalOrder()`'s `cycle` is Kahn's leftover set: every node
    // whose in-degree never reached zero. That over-includes anything
    // merely *downstream* of a cycle (blocked because its dependency never
    // finished), not only the cycle's own members — found by this rule's
    // own escape check misfiring: a node three hops past the actual loop,
    // with no edge back into anything, still landed in that set and made
    // the escape look absent. A node is truly *in* the cycle only if a
    // path exists from it back to itself using edges between other members
    // of the leftover set.
    const candidates = new Set(blocked);
    const cycle = blocked.filter((start) => canReachSelf(model, candidates, start));
    const inCycle = new Set(cycle);
    const hasEscape = cycle.some((nodeId) =>
      model
        .edgesOf(nodeId)
        .some((edge) => edge.source.nodeId === nodeId && !inCycle.has(edge.target.nodeId)),
    );

    return cycle.map((nodeId) => {
      const title = model.node(nodeId)?.title ?? nodeId;
      return hasEscape
        ? {
            code: 'escapable-loop',
            severity: 'warning' as const,
            nodeId,
            message: `${title} can loop back before continuing — valid for the backend, but the canvas preview can't run it`,
          }
        : {
            code: 'cycle',
            severity: 'error' as const,
            nodeId,
            message: `${title} is part of a loop with no way out — this can never finish`,
          };
    });
  },
};

/**
 * A graph with no terminal node produces nothing observable.
 *
 * "Terminal" means unwired downstream, not "has zero declared out-ports" —
 * found live: `AgentNode`, `RouterNode` and `GraderNode` all statically
 * declare a `result`/branch out-port regardless of whether anything is
 * connected to it, so a workflow that legitimately ends in one of them
 * without a separate `Output` node (the backend compiler supports this
 * fine — `_agent`/`_format_report_function` write `answer` directly) was
 * flagged "nothing consumes the result" even though the run produces a real
 * answer. Only `output.formatted` has literally zero out-ports; checking
 * port *descriptors* instead of actual edges made every other node type a
 * false positive.
 */
export const hasOutputRule: IWorkflowRule = {
  id: 'has-output',
  check({ model }) {
    const executable = model.nodes().filter((node) => node.kind === 'standard');
    if (executable.length === 0) return [];
    const hasSink = executable.some((node) => {
      const outPorts = node.ports.filter((p) => p.direction === 'out');
      if (outPorts.length === 0) return true;
      return outPorts.every(
        (port) => model.edgesFrom({ nodeId: node.id, portId: port.id }).length === 0,
      );
    });
    return hasSink
      ? []
      : [
          {
            code: 'no-output',
            severity: 'warning',
            message: 'Nothing consumes the result — add an output node',
          },
        ];
  },
};

/** Nodes wired to nothing at all will never run. */
export const orphanNodeRule: IWorkflowRule = {
  id: 'orphan-nodes',
  check({ model }) {
    const executable = model.nodes().filter((node) => node.kind === 'standard');
    // A lone node on a fresh canvas is normal, not a warning.
    if (executable.length < 2) return [];
    return executable
      .filter((node) => node.ports.length > 0 && model.edgesOf(node.id).length === 0)
      .map((node) => ({
        code: 'orphan-node',
        severity: 'info' as const,
        nodeId: node.id,
        message: `${node.title} isn't connected to anything`,
      }));
  },
};

/**
 * At most one worker per orchestrator may claim "Default worker".
 *
 * Ticket 37's hybrid routing sends unlabelled/unrecognised subtasks to the
 * default archetype. Two claims is not a broken document — the compiler
 * deterministically takes the first wired claimant — but the second card's
 * toggle is silently inert, which is exactly the kind of thing a developer
 * should be told rather than left to discover from dispatch behaviour.
 */
export const singleDefaultWorkerRule: IWorkflowRule = {
  id: 'single-default-worker',
  check({ model }) {
    const diagnostics: Diagnostic[] = [];
    for (const node of model.nodes()) {
      if (node.type !== 'orchestrate.supervisor') continue;
      const claimants = model
        .edgesFrom({ nodeId: node.id, portId: 'workers' })
        .map((edge) => model.node(edge.target.nodeId))
        .filter((worker) => worker != null && worker.data['default'] === true);
      if (claimants.length < 2) continue;
      for (const worker of claimants) {
        diagnostics.push({
          code: 'multiple-default-workers',
          severity: 'warning',
          nodeId: worker!.id,
          message: `${worker!.title}: more than one worker claims "Default worker" — only the first wired one takes effect`,
        });
      }
    }
    return diagnostics;
  },
};

export const DEFAULT_WORKFLOW_RULES: readonly IWorkflowRule[] = [
  requiredInputsRule,
  fieldValidationRule,
  acyclicGraphRule,
  hasOutputRule,
  orphanNodeRule,
  singleDefaultWorkerRule,
];
