import { useSyncExternalStore } from 'react';
import { createPortal } from 'react-dom';
import { usePaperController, useWorkbench } from '@app/WorkbenchContext';
import { NodeCard } from './NodeCard';

/**
 * Renders every node's card into the DOM mount JointJS created for it.
 *
 * One component owning all the portals — rather than a React root per node —
 * means a single reconciliation pass per change, shared context, and no
 * per-node root to create and destroy as the user pans. The mount registry is
 * the external store; JointJS publishes mounts as it renders views, and this
 * component follows.
 */
export function NodeLayer() {
  const paper = usePaperController();
  const workbench = useWorkbench();

  // The mount registry is the *only* subscription here. Node identity
  // (add/remove) arrives through it, and everything else about a node is
  // watched by that node's own card — so an edit to one card cannot
  // re-render every other card through this component.
  const mounts = useSyncExternalStore(
    (onChange) => paper?.mounts.subscribe(onChange) ?? (() => undefined),
    () => paper?.mounts.entries() ?? EMPTY,
  );

  if (!paper) return null;

  return (
    <>
      {mounts.map(([nodeId, element]) => {
        const node = workbench.model.node(nodeId);
        // A mount can briefly outlive its node — the view is removed on the
        // next JointJS frame, so skip rather than crash.
        if (!node) return null;
        return createPortal(<NodeCard node={node} />, element, nodeId);
      })}
    </>
  );
}

const EMPTY: readonly [string, HTMLElement][] = [];
