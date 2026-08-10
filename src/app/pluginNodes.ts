import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { FieldSchema } from '@core/model/contracts/fields';
import type { PluginToolCapability, PluginToolField } from '@core/runtime/WorkflowFileClient';
import { Err, type Result } from '@core/kernel/Result';
import {
  AbstractToolNodeModel,
  createToolExecutor,
  defineToolNode,
} from '@nodes/tools/AbstractToolNode';

/**
 * Installed-plugin tools become palette cards — register **PK-06**.
 *
 * **The gap.** A distribution that writes one
 * `[project.entry-points."openstategraph.tools"]` stanza has been *bindable*
 * since the entry-point work: `pip install`, and the runtime resolves
 * `tool.acme-ping`. Nothing put it in the editor, so a user could not wire the
 * thing they had just installed, and the author got no error — authoring an
 * atom is a two-place job and doing half of it was silent. "Extend without
 * forking" was half a promise in a documented, advertised seam.
 *
 * **What this is, and what it is not.** It is the mechanism
 * `registerDiscoveredCapabilities` already proves for a *workflow's own*
 * `tools/` folder, pointed at the other source: the backend reports what it
 * can bind, the editor registers a node type per capability at runtime, and no
 * TypeScript file is hand-written per tool. It is deliberately a **separate
 * module** from `nodes/workflowScoped.ts` because the two differ in the thing
 * that matters most about a node type — its lifetime:
 *
 * | | workflow-scoped | plugin (here) |
 * | --- | --- | --- |
 * | id | `<slug>/tools.<Class>` | the tool's own `node_type` |
 * | scope | `workflow` | `app` |
 * | lives until | another workflow is opened | the distribution is uninstalled |
 *
 * A plugin's tool is process-wide, so its `node_type` *is* its identity —
 * there is no slug to qualify it with, and the string the document holds must
 * be the string the runtime registry is keyed by.
 *
 * **Precedence is the runtime's, not ours.** Built-in < installed plugin <
 * workflow-local, exactly as `build_tool_registry` layers them. So a plugin
 * claiming `tool.web-search` *replaces* the bundled card — anything else would
 * show one tool on the canvas and run another. The replaced definition and
 * executor are remembered and restored when the plugin stops reporting: a
 * blind `unregister` would cost the editor a card it ships itself.
 */

class PluginToolNodeModel extends AbstractToolNodeModel {}

/** What we registered last time, and what each entry displaced. */
interface Displaced {
  readonly definition: INodeDefinition | undefined;
  readonly executor: INodeExecutor | undefined;
}

let registered = new Map<string, Displaced>();

/**
 * Registers one app-scoped node type per plugin-contributed tool, and
 * unregisters whatever the previous call left behind.
 *
 * Unconditional, like discovered capabilities and unlike Chinook's
 * usage-driven sync: the entire point is to make an installed-but-unwireable
 * capability *placeable*, not to react to one already placed. An empty list is
 * a real answer — plugins disabled, none installed, or a backend that predates
 * this — and correctly clears the previous registration.
 */
export function registerPluginCapabilities(
  capabilities: readonly PluginToolCapability[],
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
): void {
  const fresh = new Map<string, Displaced>();

  for (const [id, displaced] of registered) {
    if (capabilities.some((c) => nodeTypeOf(c) === id)) continue;
    if (displaced.definition) registry.nodeTypes.upsert(displaced.definition);
    else registry.nodeTypes.unregister(id);
    if (displaced.executor) executors.upsert(displaced.executor);
    else executors.unregister(id);
  }

  for (const capability of capabilities) {
    const id = nodeTypeOf(capability);
    if (!id) continue;
    // Remembered once, from the state *before* this module first touched the
    // id: re-reading it on a later refresh would remember our own card and
    // "restoring" it would leave the plugin's node behind forever.
    const displaced = registered.get(id) ?? {
      definition: registry.nodeTypes.get(id),
      executor: executors.get(id),
    };
    const { definition, executor } = createPluginToolNode(capability);
    registry.nodeTypes.upsert(definition);
    executors.upsert(executor);
    fresh.set(id, displaced);
  }

  registered = fresh;
}

/** A plugin tool's canvas identity — its `node_type`, with `id` as a fallback. */
function nodeTypeOf(capability: PluginToolCapability): string {
  return capability.nodeType || capability.id;
}

