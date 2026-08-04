import { Registry, type IIdentifiable } from '@core/kernel/Registry';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import { validateFields } from '@core/model/contracts/fields';
import type { NodeId } from '@core/model/contracts/node';

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
 */
export const acyclicGraphRule: IWorkflowRule = {
  id: 'acyclic-graph',
  check({ model }) {
    const { cycle } = model.topologicalOrder();
    if (!cycle || cycle.length === 0) return [];
    return cycle.map((nodeId) => ({
      code: 'cycle',
      severity: 'error' as const,
      nodeId,
      message: `${model.node(nodeId)?.title ?? nodeId} is part of a loop`,
    }));
  },
};

/** A graph with no terminal node produces nothing observable. */
export const hasOutputRule: IWorkflowRule = {
  id: 'has-output',
  check({ model }) {
    const executable = model.nodes().filter((node) => node.kind === 'standard');
    if (executable.length === 0) return [];
    const hasSink = executable.some(
      (node) => node.ports.filter((p) => p.direction === 'out').length === 0,
    );
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

export const DEFAULT_WORKFLOW_RULES: readonly IWorkflowRule[] = [
  requiredInputsRule,
  fieldValidationRule,
  acyclicGraphRule,
  hasOutputRule,
  orphanNodeRule,
];
