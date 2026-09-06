import { describe, expect, it } from 'vitest';
import { makeWorkbench, TYPE } from './fixtures';

/**
 * Harness smoke tests.
 *
 * These exist to fail loudly if the *test setup* breaks, so a genuine
 * regression elsewhere is never misread as a broken alias or a missing
 * registration.
 */
describe('test harness', () => {
  it('resolves path aliases', async () => {
    const module = await import('@core/kernel/geometry');
    expect(typeof module.snap).toBe('function');
  });

  it('stands up a workbench with no DOM', () => {
    const workbench = makeWorkbench();
    expect(workbench.model.nodeCount).toBe(0);
    expect(workbench.controller.history.canUndo).toBe(false);
  });

  it('registers the full node catalogue', () => {
    const workbench = makeWorkbench();
    const registered = workbench.registry.nodeTypes.list().map((definition) => definition.id);
    for (const typeId of Object.values(TYPE)) {
      expect(registered).toContain(typeId);
    }
  });

  it('registers an executor for every executable node type', () => {
    const workbench = makeWorkbench();
    const executors = workbench.engine.executors.list().map((executor) => executor.id);
    const executable = workbench.registry.nodeTypes
      .list()
      .filter((definition) => definition.kind === 'standard')
      .map((definition) => definition.id);

    // A standard node with no executor would be silently skipped at run time
    // rather than failing, so the pairing is worth asserting.
    expect(executable.length).toBeGreaterThan(0);
    for (const typeId of executable) {
      expect(executors).toContain(typeId);
    }
  });

  it('gives each workbench an isolated model', () => {
    const a = makeWorkbench();
    const b = makeWorkbench();
    a.model.setName('first');
    expect(b.model.name).not.toBe('first');
  });
});