/** One capability as a connectable node type plus the executor fronting it. */
export function createPluginToolNode(capability: PluginToolCapability): {
  definition: INodeDefinition;
  executor: INodeExecutor;
} {
  const id = nodeTypeOf(capability);
  const label = capability.name || id;
  const definition = defineToolNode(
    {
      id,
      // `app`, not `workflow`: the palette's "This workflow" section warns
      // that a type vanishes when another workflow opens, and an installed
      // plugin does not. Saying otherwise would be a lie about exactly the
      // thing a user is deciding whether to rely on.
      scope: 'app',
      label,
      // The distribution is part of the description rather than a tooltip: a
      // card that appeared because of an unrelated `pip install` has to be
      // explicable from the palette, without opening a terminal.
      description: describe(capability),
      iconId: 'node-discovered-tool',
      accent: 'neutral',
      keywords: ['plugin', 'installed', 'tool', capability.distribution].filter(Boolean),
      defaultSize: { width: 260, height: 140 },
      fields: capability.fields.map(toFieldSchema),
    },
    PluginToolNodeModel as never,
  );

  const executor = createToolExecutor(id, {
    describeTool: () => ({
      name: label,
      description: capability.description,
      parameters: capability.argsSchema as never,
    }),
    invokeTool: () =>
      Promise.resolve(
        Err(
          `"${label}" runs on the backend, where ${capability.distribution || 'its distribution'} installed it — use Chat, not the canvas Run button.`,
        ) as Result<string, string>,
      ),
  });

  return { definition, executor };
}

function describe(capability: PluginToolCapability): string {
  const parts = [capability.description].filter(Boolean);
  if (capability.distribution) {
    parts.push(
      capability.replacesBuiltin
        ? `Installed by ${capability.distribution}, replacing the built-in tool of the same type.`
        : `Installed by ${capability.distribution}.`,
    );
  }
  return parts.join(' ');
}

/**
 * One declared field as a schema the editor renders.
 *
 * An unknown `kind` degrades to `text` rather than failing the card: a plugin
 * built against a newer editor must still be usable in an older one, and a
 * missing card is the exact failure this whole change exists to remove.
 */
function toFieldSchema(field: PluginToolField): FieldSchema {
  const base = {
    key: field.key,
    label: field.label || field.key,
    hint: field.hint || undefined,
  };
  switch (field.kind) {
    case 'textarea':
      return {
        ...base,
        kind: 'textarea',
        defaultValue: asText(field.defaultValue),
        placeholder: field.placeholder || undefined,
      };
    case 'toggle':
      return { ...base, kind: 'toggle', defaultValue: field.defaultValue === true };
    case 'select':
      return {
        ...base,
        kind: 'select',
        defaultValue: asText(field.defaultValue),
        options: field.options.map((option) => ({
          value: option.value,
          label: option.label || option.value,
        })),
      };
    default:
      return {
        ...base,
        kind: 'text',
        defaultValue: asText(field.defaultValue),
        placeholder: field.placeholder || undefined,
      };
  }
}

const asText = (value: string | number | boolean): string =>
  typeof value === 'string' ? value : String(value);

/** Exposed for tests — module-level registration would leak between them. */
export function forgetPluginNodes(): void {
  registered = new Map();
  warnings = [];
  listeners.clear();
}

// --------------------------------------------------------------------------
// The capability-warning channel, editor side.
//
// The backend already collects every capability that failed to load, every
// plugin that replaced a built-in, and every Python tool with no editor card
// at all, and reports them on the capabilities response. They arrive
// asynchronously — after a load, after a Refresh — so they need somewhere to
// live that a component can subscribe to. A store rather than a toast because
// a half-authored tool is a *standing* condition: it is still true after the
// toast fades, and the person who needs to read it may not have been looking.
// --------------------------------------------------------------------------

let warnings: readonly string[] = [];
const listeners = new Set<() => void>();

/** The whole truth from the last capabilities fetch. Replaces, never appends. */
export function setCapabilityWarnings(next: readonly string[]): void {
  warnings = next;
  for (const listener of listeners) listener();
}

export function capabilityWarnings(): readonly string[] {
  return warnings;
}

/** Subscribe, `useSyncExternalStore`-shaped. Returns the unsubscribe. */
export function onCapabilityWarningsChange(handler: () => void): () => void {
  listeners.add(handler);
  return () => listeners.delete(handler);
}
