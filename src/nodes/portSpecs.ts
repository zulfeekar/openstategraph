import { Registry } from '@core/kernel/Registry';
import { ModelRegistry } from '@core/model/ModelRegistry';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { defaultsFrom } from '@core/model/contracts/fields';
import type { NodeData } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { IPortDescriptor } from '@core/model/contracts/ports';
import { maxConnectionsOf } from '@core/model/contracts/ports';
import type { INodeExecutor } from '@core/execution/INodeExecutor';

import { registerNodeCatalogue } from './index';
import { CHINOOK_NODES } from './tools/ChinookDatabaseNode';
import { TABULAR_NODES } from './tools/TabularDataNode';
import { WORKSHOP_NODES } from './tools/CodeWorkshopNode';

/**
 * The node/port catalogue, serialised for the Python runtime.
 *
 * **Why this file exists.** `backend/openstategraph/compile/workflow_compiler.py`
 * used to carry a hand-written Python copy of every node type's port table, and
 * its own comment admitted the duplication. CLAUDE.md forbids hand-mirroring a
 * type across the boundary; the register calls it RC-01. This module is the
 * generator that removes the mirror.
 *
 * **Which side generates, and why this one.** The TypeScript catalogue is
 * authoritative: `INodeDefinition.ports` is a *function of node data*, it drives
 * the editor's palette, canvas, inspector and connection rules, and a node type
 * is added by writing a module here. Python only ever *reads* the shape. So
 * TypeScript emits and Python loads — the opposite direction to the Pydantic →
 * TypeScript generation rule, and deliberately so: the rule is "one declaration,
 * generated consumers", not "Python always wins".
 *
 * The emitted JSON is **committed** (`backend/openstategraph/compile/port_specs.json`)
 * because the Python wheel must work with no Node.js anywhere near it. CI
 * regenerates and diffs, so a stale artifact fails the build instead of rotting
 * behind a comment.
 */

/** Bumped when the artifact's shape changes in a way Python must notice. */
export const PORT_SPEC_SCHEMA_VERSION = 1;

/** Where the emitted artifact lives, relative to the repository root. */
export const PORT_SPEC_ARTIFACT_PATH = 'backend/openstategraph/compile/port_specs.json';

/** The npm script that regenerates it. Quoted verbatim in the drift failure. */
export const PORT_SPEC_GENERATE_COMMAND = 'npm run generate:ports';

export interface GeneratedPort {
  readonly id: string;
  readonly direction: 'in' | 'out';
  readonly type: string;
  readonly label: string;
  readonly required: boolean;
  /**
   * Resolved cap; `null` is *unlimited*, spelled out rather than left to a
   * default. Never `Infinity` — CLAUDE.md forbids a non-finite number in a
   * serialisable field, and this one crosses a language boundary as JSON.
   */
  readonly max_connections: number | null;
  /** Effective source port types accepted here, port-level widening included. */
  readonly accepts: readonly string[];
}

/**
 * A family of ports generated from a node's own configuration rather than
 * declared statically — today, one per branch on a router.
 *
 * Discovered by probing rather than declared twice: see `splitPorts`.
 */
export interface GeneratedDynamicPortGroup {
  readonly prefix: string;
  readonly direction: 'in' | 'out';
  readonly type: string;
  readonly max_connections: number | null;
  readonly accepts: readonly string[];
}

export interface GeneratedNodeType {
  readonly type: string;
  readonly kind: string;
  readonly category: string;
  /** `'app'` (always available) or `'workflow'` (travels with a package). */
  readonly scope: string;
  readonly label: string;
  readonly description: string;
  readonly ports: readonly GeneratedPort[];
  readonly dynamic_ports: readonly GeneratedDynamicPortGroup[];
}

export interface GeneratedPortType {
  readonly id: string;
  readonly label: string;
  readonly accepts: readonly string[];
}

export interface NodeCatalogueArtifact {
  readonly schema_version: number;
  readonly generated_by: string;
  readonly source: string;
  readonly warning: string;
  readonly port_types: readonly GeneratedPortType[];
  readonly node_types: readonly GeneratedNodeType[];
}

/**
 * Every node definition the product can register, app-scoped and
 * workflow-scoped alike.
 *
 * The workflow-scoped families are the documented supplementary source the
 * ticket asks for: `registerNodeCatalogue` deliberately does *not* register
 * them (one workflow's tools must not litter every palette — see
 * `syncWorkflowScopedNodes`), yet a document that uses them is compiled by the
 * same Python compiler and described by the same MCP vocabulary. Enumerating
 * the exported families here is the only way they reach the artifact, and the
 * test asserts each family is present so adding a fourth family cannot be
 * forgotten silently.
 *
 * Not enumerable, by construction: `createDiscoveredToolNode` mints a node type
 * per tool found in a *particular* workflow package at runtime. Those keep
 * arriving through `tool.`/`function.` prefix handling on the Python side; no
 * static artifact could list them.
 */
export function allNodeDefinitions(): readonly INodeDefinition[] {
  return buildCatalogue().definitions;
}

/**
 * Stands up the real catalogue exactly as the editor does.
 *
 * `CredentialStore(false)` keeps the provider registry memory-only: this runs
 * under Node, where `window.localStorage` does not exist.
 */
