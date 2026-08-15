import type { IPaperFeature } from './IPaperFeature';
import { PanZoomFeature } from './PanZoomFeature';
import { SelectionFeature } from './SelectionFeature';
import { DragCommitFeature } from './DragCommitFeature';
import { SnaplinesFeature } from './SnaplinesFeature';
import { FrameOnLoadFeature } from './FrameOnLoadFeature';
import { LinkToolsFeature } from './LinkToolsFeature';
import { WaypointCommitFeature } from './WaypointCommitFeature';
import { KeyboardFeature, createDefaultShortcuts, type Shortcut } from './KeyboardFeature';
import { ConnectionFeature } from './ConnectionFeature';

/**
 * The features `PaperController` installs, and the two it keeps a handle on.
 *
 * `keyboard` and `connection` are named because the controller exposes them
 * (`shortcuts`, `observeConnectionRejections`); everything else it only
 * installs and disposes.
 */
export interface DefaultFeatureSet {
  /** In install order — the order features see the paper in. */
  readonly all: readonly IPaperFeature[];
  readonly keyboard: KeyboardFeature;
  readonly connection: ConnectionFeature;
}

/**
 * The default canvas behaviour, as one list.
 *
 * Extracted from `PaperController`'s constructor so the list is a value
 * rather than a literal buried in a composition root that needs a DOM and a
 * live JointJS paper to reach. `featureDisposal.test.ts` installs and
 * disposes exactly this set against counting targets, which is what makes
 * the `IPaperFeature` teardown invariant testable for *every* feature
 * instead of the ones someone remembered to name — a raw
 * `addEventListener` in `SelectionFeature` survived a hundred canvas
 * rebuilds precisely because nothing enumerated the list.
 */
export function createDefaultFeatures(
  options: { readonly shortcuts?: readonly Shortcut[] } = {},
): DefaultFeatureSet {
  const panZoom = new PanZoomFeature();
  const keyboard = new KeyboardFeature(createDefaultShortcuts(options.shortcuts ?? []));
  const connection = new ConnectionFeature();

  return {
    all: [
      panZoom,
      new SelectionFeature(panZoom),
      new DragCommitFeature(),
      new SnaplinesFeature(),
      new FrameOnLoadFeature(),
      connection,
      new LinkToolsFeature(),
      new WaypointCommitFeature(),
      keyboard,
    ],
    keyboard,
    connection,
  };
}
