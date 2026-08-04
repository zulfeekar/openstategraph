import { describe, expect, it } from 'vitest';
import { defaultsFrom } from '@core/model/contracts/fields';
import type { IPortDescriptor } from '@core/model/contracts/ports';
import { maxConnectionsOf, portRefEquals, portRefKey, sideOf } from '@core/model/contracts/ports';
import { addNode, makeWorkbench, TYPE } from '@core/testing/fixtures';

const port = (over: Partial<IPortDescriptor> = {}): IPortDescriptor => ({
  id: 'p',
  direction: 'in',
  type: 'text',
  label: 'p',
  ...over,
});

/**
 * Port capacity.
 *
 * Cardinality belongs to the port, not the node: an agent's tool bus accepts
 * many links while its prompt accepts one, and both live on the same node. So
 * "how many edges may attach" has to be answerable per port.
 *
 * The representation of *unlimited* matters more than it looks. A port
 * descriptor is data that reaches `workflow.json`, and `JSON.stringify` turns
 * `Infinity` into `null` — a silent, one-way corruption. `undefined` (meaning
 * "no cap declared") is the only representation that survives a round trip.
 */
describe('maxConnectionsOf', () => {
  it('defaults an input to a single connection', () => {
    // A field cannot be fed two values at once.
    expect(maxConnectionsOf(port({ direction: 'in' }))).toBe(1);
  });

  it('leaves an output uncapped', () => {
    expect(maxConnectionsOf(port({ direction: 'out' }))).toBeNull();
  });

  it('honours an explicit cap', () => {
    expect(maxConnectionsOf(port({ direction: 'in', maxConnections: 4 }))).toBe(4);
  });

  it('honours an explicit uncapped declaration on an input', () => {
    // The agent tool bus: many tools converge on one input port.
    expect(maxConnectionsOf(port({ direction: 'in', maxConnections: null }))).toBeNull();
  });

  it('treats an explicit cap of 0 as a cap, not as absent', () => {
    // `0` is falsy; a `??`/truthiness check here would silently return 1.
    expect(maxConnectionsOf(port({ direction: 'in', maxConnections: 0 }))).toBe(0);
  });

  it('never returns a non-finite number', () => {
    for (const direction of ['in', 'out'] as const) {
      const cap = maxConnectionsOf(port({ direction }));
      if (cap !== null) expect(Number.isFinite(cap)).toBe(true);
    }
  });
});

/**
 * The defect this file exists for: a non-finite number in a field that is
 * serialised. `JSON.stringify(Infinity)` is `"null"`, and `JSON.parse` gives
 * back `null` — so the value does not survive its own round trip, and the
 * corruption is silent.
 */
describe('port descriptors survive JSON', () => {
  it('round-trips every port of every registered node type', () => {
    const workbench = makeWorkbench();

    for (const definition of workbench.registry.nodeTypes.list()) {
      // Ports are a function of data — dynamic port sets are a supported
      // feature — so ask each type for the ports it shows by default.
      for (const p of definition.ports(defaultsFrom(definition.fields))) {
        const revived = JSON.parse(JSON.stringify(p)) as IPortDescriptor;
        expect(revived, `${definition.id}.${p.id} did not survive JSON`).toEqual(p);
      }
    }
  });

  it('caps unlimited ports as null rather than Infinity', () => {
    const workbench = makeWorkbench();

    for (const definition of workbench.registry.nodeTypes.list()) {
      for (const p of definition.ports(defaultsFrom(definition.fields))) {
        if (p.maxConnections == null) continue;
        expect(
          Number.isFinite(p.maxConnections),
          `${definition.id}.${p.id} declares a non-finite cap`,
        ).toBe(true);
      }
    }
  });
});

describe('port helpers', () => {
  it('defaults an input to the left side and an output to the right', () => {
    expect(sideOf(port({ direction: 'in' }))).toBe('left');
    expect(sideOf(port({ direction: 'out' }))).toBe('right');
  });

  it('honours an explicit side', () => {
    expect(sideOf(port({ direction: 'in', side: 'bottom' }))).toBe('bottom');
  });

  it('compares refs by node and port together', () => {
    expect(portRefEquals({ nodeId: 'a', portId: 'p' }, { nodeId: 'a', portId: 'p' })).toBe(true);
    expect(portRefEquals({ nodeId: 'a', portId: 'p' }, { nodeId: 'b', portId: 'p' })).toBe(false);
    expect(portRefEquals({ nodeId: 'a', portId: 'p' }, { nodeId: 'a', portId: 'q' })).toBe(false);
  });

  it('keys refs uniquely', () => {
    expect(portRefKey({ nodeId: 'a', portId: 'p' })).not.toBe(
      portRefKey({ nodeId: 'a', portId: 'q' }),
    );
  });
});

/**
 * Capacity is enforced, not merely declared — an uncapped port must actually
 * accept many links, and a capped one must not silently exceed its cap.
 */
describe('capacity is enforced on the tool bus', () => {
  it('accepts several tools on the agent’s uncapped input', () => {
    const workbench = makeWorkbench();
    const agent = addNode(workbench, TYPE.agent);
    const first = addNode(workbench, TYPE.redditSearch);
    const second = addNode(workbench, TYPE.redditSearch);

    workbench.controller.connect(
      { nodeId: first.id, portId: 'tool' },
      { nodeId: agent.id, portId: 'tools' },
    );
    workbench.controller.connect(
      { nodeId: second.id, portId: 'tool' },
      { nodeId: agent.id, portId: 'tools' },
    );

    // Neither displaces the other: this is the case an Infinity-to-null
    // corruption would break, by collapsing the bus to a single slot.
    expect(workbench.model.edgeCount).toBe(2);
  });
});
