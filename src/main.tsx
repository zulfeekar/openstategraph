import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@design/styles/index.css';
import { createWorkbench } from '@app/Workbench';
import { WorkbenchProvider } from '@app/WorkbenchContext';
import { seedDemoWorkflow, shouldSeedDemo } from '@app/seedDemo';
import { AppShell } from '@view/AppShell';
import { ErrorBoundary } from '@view/ErrorBoundary';

// Setup runs before any React tree exists, so `<ErrorBoundary>` below
// cannot catch a failure here — there is nothing mounted yet to catch it
// in. Found live, not speculatively: `seedDemoWorkflow` once threw
// synchronously (a node type it needs was not registered yet) and the
// result was a permanently blank `<div id="root">` with the real stack
// visible only in the console, which is not somewhere a user looks. This
// is the same fallback `<ErrorBoundary>` renders, applied to the one
// window it cannot reach.
let workbench: ReturnType<typeof createWorkbench>;
try {
  workbench = createWorkbench();
  // **The seed is a property of this checkout, not of the product**
  // (workflow-gallery ticket 41). A `pip install` opened onto a 13-node
  // "Chinook Assistant" nobody had asked for: absent from `/api/workflows`,
  // absent from the examples catalogue, present only as a string inside the
  // built bundle — and offering to Save itself. A first impression the
  // customer could not account for.
  //
  // It is gated rather than deleted because in a *checkout* the same document
  // is honest and load-bearing: `workflows/chinook-assistant/workflow.json`
  // is on disk and in `/api/workflows`, the e2e suite loads it as its fixture
  // (`e2e/canvas.smoke.spec.ts`, run against `npm run dev`, where this is
  // true), and several canvas tuning constants cite measurements of it.
  //
  // A shipped build opens on the empty canvas the Workflows drawer already
  // offers and describes as `Blank canvas`, with the START FROM templates and
  // the EXAMPLES shelf beside it — every one of them a document whose
  // provenance the customer can see. `import.meta.env.DEV` is a literal at
  // build time, so this also takes the document *out of the bundle*, which is
  // what `seedDemo.test.ts` asserts.
  //
  // **And asked for by name** (`install-experience` 23). Dev alone was not a
  // small enough audience: a stranger who clones this repository runs
  // `npm run dev`, and `http://localhost:5273/` came up holding those same 13
  // nodes before a byte of storage had been read — the first screen behind a
  // public repository, showing a workflow nobody had made. `/` is a blank
  // canvas now. `/?demo=1` is the fixture, and the e2e suite asks for it that
  // way, which is the only caller that needs it: Playwright starts the dev
  // server and no backend, so `?w=chinook-assistant` — how a person opens this
  // package in a checkout — is not available to it.
  if (import.meta.env.DEV && shouldSeedDemo(window.location.search)) {
    seedDemoWorkflow(workbench);
  }
  workbench.warmUp();
} catch (error) {
  const el = document.getElementById('root');
  if (el) {
    el.style.whiteSpace = 'pre-wrap';
    el.style.fontFamily = 'monospace';
    el.style.padding = '2rem';
    el.style.color = '#c00';
    const detail = error instanceof Error ? `${error.message}\n${error.stack}` : String(error);
    el.textContent = `OpenStateGraph failed to start.\n\n${detail}`;
  }
  throw error;
}

// Dev-only handle for poking at the model and the graph from the console.
// A canvas app is hard to debug through the DOM alone — being able to compare
// `model.nodeCount` against `graph.getElements().length` is how a model/graph
// divergence gets found in seconds instead of by bisecting handlers.
if (import.meta.env.DEV) {
  (window as unknown as { __openstategraph: unknown }).__openstategraph = workbench;
}

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

createRoot(container).render(
  // StrictMode double-invokes effects in development, which is exactly the
  // pressure the paper's mount/dispose cycle needs to survive — if the
  // canvas leaked a paper or a listener, this is where it would show.
  <StrictMode>
    <ErrorBoundary>
      <WorkbenchProvider workbench={workbench}>
        <AppShell />
      </WorkbenchProvider>
    </ErrorBoundary>
  </StrictMode>,
);
