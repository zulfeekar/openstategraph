import type { Accent } from '@design/tokens';
import type { IIdentifiable } from '@core/kernel/Registry';

/**
 * Ports carry typed values. A port *type* is a first-class, registered
 * concept rather than a string on a node, because three separate concerns
 * need to agree about it: connection validity, the glyph and colour shown
 * next to the port, and how the execution engine coerces a value flowing
 * across a link.
 */
export type PortTypeId = string;

export type PortDirection = 'in' | 'out';

/** Which edge of the card a port's dot sits on. */
export type PortSide = 'left' | 'right' | 'top' | 'bottom';

export interface IPortTypeDefinition extends IIdentifiable {
  readonly id: PortTypeId;
  readonly label: string;
  /** Resolved to a concrete glyph by the view's icon registry. */
  readonly iconId: string;
  readonly accent: Accent;
  /**
   * Port types this one accepts input from. Defaults to "only itself".
   * `'*'` accepts anything — used by pass-through and debug nodes.
   */
  readonly accepts?: readonly (PortTypeId | '*')[];
}

/**
 * A port as declared by a node type. Static shape; the runtime instance
 * (`PortInstance`) pairs this with its owning node id.
 */
export interface IPortDescriptor {
  /** Unique within its node. */
  readonly id: string;
  readonly direction: PortDirection;
  readonly type: PortTypeId;
  /** Shown in the node's port footer, e.g. "prompt". */
  readonly label: string;
  /**
   * Cap on simultaneous connections. Inputs default to 1 (a node field
   * cannot be fed two values at once); outputs default to unlimited,
   * since fanning one result into several consumers is normal.
   *
   * `null` declares *unlimited* explicitly — an agent's tool bus, where many
   * tools converge on one input. It is `null` and not `Infinity` because a
   * port descriptor is data that reaches `workflow.json`, and
   * `JSON.stringify(Infinity)` is `"null"`: the value would not survive its
   * own round trip, and nothing would report the loss.
   */
  readonly maxConnections?: number | null;
  /** An unconnected required input makes the workflow invalid. */
  readonly required?: boolean;
  /** Defaults to `left` for inputs and `right` for outputs. */
  readonly side?: PortSide;
  /**
   * `row`  — a labelled row in the node footer with a dot on the card edge.
   * `pill` — a detached labelled capsule below the card, used for the
   *          agent's tool bus where several tools converge on one point.
   */
  readonly appearance?: 'row' | 'pill';
  /**
   * This output is one of several **mutually exclusive** ways out of the node
   * — a router branch, a grader's pass/revise, an approval's
   * approved/rejected. The canvas puts the port's name on the *link* leaving
   * it, because "which way did it go" is a fact about the connection, not
   * about the card.
   *
   * Declared here rather than sniffed from the node type so a plugin's own
   * conditional node gets the same treatment with no canvas edit (open-closed:
   * a new capability registers, it does not amend `canvas/`).
   *
   * Only conditional outputs earn a label. A typed edge — tool, skill,
   * feedback, worker — already carries colour plus a dash signature and has a
   * legend; labelling those too is noise that hides the labels that matter.
   */
  readonly branch?: boolean;
  /** Tooltip / inspector help text. */
  readonly description?: string;
  /**
   * Extra source port types *this port* accepts, on top of whatever its port
   * type already declares. Narrower than widening the type itself: an
   * agent's `prompt` may consume a previous agent's `result` (prompt
   * chaining) without every `text` input in the catalogue silently gaining
   * the same affordance.
   *
   * Consumer-declared, like `IPortTypeDefinition.accepts`, and additive only
   * — a port may open itself up, never close down what its type allows.
   */
  readonly accepts?: readonly (PortTypeId | '*')[];
}

export interface PortInstance extends IPortDescriptor {
  readonly nodeId: string;
}

/** Fully-qualified endpoint of an edge. */
export interface PortRef {
  readonly nodeId: string;
  readonly portId: string;
}

export const portRefEquals = (a: PortRef, b: PortRef): boolean =>
  a.nodeId === b.nodeId && a.portId === b.portId;

export const portRefKey = (ref: PortRef): string => `${ref.nodeId}/${ref.portId}`;

/**
 * Resolves the effective connection cap for a port. `null` means unlimited.
 *
 * The check is `=== undefined`, not `!= null`: `null` is a meaningful
 * declaration (unlimited) rather than an absent one, and `0` is a real cap, so
 * neither may fall through to the direction default.
 */
export function maxConnectionsOf(port: IPortDescriptor): number | null {
  if (port.maxConnections !== undefined) return port.maxConnections;
  return port.direction === 'in' ? 1 : null;
}

/**
 * Whether this *port* individually opts into a source type its port type does
 * not already accept. Type-level compatibility is checked separately, so this
 * only ever widens.
 */
export function portAcceptsType(port: IPortDescriptor, sourceType: PortTypeId): boolean {
  const accepts = port.accepts;
  if (!accepts) return false;
  return accepts.includes('*') || accepts.includes(sourceType);
}

/**
 * Resolves the effective side for a port.
 *
 * **Position encodes role**, so a reader knows what a port is for before
 * hovering it. Two roles, two axes:
 *
 * - **Flow** — the sequence of steps. Input `left`, output `right`, i.e.
 *   along the reading axis. This is the default and needs no declaration.
 * - **Binding** — a capability *attached* to a step rather than a step in
 *   the sequence: a tool, a skill, a worker pool. Drawn across the reading
 *   axis, so a binding never looks like a stage of the flow. Declared with
 *   `side: BINDING_SIDE.provider` on the thing being attached, and
 *   `BINDING_SIDE.consumer` on the bus that gathers them.
 *
 * Both rotate together under `resolvePortSide`, so the distinction survives
 * the flow-direction toggle instead of being a horizontal-only convention.
 */
export function sideOf(port: IPortDescriptor): PortSide {
  return port.side ?? (port.direction === 'in' ? 'left' : 'right');
}

/**
 * The two ends of a binding, named once.
 *
 * A tool node's `tool` output and a Markdown file's `skill` output are the
 * same kind of thing — a capability offered upward — and had drifted onto
 * different sides. Naming the convention is what stops that happening again;
 * the alternative was two node files each asserting a bare string.
 */
export const BINDING_SIDE = {
  /** The card offering a capability: its dot is on top, pointing up at the user of it. */
  provider: 'top',
  /** The card consuming several: a bus slung under the card. */
  consumer: 'bottom',
} as const satisfies Record<string, PortSide>;

/** Which way the canvas reads: left→right, or top→bottom. Ticket 45. */
export type FlowDirection = 'horizontal' | 'vertical';

const CLOCKWISE: Record<PortSide, PortSide> = {
  left: 'top',
  top: 'right',
  right: 'bottom',
  bottom: 'left',
};

/**
 * The side a port lands on under a given flow direction.
 *
 * One rule, no per-port annotations: a port's effective *horizontal* side
 * (explicit `side`, or the in→left / out→right default) rotates 90°
 * clockwise for vertical flow. That single rotation moves flow ports from
 * the left/right edges to top/bottom AND swings the tool/worker buses from
 * top/bottom onto the card's flanks — every existing `side` declaration
 * keeps meaning what it meant, just relative to the reading direction.
 */
export function resolvePortSide(port: IPortDescriptor, flow: FlowDirection): PortSide {
  const horizontal = sideOf(port);
  return flow === 'horizontal' ? horizontal : CLOCKWISE[horizontal];
}
