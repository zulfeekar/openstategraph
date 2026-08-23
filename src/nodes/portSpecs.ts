import { Registry } from '@core/kernel/Registry';
import { ModelRegistry } from '@core/model/ModelRegistry';
import { CredentialStore, ProviderRegistry } from '@core/providers/ProviderRegistry';
import { defaultsFrom } from '@core/model/contracts/fields';
import type { FieldValue, NodeData } from '@core/model/contracts/fields';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { IPortDescriptor } from '@core/model/contracts/ports';
import { maxConnectionsOf } from '@core/model/contracts/ports';
import type { INodeExecutor } from '@core/execution/INodeExecutor';

import { registerNodeCatalogue } from './index';
import { workflowScopedFamilies } from './workflowScoped';
import { MODEL_FIELD_KEY } from './modelField';
import { LEGACY_RULES_MODE_KEY, SKILL_PORT_ID } from './skillLayer';
import { LEGACY_SKILL_BODY_KEY } from './inputs/SkillNode';

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
export const PORT_SPEC_SCHEMA_VERSION = 3;

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
  /**
   * Does this node type drive a language model — i.e. does it declare the
   * shared `model` field (`src/nodes/modelField.ts`)?
   *
   * Emitted because the two sides had silently disagreed about it. The
   * backend's `NodeRuntime._resolve_model(data)` read `data["model"]` for six
   * node types while only one of them shipped the picker, so five nodes drove
   * a model that nobody could choose and the backend read a key nothing could
   * write. Nothing failed — it just quietly used the wrong model, which is the
   * worst shape a defect can take.
   *
   * TypeScript declares it, Python asserts against it, exactly as the ports
   * already work. A new model-driven node type that forgets the field now
   * fails a test instead of shipping.
   */
  readonly drives_model: boolean;

  /**
   * Does this node type accept a wired skill — i.e. does it declare the shared
   * `skill` input port (`src/nodes/skillLayer.ts`)?
   *
   * Emitted for exactly the reason `drives_model` is, and against the same
   * class of silence: the backend reads `plan.skill_bindings` and composes a
   * skill layer for five node types, while the editor declared the port on
   * two. The other three offered no way to wire the thing their compiler was
   * ready to read, and nothing failed.
   *
   * `backend/tests/test_skill_layer_contract.py` asserts this set against the
   * builders that actually read a skill binding, reading the compiler's own
   * source rather than a hand-kept list.
   */
  readonly accepts_skill: boolean;

  /**
   * Every key this node type's own configuration writes into `data` —
   * `Object.keys(defaultsFrom(fields))`, so a `file` field contributes its
   * `contentKey` too.
   *
   * `drives_model` and `accepts_skill` are two instances of one defect: a
   * compiler factory reading a `data` key the editor declares nowhere, which
   * raises nothing and simply yields `""` forever. Three of those shipped
   * (the model picker, the worker's rules mode, the supervisor's rules). This
   * generalises the guard: `backend/tests/test_data_key_contract.py` extracts
   * the literal keys each factory reads and asserts every one of them appears
   * here, so instance four fails a test instead of shipping.
   */
  readonly field_keys: readonly string[];

  /**
   * The field schema itself — key, kind, required, default, one line of
   * `hint` — for every field this node type declares.
   *
   * `field_keys` above answers "which keys may `data` carry"; this answers
   * "what does each one mean", which is what a client composing over MCP
   * needs and did not have (launch-readiness/18: `get_node_vocabulary`
   * published every port and no `data` schema, so a composing model had to
   * guess a tool's config — guess wrong and the document still validated
   * clean).
   *
   * Read straight off `definition.fields`, not through `defaultsFrom`: that
   * helper exists to flatten a `file` field's two written keys into a
   * defaults record, which is the wrong shape here — a client needs to see
   * the *field* (one card control) it can set, not the derived keys it
   * writes.
   */
  readonly fields: readonly GeneratedField[];
}

/**
 * One field of a node's declared configuration, as a composing client needs
 * to see it. Deliberately narrower than `FieldSchema`: no `validate`
 * function (host-language code, unserializable — the portability guardrail
 * this repo already applies to router predicates), no rendering hints
 * (`onCard`, `group`, `advanced`) that only matter to the editor's own UI.
 */
export interface GeneratedField {
  readonly key: string;
  readonly kind: string;
  readonly label: string;
  readonly hint: string;
  readonly required: boolean;
  readonly defaultValue: FieldValue;
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
  /**
   * Keys a saved document may still carry that no node type declares a field
   * for — today exactly one, the Grader's old `criteriaMode`, which
   * `skillLayer.ts` keeps as a *migration* fallback and deliberately never
   * re-declares as a second control.
   *
   * Emitted because the data-key contract has to tell a deliberate
   * compatibility read apart from a field nobody can write, and the difference
   * is knowledge the editor already holds. A hand-kept exclusion list on the
   * Python side would be the third declaration these contracts exist to
   * prevent — and worse, an easy place to silence a real defect.
   */
  readonly legacy_data_keys: readonly string[];
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

  // Every workflow-scoped family, not a named one (ticket 03). The generated
  // artifact is what the backend validates ports against, so a family missing
  // from here is a family whose edges the compiler cannot check — which is
  // exactly the "extending means editing the engine" this ticket removed.
  const workflowScoped = workflowScopedFamilies
    .list()
    .flatMap((family) => family.nodes.map((entry) => entry.definition));
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
        drives_model: definition.fields.some((field) => field.key === MODEL_FIELD_KEY),
        // Read off the resolved port list, not off a second declaration: the
        // port is the thing a document wires to, so the port is what the
        // contract is about. `direction` matters — `input.markdown` declares a
        // `skill` port too, but it is the provider half, the file being
        // offered rather than a prompt being shaped.
        accepts_skill: ports.some((port) => port.id === SKILL_PORT_ID && port.direction === 'in'),
        // Through `defaultsFrom` rather than `fields.map(f => f.key)`, because
        // the data record is what the backend reads and a `file` field writes
        // two keys into it. Sorted so the drift diff is about the catalogue.
        field_keys: Object.keys(defaultsFrom(definition.fields)).sort(),
        fields: definition.fields.map((field) => ({
          key: field.key,
          kind: field.kind,
          label: field.label ?? '',
          hint: field.hint ?? '',
          required: field.required ?? false,
          defaultValue: field.defaultValue ?? null,
        })),
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
    legacy_data_keys: [LEGACY_RULES_MODE_KEY, LEGACY_SKILL_BODY_KEY].sort(),
    port_types: portTypes,
    node_types: nodeTypes,
  };
}

/** The exact bytes written to disk, so the drift check compares like with like. */
export function serializePortSpecArtifact(artifact: NodeCatalogueArtifact): string {
  return `${JSON.stringify(artifact, null, 2)}\n`;
}
