import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@design/styles/index.css';
import { createWorkbench } from '@app/Workbench';
import { WorkbenchProvider } from '@app/WorkbenchContext';
import { seedDemoWorkflow } from '@app/seedDemo';
import { AppShell } from '@view/AppShell';

const workbench = createWorkbench();
seedDemoWorkflow(workbench);
workbench.warmUp();

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
    <WorkbenchProvider workbench={workbench}>
      <AppShell />
    </WorkbenchProvider>
  </StrictMode>,
);