function buildCatalogue(): { registry: ModelRegistry; definitions: readonly INodeDefinition[] } {
  const registry = new ModelRegistry();
  const executors = new Registry<INodeExecutor>('executors');
  registerNodeCatalogue(registry, executors, new ProviderRegistry(new CredentialStore(false)));

  const workflowScoped = [...CHINOOK_NODES, ...TABULAR_NODES, ...WORKSHOP_NODES].map(
    (entry) => entry.definition,
  );
  return { registry, definitions: [...registry.nodeTypes.list(), ...workflowScoped] };
}

/**
 * Data that makes a node produce as few config-generated ports as possible.
 *
 * Arrays and strings are emptied because that is what a "no branches
 * configured" state looks like. Compared against the defaults, the ports that
 * differ are exactly the ones the node computes from its data.
 */
function emptyData(defaults: NodeData): NodeData {
  const probe: NodeData = {};
  for (const [key, value] of Object.entries(defaults)) {
    probe[key] = Array.isArray(value) ? [] : typeof value === 'string' ? '' : value;
  }
  return probe;
}

/** Longest common prefix of a set of port ids, e.g. `branch:`. */
function commonPrefix(ids: readonly string[]): string {
  if (ids.length === 0) return '';
  let prefix = ids[0] ?? '';
  for (const id of ids) {
    let i = 0;
    while (i < prefix.length && i < id.length && prefix[i] === id[i]) i += 1;
    prefix = prefix.slice(0, i);
  }
  return prefix;
}

/**
 * Effective source port types a port accepts.
 *
 * Two declarations combine: the port *type*'s own `accepts` (defaulting to
 * "only itself") and the port's additive widening. Resolved here so a consumer
 * in another language does not have to re-implement `ModelRegistry.canConnectTypes`.
 */
function acceptsOf(registry: ModelRegistry, port: IPortDescriptor): string[] {
  const typeDefinition = registry.portTypes.get(port.type);
  const fromType = typeDefinition?.accepts ?? [port.type];
  return [...new Set([...fromType, ...(port.accepts ?? [])])].sort();
}

function serializePort(registry: ModelRegistry, port: IPortDescriptor): GeneratedPort {
  return {
    id: port.id,
    direction: port.direction,
    type: port.type,
    label: port.label,
    required: port.required ?? false,
    max_connections: maxConnectionsOf(port),
    accepts: acceptsOf(registry, port),
  };
}

/**
 * Splits a node's ports into the statically declared ones and the families it
 * generates from its own configuration.
 *
 * Probed, never declared: a `dynamicPorts` field on `INodeDefinition` would
 * state in metadata what `ports()` already states in code, which is the same
 * mirror this whole file exists to delete. Ports that survive emptying the
 * node's data unchanged are static; the rest are grouped by their common id
 * prefix.
 */
function splitPorts(
  registry: ModelRegistry,
  definition: INodeDefinition,
): { ports: GeneratedPort[]; dynamic: GeneratedDynamicPortGroup[] } {
  const defaults = defaultsFrom(definition.fields);
  const configured = definition.ports(defaults);
  const probed = definition.ports(emptyData(defaults));

  const probedIds = new Set(probed.map((port) => port.id));
  const configuredIds = new Set(configured.map((port) => port.id));

  const stable = configured.filter((port) => probedIds.has(port.id));
  const varying = [
    ...configured.filter((port) => !probedIds.has(port.id)),
    ...probed.filter((port) => !configuredIds.has(port.id)),
  ];

  if (varying.length === 0) {
    return { ports: stable.map((port) => serializePort(registry, port)), dynamic: [] };
  }

  const template = varying[0]!;
  const prefix = commonPrefix(varying.map((port) => port.id));
  return {
    ports: stable.map((port) => serializePort(registry, port)),
    dynamic: [
      {
        prefix,
        direction: template.direction,
        type: template.type,
        max_connections: maxConnectionsOf(template),
        accepts: acceptsOf(registry, template),
      },
    ],
  };
}

/**
 * Builds the artifact. Pure, deterministic and sorted, so the drift diff is
 * about the catalogue rather than about iteration order.
 */
export function buildPortSpecArtifact(): NodeCatalogueArtifact {
  const { registry, definitions } = buildCatalogue();

  const nodeTypes = definitions
    .map((definition): GeneratedNodeType => {
      const { ports, dynamic } = splitPorts(registry, definition);
      return {
        type: definition.id,
        kind: definition.kind,
        category: definition.category,
        scope: definition.scope ?? 'app',
        label: definition.label,
        description: definition.description,
        ports,
        dynamic_ports: dynamic,
      };
    })
    .sort((a, b) => (a.type < b.type ? -1 : a.type > b.type ? 1 : 0));

  const portTypes = registry.portTypes
    .list()
    .map((definition): GeneratedPortType => ({
      id: definition.id,
      label: definition.label,
      accepts: [...new Set(definition.accepts ?? [definition.id])].sort(),
    }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  return {
    schema_version: PORT_SPEC_SCHEMA_VERSION,
    generated_by: PORT_SPEC_GENERATE_COMMAND,
    source: 'src/nodes/portSpecs.ts',
    warning:
      'GENERATED FILE — DO NOT EDIT. The TypeScript node catalogue is authoritative; ' +
      `run \`${PORT_SPEC_GENERATE_COMMAND}\` after changing a node type or a port.`,
    port_types: portTypes,
    node_types: nodeTypes,
  };
}

/** The exact bytes written to disk, so the drift check compares like with like. */
export function serializePortSpecArtifact(artifact: NodeCatalogueArtifact): string {
  return `${JSON.stringify(artifact, null, 2)}\n`;
}
