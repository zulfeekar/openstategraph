import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { Workbench } from './Workbench';
import { DEMO_URL_PARAM, seedDemoWorkflow, shouldSeedDemo } from './seedDemo';

const repoRoot = join(__dirname, '..', '..');

/**
 * The newest mtime anywhere under `dir`, so a tree can be compared to a tree.
 *
 * `skipTests` exists because the comparison is "is the bundle built from the
 * current source" and **a test file is not source the bundle contains**.
 * Without it, editing any `*.test.ts` marks `dist/` stale and the suite
 * demands a rebuild that would change nothing in the output — a guard that
 * cries wolf gets deleted, which is the failure mode ticket 47 is about.
 */
function newestMtime(dir: string, skipTests = false): number {
  let newest = 0;
  for (const entry of readdirSync(dir)) {
    if (skipTests && /\.test\.tsx?$/.test(entry)) continue;
    const full = join(dir, entry);
    const stat = statSync(full);
    newest = Math.max(newest, stat.isDirectory() ? newestMtime(full, skipTests) : stat.mtimeMs);
  }
  return newest;
}

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
    const guarded =
      /if \(import\.meta\.env\.DEV && shouldSeedDemo\(window\.location\.search\)\) \{\s*\n\s*seedDemoWorkflow\(workbench\);/;

    expect(main).toContain('seedDemoWorkflow(workbench)');
    expect(main).toMatch(guarded);
    expect(main.match(/seedDemoWorkflow\(workbench\)/g)).toHaveLength(1);
  });

  it('leaves no workflow document inside the built assets', (ctx) => {
    const assets = join(repoRoot, 'dist', 'assets');

    // Ticket 47 named two faults here and they pull opposite ways: a **stale**
    // `dist/` passed silently, and requiring a fresh one couples `npm test` to
    // having run `npm run build`. Skipping — loudly, with the reason — settles
    // both. A bundle that cannot be checked now reports "not checked" instead
    // of "clean", and editing a source file no longer reddens the suite for a
    // reason that has nothing to do with the edit.
    //
    // The guarantee does not rest on this running. `seeds only under
    // import.meta.env.DEV` above is the source-level assertion, and it needs
    // no build; the wheel cannot be built without a current `dist/`
    // (backend/hatch_build.py), and CI builds one. This is the belt to that
    // pair of braces, and it is honest about when it is absent.
    if (!existsSync(assets)) {
      ctx.skip('dist/ is missing — run `npm run build`. Checked in CI and at wheel-build.');
      return;
    }
    if (newestMtime(join(repoRoot, 'dist')) < newestMtime(join(repoRoot, 'src'), true)) {
      ctx.skip('dist/ is older than src/ — would be checking a stale bundle. Run `npm run build`.');
      return;
    }

    const offenders = readdirSync(assets)
      .filter((name) => name.endsWith('.js'))
      .filter((name) => readFileSync(join(assets, name), 'utf8').includes('Chinook Assistant'));

    expect(offenders).toEqual([]);
  });
});

/**
 * `install-experience` 23 — **the checkout's fixture is not the checkout's
 * front door either.**
 *
 * Ticket 41 took this document out of the *shipped bundle* and stopped there,
 * which was the whole of the problem it could see: a customer met a 13-node
 * graph they had not made. In a checkout the seed stayed unconditional, so
 * `http://localhost:5273/` — no `?w=` of any kind — came up holding Chinook
 * Assistant, 13 nodes and 17 links, before a single byte of storage had been
 * read. That is the document the owner reported, and the counts identify it
 * exactly.
 *
 * A stranger cloning the repository runs `npm run dev`, so "only in a
 * checkout" is not a smaller audience than the wheel's — it is the audience
 * the README sends here. Landing inside somebody else's workflow is the same
 * first impression ticket 41 fixed, on the path more people take.
 *
 * ## Why gated rather than deleted
 *
 * The seed still earns its keep, for one reason and it is worth stating
 * plainly: it is the **only** way the e2e suite gets a populated canvas with
 * no backend running. Playwright's `webServer` starts `npm run dev` and
 * nothing else, so `?w=chinook-assistant` — which is how a *person* opens this
 * package in a checkout, and what the burst specs already use against the
 * supervised stack — would make the smoke suite depend on a Python process it
 * does not start.
 *
 * So the document stays, and the *default* moves. `/` is a blank canvas;
 * `/?demo=1` is the fixture, dev-only exactly as before, and the e2e suite
 * asks for it by name. A fixture that has to be asked for cannot be mistaken
 * for a product.
 */
describe('the demo is opt-in, even in a checkout', () => {
  it('does not seed a bare address', () => {
    expect(shouldSeedDemo('')).toBe(false);
    expect(shouldSeedDemo('?')).toBe(false);
  });

  it('does not seed a deep link, which names its own document', () => {
    // `?w=` is answered by the load path, and seeding underneath it would put
    // 13 nodes on the canvas for the half-second before the fetch lands.
    expect(shouldSeedDemo('?w=chinook-assistant')).toBe(false);
  });

  it('seeds when asked for by name, with or without a value', () => {
    expect(shouldSeedDemo(`?${DEMO_URL_PARAM}`)).toBe(true);
    expect(shouldSeedDemo(`?${DEMO_URL_PARAM}=1`)).toBe(true);
    expect(shouldSeedDemo(`?w=chinook-assistant&${DEMO_URL_PARAM}=1`)).toBe(true);
  });

  it('is the parameter the e2e suite actually asks for', () => {
    // The one pairing nothing else can check: a rename here that missed the
    // specs would leave every smoke test waiting on a node that never appears,
    // and the failure would read as a canvas bug.
    for (const spec of ['canvas.smoke.spec.ts', 'copyTextOutOfTheEditor.spec.ts']) {
      const source = readFileSync(join(repoRoot, 'e2e', spec), 'utf8');
      expect(source).toContain(`page.goto('/?${DEMO_URL_PARAM}=1')`);
    }
  });
});
