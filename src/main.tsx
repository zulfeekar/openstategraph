import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@design/styles/index.css';
import { createWorkbench } from '@app/Workbench';
import { WorkbenchProvider } from '@app/WorkbenchContext';
import { seedDemoWorkflow } from '@app/seedDemo';
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
  seedDemoWorkflow(workbench);
  workbench.warmUp();
} catch (error) {
  const el = document.getElementById('root');
  if (el) {
    el.style.whiteSpace = 'pre-wrap';
    el.style.fontFamily = 'monospace';
    el.style.padding = '2rem';
    el.style.color = '#c00';
    const detail = error instanceof Error ? `${error.message}\n${error.stack}` : String(error);
    el.textContent = `Dyflow failed to start.\n\n${detail}`;
  }
  throw error;
}

// Dev-only handle for poking at the model and the graph from the console.
// A canvas app is hard to debug through the DOM alone — being able to compare
// `model.nodeCount` against `graph.getElements().length` is how a model/graph
// divergence gets found in seconds instead of by bisecting handlers.
if (import.meta.env.DEV) {
  (window as unknown as { __dyflow: unknown }).__dyflow = workbench;
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
