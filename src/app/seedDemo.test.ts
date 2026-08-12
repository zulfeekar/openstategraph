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
 * workflow-scoped instead, the seed started throwing
 * `[nodeTypes] unknown id "tool.chinook-get-all-tables"` on every single app
 * load. The seed now imports the shipped `workflow.json` and registers the
 * document's own workflow-scoped types before importing it, which is the
 * same load-order rule stated once instead of per load path.
 *
 * The router assertion below is the one-chinook ticket, pinned. The editor
 * seeded a routerless graph for the whole life of the previous map, so the
 * owner was looking at a canvas that did not contain the thing under
 * discussion. That is a regression worth a test rather than a comment.
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

  it('seeds the router, between the input and the agents', () => {
    const workbench = new Workbench();
    seedDemoWorkflow(workbench);

    const types = workbench.model.nodes().map((n) => n.type);
    expect(types).toContain('route.classifier');
    expect(types).toContain('input.markdown');
    expect(types.filter((t) => t === 'agent.llm')).toHaveLength(3);
    // Nothing is mounted: the one example is one document.
    expect(types).not.toContain('workflow.subgraph');
  });

  it('seeds the whole shipped document, not a subset of it', () => {
    const workbench = new Workbench();
    seedDemoWorkflow(workbench);

    // A silently dropped node is the failure mode this guards: the
    // serializer skips unknown types with a warning rather than an error.
    expect(workbench.model.nodes()).toHaveLength(13);
    expect(workbench.model.name).toBe('Chinook Assistant');
  });

  it("leaves an empty undo stack, so the first Cmd-Z is the user's own edit", () => {
    const workbench = new Workbench();
    seedDemoWorkflow(workbench);

    expect(workbench.controller.history.canUndo).toBe(false);
  });
});
