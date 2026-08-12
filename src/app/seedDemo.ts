import type { Workbench } from './Workbench';
import { registerNodeTypesForRawDocument } from '@nodes/workflowScoped';
import envelope from '../../workflows/chinook-assistant/workflow.json';

/**
 * The workflow the editor opens with: **the shipped example itself**.
 *
 * This used to hand-build a Chinook showcase node by node, and that was the
 * defect the one-chinook ticket exists to fix. There were two Chinook
 * documents — `chinook-assistant`, which had the router, and
 * `chinook-nl-to-sql`, which did not — and this file seeded a third thing
 * again: a hand-written graph that mirrored the *routerless* one. So the
 * editor opened on an agent with no router in front of it, which is exactly
 * the graph the owner kept reporting on while the router lived in a document
 * they never saw.
 *
 * The fix is not "hand-build the right graph", it is **stop hand-building
 * one**. `workflows/chinook-assistant/workflow.json` is the single source of
 * truth for what the example *is*; anything typed here is a second copy of
 * that knowledge that drifts the first time either changes. CLAUDE.md's DRY
 * rule is about exactly this: duplication of knowledge is the defect.
 *
 * Loaded through `controller.document.importJSON`, the same path an explicit
 * "Load" and the autosave restore take — which is also what keeps the undo
 * stack empty, since replacing the document clears history by design. The
 * first Cmd-Z should undo the *user's* first edit, not dismantle the example.
 */
export function seedDemoWorkflow(workbench: Workbench): void {
  const { document } = envelope as { document: unknown };

  // Load-order rule, unchanged and still load-bearing: the serializer
  // silently skips nodes whose type is not registered yet, so the document's
  // workflow-scoped types (Chinook's three tools) have to be registered
  // *before* it is imported or all three cards and every edge touching them
  // vanish without an error. Inferred from the document rather than asserted
  // here — this file no longer knows which families the example uses.
  registerNodeTypesForRawDocument(document, workbench.registry, workbench.engine.executors);

  const result = workbench.controller.document.importJSON(JSON.stringify(document));
  if (!result.ok) {
    // Thrown, not swallowed: `main.tsx` renders a real stack for a failure
    // here, and a silently empty canvas at startup is far worse than a
    // visible error — nobody looks in the console at app load.
    throw new Error(`Failed to seed the shipped example: ${result.message}`);
  }
}
