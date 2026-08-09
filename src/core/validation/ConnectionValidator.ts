import { Registry, type IIdentifiable } from '@core/kernel/Registry';
import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { WorkflowModel } from '@core/model/WorkflowModel';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import {
  maxConnectionsOf,
  portAcceptsType,
  portRefEquals,
  type IPortDescriptor,
  type PortRef,
} from '@core/model/contracts/ports';
import type { EdgeId } from '@core/model/contracts/workflow';

/** Everything a rule may inspect about a proposed connection. */
export interface ConnectionContext {
  readonly model: WorkflowModel;
  readonly registry: ModelRegistry;
  readonly source: PortRef;
  readonly target: PortRef;
  readonly sourceNode: AbstractNodeModel;
  readonly targetNode: AbstractNodeModel;
  readonly sourcePort: IPortDescriptor;
  readonly targetPort: IPortDescriptor;
}

/**
 * A rule's finding. `null` from `check` means "no objection".
 *
 * `reason` rejects outright. `replaces` accepts, but requires the listed
 * edges to be removed first — the mechanism behind "dropping a link on an
 * occupied single input swaps it" rather than silently failing.
 */
export interface RuleFinding {
  readonly reason?: string;
  readonly replaces?: readonly EdgeId[];
}

export interface IConnectionRule extends IIdentifiable {
  readonly id: string;
  /** Lower runs first; cheap structural checks should precede graph walks. */
  readonly order: number;
  check(ctx: ConnectionContext): RuleFinding | null;
}

export type ConnectionVerdict =
  | { readonly ok: true; readonly replaces: readonly EdgeId[] }
  | { readonly ok: false; readonly reason: string };

/**
 * Decides whether a link may be drawn.
 *
 * A chain of independent rules rather than one function, because the set of
 * things that make a connection illegal grows with the product (typed
 * ports, capacity, cycles, and later: tool-only buses, scoped links,
 * licence-gated nodes). Each is registered, ordered and individually
 * testable, and the canvas asks one question: `validate`.
 */
export class ConnectionValidator {
  readonly rules = new Registry<IConnectionRule>('connectionRules');

  constructor(
    private readonly model: WorkflowModel,
    private readonly registry: ModelRegistry,
  ) {}

  /**
   * Resolves the endpoints and runs the chain.
   *
   * Called on every pointer-move while a link is being dragged, so the
   * early exits matter: a missing node or port short-circuits before any
   * rule allocates.
   */
  validate(source: PortRef, target: PortRef): ConnectionVerdict {
    const sourceNode = this.model.node(source.nodeId);
    const targetNode = this.model.node(target.nodeId);
    if (!sourceNode || !targetNode) return { ok: false, reason: 'Unknown node' };

    const sourcePort = sourceNode.port(source.portId);
    const targetPort = targetNode.port(target.portId);
    if (!sourcePort || !targetPort) return { ok: false, reason: 'Unknown port' };

    const ctx: ConnectionContext = {
      model: this.model,
      registry: this.registry,
      source,
      target,
      sourceNode,
      targetNode,
      sourcePort,
      targetPort,
    };

    const replaces: EdgeId[] = [];
    for (const rule of this.orderedRules()) {
      const finding = rule.check(ctx);
      if (!finding) continue;
      if (finding.reason) return { ok: false, reason: finding.reason };
      if (finding.replaces) replaces.push(...finding.replaces);
    }
    return { ok: true, replaces };
  }

  /** Convenience for the canvas's magnet highlighting. */
  canConnect(source: PortRef, target: PortRef): boolean {
    return this.validate(source, target).ok;
  }

  private orderedRules(): readonly IConnectionRule[] {
    return this.rules
      .list()
      .slice()
      .sort((a, b) => a.order - b.order);
  }
}

/* ================================================================== *
 * The default rule set.
 *
 * Registered by bootstrap, not by the validator, so an embedding app can
 * drop a rule it does not want or insert its own.
 * ================================================================== */

/** Links run output → input. Prevents in→in and out→out wiring. */
export const directionRule: IConnectionRule = {
  id: 'direction',
  order: 10,
  check({ sourcePort, targetPort }) {
    if (sourcePort.direction !== 'out') return { reason: 'Links must start at an output port' };
    if (targetPort.direction !== 'in') return { reason: 'Links must end at an input port' };
    return null;
  },
};

