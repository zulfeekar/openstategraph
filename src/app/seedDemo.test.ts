import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { Workbench } from './Workbench';
import { seedDemoWorkflow } from './seedDemo';

const repoRoot = join(__dirname, '..', '..');

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
 *
 * **What it is no longer.** Workflow-gallery ticket 41: this document is the
 * *checkout's* fixture, not the product's first screen. A `pip install`
 * opened onto it — 13 nodes named "Chinook Assistant", absent from
 * `/api/workflows` and from the examples catalogue, existing only as a string
 * in the shipped bundle, with a Save button inviting the customer to adopt
 * it. `main.tsx` now seeds only under `import.meta.env.DEV`, and the last
 * describe block below is what holds that.
 */
describe('seedDemoWorkflow', () => {
  it('seeds a real document on a fresh workbench, not merely without throwing', () => {
    // `not.toThrow()` was the whole assertion, and this document is the
    // fixture the entire e2e suite loads — a seed that quietly did nothing
    // would pass it (reviews-2026-08-14 ticket 09).
    const workbench = new Workbench();

    expect(() => seedDemoWorkflow(workbench)).not.toThrow();
    expect(workbench.model.nodes().length).toBeGreaterThan(2);
    expect(workbench.model.edges().length).toBeGreaterThan(0);
    expect(workbench.model.name.trim()).not.toBe('');
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

/**
 * Ticket 41's own assertions: the seed is a development fixture, and a
 * shipped build must carry no trace of it.
 *
 * Two tests, because they fail for different reasons and only one of them can
 * run everywhere. The source gate is the *cause* and runs on every `npm test`;
 * the bundle assertion is the *claim the ticket makes* and needs a build to
 * have happened, so it says so rather than passing vacuously.
 */
describe('the shipped bundle carries no example document', () => {
  it('leaves a shipped build on an empty, neutrally-named canvas', () => {
    // What `main.tsx` produces when the guard is false. Not "a different
    // document" — no document, which is the `Blank canvas` the Workflows
    // drawer already offers and explains, with the START FROM templates and
    // the EXAMPLES shelf beside it.
    const workbench = new Workbench();

    expect(workbench.model.nodes()).toHaveLength(0);
    expect(workbench.model.edges()).toHaveLength(0);
    // A generic name the customer can account for, not a package name they
    // have never heard of. The Save button reads "Save AI Workflow", which is
    // an offer to name their own thing rather than to adopt someone else's.
    expect(workbench.model.name).toBe('AI Workflow');
  });

  it('seeds only under import.meta.env.DEV', () => {
    // Read rather than executed: `main.tsx` mounts React against a real DOM
    // and this suite runs in node. What matters is structural anyway — the
    // guard has to be a build-time literal for the document to be dropped
    // from the bundle at all, so a runtime check would prove nothing.
    const main = readFileSync(join(repoRoot, 'src', 'main.tsx'), 'utf8');
    const guarded = /if \(import\.meta\.env\.DEV\) \{\s*\n\s*seedDemoWorkflow\(workbench\);/;

    expect(main).toContain('seedDemoWorkflow(workbench)');
    expect(main).toMatch(guarded);
    expect(main.match(/seedDemoWorkflow\(workbench\)/g)).toHaveLength(1);
  });

  it('leaves no workflow document inside the built assets', () => {
    const assets = join(repoRoot, 'dist', 'assets');
    // `dist/` is a build output, not a checked-in file. A missing one means
    // this claim has not been checked, which is not the same as it holding —
    // and the wheel cannot be built without it (backend/hatch_build.py), so
    // the artifact a customer installs has always been through this.
    expect(existsSync(assets), 'run `npm run build` first — dist/ is missing').toBe(true);

    const offenders = readdirSync(assets)
      .filter((name) => name.endsWith('.js'))
      .filter((name) => readFileSync(join(assets, name), 'utf8').includes('Chinook Assistant'));

    expect(offenders).toEqual([]);
  });
});
