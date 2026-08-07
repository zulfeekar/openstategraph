import { beforeEach, describe, expect, it } from 'vitest';
import type { Workbench } from '@app/Workbench';
import { makeWorkbench } from '@core/testing/fixtures';

/**
 * Workflow-level settings — ticket 36.
 *
 * The backend reads `document.settings.model` for its node → workflow →
 * default model resolution, and the tabular-analytics workflow ships one.
 * Until this existed, `toJSON()` emitted exactly `{version, name, nodes,
 * edges}`, so *opening a workflow in the editor and saving deleted its
 * settings* — silent data loss on the round trip.
 */
describe('workflow settings', () => {
  let workbench: Workbench;

  beforeEach(() => {
    workbench = makeWorkbench();
  });

  it('round-trips settings through export and import', () => {
    workbench.model.setSettings({ model: 'ollama:gpt-oss:120b-cloud' });
    const json = workbench.controller.document.exportJSON();

    const reloaded = makeWorkbench();
    const outcome = reloaded.controller.document.importJSON(json);

    expect(outcome.ok).toBe(true);
    expect(reloaded.model.settings).toEqual({ model: 'ollama:gpt-oss:120b-cloud' });
  });

  it('omits the key entirely when no settings exist', () => {
    // Canonical serialization: an empty object would be diff noise on every
    // existing document the moment the field shipped.
    const parsed = JSON.parse(workbench.controller.document.exportJSON()) as Record<
      string,
      unknown
    >;
    expect(parsed).not.toHaveProperty('settings');
  });

  it('loads the real tabular-analytics shape', () => {
    const outcome = workbench.controller.document.importJSON(
      JSON.stringify({
        version: 2,
        name: 'Video Game Sales Analytics',
        settings: { model: 'ollama:gpt-oss:120b-cloud' },
        nodes: [],
        edges: [],
      }),
    );
    expect(outcome.ok).toBe(true);
    expect(workbench.model.settings['model']).toBe('ollama:gpt-oss:120b-cloud');
  });

  it('clears stale settings when importing a document that has none', () => {
    workbench.model.setSettings({ model: 'anthropic:claude-opus-5' });
    const outcome = workbench.controller.document.importJSON(
      JSON.stringify({ version: 2, name: 'plain', nodes: [], edges: [] }),
    );
    expect(outcome.ok).toBe(true);
    expect(workbench.model.settings).toEqual({});
  });

  it('setSettings replaces rather than merges, and copies defensively', () => {
    const first = { model: 'a' };
    workbench.model.setSettings(first);
    first.model = 'mutated';
    expect(workbench.model.settings['model']).toBe('a');

    workbench.model.setSettings({ recursionLimit: 100 });
    expect(workbench.model.settings).toEqual({ recursionLimit: 100 });
  });

  it('announces the change so panels can react', () => {
    const events: string[] = [];
    workbench.model.onAny((type) => events.push(type));
    workbench.model.setSettings({ model: 'x' });
    expect(events).toContain('workflow:settings');
  });
});