/** A node cannot feed itself. */
export const selfLoopRule: IConnectionRule = {
  id: 'self-loop',
  order: 20,
  check({ source, target }) {
    return source.nodeId === target.nodeId ? { reason: 'A node cannot connect to itself' } : null;
  },
};

/** The exact same pair of ports may only be linked once. */
export const duplicateRule: IConnectionRule = {
  id: 'duplicate',
  order: 30,
  check({ model, source, target }) {
    const exists = model
      .edgesOf(source.nodeId)
      .some((edge) => portRefEquals(edge.source, source) && portRefEquals(edge.target, target));
    return exists ? { reason: 'These ports are already connected' } : null;
  },
};

/**
 * The consumer's declared `accepts` list governs compatibility — at two
 * granularities. A *port type* may accept another type catalogue-wide, and an
 * individual *port* may opt into one more source type without widening its
 * type for everyone (ticket 08: prompt chaining wants `result → prompt`, not
 * `result → every text input ever added`).
 */
export const typeCompatibilityRule: IConnectionRule = {
  id: 'type-compatibility',
  order: 40,
  check({ registry, sourcePort, targetPort }) {
    if (portAcceptsType(targetPort, sourcePort.type)) return null;
    if (registry.canConnectTypes(sourcePort.type, targetPort.type)) return null;
    const from = registry.portType(sourcePort.type).label;
    const to = registry.portType(targetPort.type).label;
    return { reason: `${from} output can't feed a ${to} input` };
  },
};

/**
 * Enforces port capacity.
 *
 * A full single-slot input yields a *replacement* rather than a rejection:
 * re-wiring an input by dropping a new link on it is the gesture users
 * reach for, and making them delete the old link first is friction with no
 * safety benefit. Multi-slot inputs that are genuinely full do reject,
 * since there is no obvious incumbent to displace.
 */
export const capacityRule: IConnectionRule = {
  id: 'capacity',
  order: 50,
  check({ model, target, targetPort, sourcePort, source }) {
    // `null` is unlimited, so there is nothing to compare against.
    const outMax = maxConnectionsOf(sourcePort);
    if (outMax !== null && model.edgesFrom(source).length >= outMax) {
      return { reason: `This output accepts ${outMax} connection${outMax === 1 ? '' : 's'}` };
    }

    const inMax = maxConnectionsOf(targetPort);
    if (inMax === null) return null;

    const occupying = model.edgesInto(target);
    if (occupying.length < inMax) return null;

    if (inMax === 1) {
      return { replaces: occupying.map((edge) => edge.id) };
    }
    return { reason: `This input accepts ${inMax} connections` };
  },
};

/**
 * Rejects a cycle unless it closes on a **feedback** port.
 *
 * Previously this forbade every cycle, and was unreachable dead code: no input
 * accepted a `result`, so no cycle was type-expressible in the first place.
 * Adding the grader's `revise: feedback` output and the agent's `feedback` input
 * made cycles expressible, which woke this rule up — and it would then have
 * blocked the evaluator-optimizer loop the product exists to support.
 *
 * So the gate is the **port type**, exactly as ticket 09 settled. An *accidental*
 * cycle stays impossible to draw, because nothing else accepts `feedback`, while
 * a deliberate revise loop is two clicks. That is stricter than a flag and needs
 * no escape hatch.
 *
 * What is still forbidden: a cycle of ordinary edges, which can never terminate.
 */
export const acyclicRule: IConnectionRule = {
  id: 'acyclic',
  order: 60,
  check({ model, source, target, sourcePort }) {
    // A feedback edge is the declared way to close a loop.
    if (sourcePort.type === 'feedback') return null;

    const seen = new Set<string>([target.nodeId]);
    const queue = [target.nodeId];
    while (queue.length > 0) {
      const current = queue.shift();
      if (current == null) continue;
      if (current === source.nodeId) {
        return {
          reason: 'That would create a loop. Route it through a Grader’s “revise” output instead.',
        };
      }
      for (const next of model.successorsOf(current)) {
        if (seen.has(next.id)) continue;
        seen.add(next.id);
        queue.push(next.id);
      }
    }
    return null;
  },
};

export const DEFAULT_CONNECTION_RULES: readonly IConnectionRule[] = [
  directionRule,
  selfLoopRule,
  duplicateRule,
  typeCompatibilityRule,
  capacityRule,
  acyclicRule,
];
