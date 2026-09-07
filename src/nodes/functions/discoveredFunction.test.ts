import { describe, expect, it, beforeEach } from 'vitest';
import { Workbench } from '@app/Workbench';
import {
  capabilityBackedTypeIds,
  forgetCapabilityBackedTypeIds,
  packageScopedNodes,
  registerDiscoveredCapabilities,
  registerNodeTypesForRawDocument,
} from '@nodes/workflowScoped';
import type { FunctionCapability } from '@core/runtime/WorkflowFileClient';
import { discoveredFunctionNodeType } from './DiscoveredFunctionNode';

/**
 * `export-and-eject/01` — a discovered function runs, but nobody could put
 * one on a canvas.
 *
 * Every assertion here is phrased against the surface a developer actually
 * touches: the palette's "This workflow" list (`packageScopedNodes`), the
 * node type ids a document may name, and the ports an edge may land on. A
 * test that merely asked whether a registry minted *something* would stay
 * green if the minted type carried a node type id the compiler cannot bind —
 * which is the one thing that would make the whole feature useless.
 */
const shout: FunctionCapability = {
  id: 'fnlab/functions.shout',
  name: 'shout',
  docstring: 'Uppercases the upstream text and adds a bang.',
  signature: '(text: str) -> str',
};

const reverseIt: FunctionCapability = {
  id: 'fnlab/functions.reverse_it',
  name: 'reverse_it',
  docstring: '',
  signature: '(text: str) -> str',
};

const open = (functions: readonly FunctionCapability[], document: unknown = { nodes: [] }) => {
  const workbench = new Workbench();
  registerNodeTypesForRawDocument(document, workbench.registry, workbench.engine.executors);
  registerDiscoveredCapabilities(
    { tools: [], functions },
    workbench.registry,
    workbench.engine.executors,
  );
  return workbench;
};

const palette = (workbench: Workbench) =>
  packageScopedNodes(workbench.registry.paletteSections(), capabilityBackedTypeIds()).map(
    (definition) => definition.id,
  );

describe('a discovered function on the canvas', () => {
  beforeEach(() => forgetCapabilityBackedTypeIds());

  it('is named by the type id the compiler binds, not by the capability id', () => {
    // `NodeRuntime.builder_for` dispatches on a `function.` prefix and
    // `discover_function_callables` keys its registry `function.<name>` — so a
    // node typed `fnlab/functions.shout` would compile to `_passthrough` and
    // report an unresolved binding. The capability id is slug-qualified for
    // *reporting*; the node type is the runtime's own convention.
    expect(discoveredFunctionNodeType(shout)).toBe('function.shout');
  });

  it('appears in the palette of the package that ships it', () => {
    expect(palette(open([shout, reverseIt])).sort()).toEqual([
      'function.reverse_it',
      'function.shout',
    ]);
  });

  it('leaves the palette when a package without it is opened', () => {
    const workbench = open([shout]);
    expect(palette(workbench)).toEqual(['function.shout']);

    registerDiscoveredCapabilities(
      { tools: [], functions: [] },
      workbench.registry,
      workbench.engine.executors,
    );
    expect(palette(workbench)).toEqual([]);
  });

  it('can be placed, and carries one in-port and one out-port', () => {
    const workbench = open([shout]);
    const definition = workbench.registry.nodeTypes.require('function.shout');

    const ports = typeof definition.ports === 'function' ? definition.ports({}) : definition.ports;
    const inputs = ports.filter((port) => port.direction === 'in');
    const outputs = ports.filter((port) => port.direction === 'out');
    expect(inputs).toHaveLength(1);
    expect(outputs).toHaveLength(1);
    // `fn(text: str) -> str` and nothing more: one link in (the default
    // cardinality), a fan-out allowed on the way out.
    expect(inputs[0]?.maxConnections ?? 1).toBe(1);
    expect(outputs[0]?.maxConnections ?? null).toBe(null);

    // Placeable, which is the whole ticket.
    const node = workbench.controller.nodes.add('function.shout', { x: 0, y: 0 });
    expect(node.ok).toBe(true);
  });

  it('offers no configuration, because the runtime reads none', () => {
    // v1, stated rather than left to be inferred: the signature and docstring
    // become the card's label and description, never a field schema. A field
    // would be a control the compiled step cannot see, and the backend already
    // refuses those elsewhere as "a picker the compiler ignores".
    //
    // Not `toEqual([])`: `defineNode` gives every node type the graph-assembly
    // overrides (retry, timeout) that `StateGraph.add_node` takes, and those
    // belong to the workflow rather than to this family. What must be empty is
    // everything else.
    const fields = workbenchDefinition().fields;
    expect(fields.filter((field) => field.group !== 'Execution')).toEqual([]);
    expect(fields.map((field) => field.key)).not.toContain('text');
  });

  it('preserves a document that names one when the package is gone', () => {
    // CLAUDE.md's `code -> canvas` rule: the type id is data that travels with
    // the package, and a document naming one must be preserved exactly as
    // saved. With the package present the type is registered and the palette
    // offers it; with the package absent neither happens — and the node must
    // still survive a load and a save unrewritten, via the unknown-node path.
    const authored = open([shout]);
    authored.controller.nodes.add('function.shout', { x: 40, y: 40 });
    const json = authored.controller.document.exportJSON();

    const elsewhere = open([]);
    elsewhere.controller.document.importJSON(json);
    expect(palette(elsewhere)).toEqual([]);
    expect(
      (
        JSON.parse(elsewhere.controller.document.exportJSON()) as { nodes: { type: string }[] }
      ).nodes.map((node) => node.type),
    ).toEqual(['function.shout']);
  });

  function workbenchDefinition() {
    return open([shout]).registry.nodeTypes.require('function.shout');
  }
});
