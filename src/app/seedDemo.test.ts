import { describe, expect, it } from 'vitest';
import { Workbench } from './Workbench';
import { seedDemoWorkflow } from './seedDemo';

/**
 * `seedDemoWorkflow` runs at app startup, before any React tree exists —
 * a real crash there is a permanently blank `<div id="root">`, since
 * `<ErrorBoundary>` (main.tsx) has nothing mounted yet to catch it in.
 *
 * Found exactly this way, live: once Chinook's tools stopped being
 * registered in the global catalogue (`registerNodeCatalogue`) and became
 * workflow-scoped instead, this function — which seeds a Chinook showcase
 * by writing straight to the model before any document exists — started
 * throwing `[nodeTypes] unknown id "tool.chinook-get-all-tables"` on every
 * single app load. `seedDemoWorkflow` now calls `registerChinookNodes`
 * itself first; this pins that it actually works on a workbench that has
 * not touched Chinook at all yet, which is the exact state a fresh
 * `new Workbench()` is in.
 */
describe('seedDemoWorkflow', () => {
  it('does not throw on a fresh workbench with no Chinook nodes registered yet', () => {
    const workbench = new Workbench();
    expect(() => seedDemoWorkflow(workbench)).not.toThrow();
  });

  it('seeds a document that actually includes the Chinook tool nodes', () => {
    const workbench = new Workbench();
    seedDemoWorkflow(workbench);

    const types = workbench.model.nodes().map((n) => n.type);
    expect(types).toContain('tool.chinook-get-all-tables');
    expect(types).toContain('tool.chinook-get-schema');
    expect(types).toContain('tool.chinook-execute-sql');
  });

  it("leaves an empty undo stack, so the first Cmd-Z is the user's own edit", () => {
    const workbench = new Workbench();
    seedDemoWorkflow(workbench);

    expect(workbench.controller.history.canUndo).toBe(false);
  });
});
