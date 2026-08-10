import { beforeEach, describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import type { PluginToolCapability } from '@core/runtime/WorkflowFileClient';
import {
  capabilityWarnings,
  forgetPluginNodes,
  onCapabilityWarningsChange,
  registerPluginCapabilities,
  setCapabilityWarnings,
} from './pluginNodes';

const pluginTool = (overrides: Partial<PluginToolCapability> = {}): PluginToolCapability => ({
  id: 'tool.acme-ping',
  name: 'acme_ping',
  description: 'Answers with a pong.',
  argsSchema: {},
  nodeType: 'tool.acme-ping',
  distribution: 'osg-acme',
  fields: [],
  replacesBuiltin: false,
  ...overrides,
});

beforeEach(() => {
  forgetPluginNodes();
});

/**
 * Register PK-06: a tool an installed distribution ships was bindable by the
 * runtime and absent from the editor, so nobody could wire it. These are the
 * editor half — the backend half is `backend/tests/test_plugin_capabilities.py`.
 */
describe('registerPluginCapabilities', () => {
  it('puts an installed plugin’s tool in the palette', () => {
    const workbench = new Workbench();

    registerPluginCapabilities([pluginTool()], workbench.registry, workbench.engine.executors);

    const definition = workbench.registry.nodeTypes.get('tool.acme-ping');
    expect(definition).toBeDefined();
    expect(definition?.label).toBe('acme_ping');
    expect(workbench.engine.executors.get('tool.acme-ping')).toBeDefined();
  });

  it('registers it under the tool’s own node type, so a saved document binds', () => {
    // Unlike a workflow-local capability (whose id is `<slug>/tools.<Class>`),
    // a plugin tool's identity is process-wide: the string the document holds
    // and the string the runtime registry is keyed by must be the same one.
    const workbench = new Workbench();

    registerPluginCapabilities([pluginTool()], workbench.registry, workbench.engine.executors);

    expect(workbench.registry.nodeTypes.get('tool.acme-ping')?.id).toBe('tool.acme-ping');
  });

  it('marks it app-scoped, not workflow-scoped', () => {
    // The palette lifts `scope: 'workflow'` into a "This workflow" section
    // that warns the type vanishes when another workflow opens. An installed
    // plugin does not vanish, and saying it does would be a lie about
    // something a user is deciding whether to rely on.
    const workbench = new Workbench();

    registerPluginCapabilities([pluginTool()], workbench.registry, workbench.engine.executors);

    expect(workbench.registry.nodeTypes.get('tool.acme-ping')?.scope).toBe('app');
  });

  it('names the distribution on the card, so an unrelated pip install is explicable', () => {
    const workbench = new Workbench();

    registerPluginCapabilities([pluginTool()], workbench.registry, workbench.engine.executors);

    expect(workbench.registry.nodeTypes.get('tool.acme-ping')?.description).toContain('osg-acme');
  });

  it('renders the fields the plugin declared', () => {
    const workbench = new Workbench();

    registerPluginCapabilities(
      [
        pluginTool({
          fields: [
            {
              key: 'endpoint',
              label: 'Endpoint',
              kind: 'text',
              defaultValue: '',
              placeholder: 'https://acme.example/ping',
              hint: 'Where the ping goes.',
              options: [],
            },
          ],
        }),
      ],
      workbench.registry,
      workbench.engine.executors,
    );

    // Alongside the retry/timeout fields `defineNode` gives every node type —
    // the declared field joins the card, it does not replace the machinery.
    const fields = workbench.registry.nodeTypes.get('tool.acme-ping')?.fields ?? [];
    const endpoint = fields.find((f) => f.key === 'endpoint');
    expect(endpoint?.kind).toBe('text');
    expect(endpoint?.label).toBe('Endpoint');
  });

  it('falls back to a text control for a field kind this editor does not know', () => {
    // A plugin built against a newer editor must degrade, not disappear.
    const workbench = new Workbench();

    registerPluginCapabilities(
      [
        pluginTool({
          fields: [
            {
              key: 'colour',
              label: 'Colour',
              kind: 'colour-wheel',
              defaultValue: '',
              placeholder: '',
              hint: '',
              options: [],
            },
          ],
        }),
      ],
      workbench.registry,
      workbench.engine.executors,
    );

    expect(
      workbench.registry.nodeTypes.get('tool.acme-ping')?.fields?.find((f) => f.key === 'colour')
        ?.kind,
    ).toBe('text');
  });

  it('drops a plugin tool that no longer reports, without stranding it in the palette', () => {
    const workbench = new Workbench();
    registerPluginCapabilities([pluginTool()], workbench.registry, workbench.engine.executors);

    registerPluginCapabilities([], workbench.registry, workbench.engine.executors);

    expect(workbench.registry.nodeTypes.get('tool.acme-ping')).toBeUndefined();
    expect(workbench.engine.executors.get('tool.acme-ping')).toBeUndefined();
  });
});

/**
 * Precedence, as documented on both sides: built-in < installed plugin <
 * workflow-local. A plugin replacing a bundled tool is what installing one is
 * *for*; the editor must resolve it the same way the runtime does, or the card
 * would describe one tool and the run would execute another.
 */
describe('a plugin tool whose node type collides with a built-in', () => {
  const BUILTIN = 'tool.web-search';

  it('replaces the built-in card, matching what the runtime will bind', () => {
    const workbench = new Workbench();
    expect(workbench.registry.nodeTypes.get(BUILTIN)?.label).toBe('Web Search');

    registerPluginCapabilities(
      [
        pluginTool({
          id: BUILTIN,
          nodeType: BUILTIN,
          name: 'acme_web_search',
          replacesBuiltin: true,
        }),
      ],
      workbench.registry,
      workbench.engine.executors,
    );

    expect(workbench.registry.nodeTypes.get(BUILTIN)?.label).toBe('acme_web_search');
    expect(workbench.registry.nodeTypes.get(BUILTIN)?.description).toContain('osg-acme');
  });

  it('gives the built-in back when the plugin stops reporting', () => {
    // Unregistering blindly would delete a bundled node type the catalogue
    // registered at startup — a plugin uninstall must not cost the editor a
    // card it ships itself.
    const workbench = new Workbench();
    registerPluginCapabilities(
      [
        pluginTool({
          id: BUILTIN,
          nodeType: BUILTIN,
          name: 'acme_web_search',
          replacesBuiltin: true,
        }),
      ],
      workbench.registry,
      workbench.engine.executors,
    );

    registerPluginCapabilities([], workbench.registry, workbench.engine.executors);

    expect(workbench.registry.nodeTypes.get(BUILTIN)?.label).toBe('Web Search');
    expect(workbench.engine.executors.get(BUILTIN)).toBeDefined();
  });
});

/** The half-authored error: a message, not silence. */
describe('capability warnings', () => {
  it('are held for the palette to show, not dropped on the floor', () => {
    setCapabilityWarnings(['2 tools the runtime can bind have no editor card: a, b.']);

    expect(capabilityWarnings()).toEqual([
      '2 tools the runtime can bind have no editor card: a, b.',
    ]);
  });

  it('notify subscribers, so a warning that arrives after paint still shows', () => {
    let notified = 0;
    const stop = onCapabilityWarningsChange(() => (notified += 1));

    setCapabilityWarnings(['something is half-authored']);
    stop();

    expect(notified).toBe(1);
  });

  it('are replaced, never appended — the backend reports the whole truth each time', () => {
    setCapabilityWarnings(['first']);
    setCapabilityWarnings(['second']);

    expect(capabilityWarnings()).toEqual(['second']);
  });
});
