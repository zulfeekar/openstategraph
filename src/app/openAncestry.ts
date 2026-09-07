import { readDrillStack } from '@app/drillStack';
import { getOpenSlug } from '@app/openWorkflow';
import { getOpenAddress } from '@app/openAddress';

/**
 * Which packages are already above whatever the editor has open.
 *
 * This is the app-side half of `mountAncestry`: `core/` asks for a trail during
 * a render, and the two facts that make one — the open **address** and the open
 * **class slug** — live in `sessionStorage`, which `core/` may not reach.
 *
 * Oldest first, which is what makes the refusal's chain read as the route that
 * produced the cycle rather than a set:
 *
 * 1. **The drill stack**, if anything is on it. It predates the address and is
 *    still written when a workflow is opened from the Workflows panel.
 * 2. **The address root.** `?w=concierge/wf-music` says the document on screen
 *    is a mount *inside* `concierge`, so `concierge` is above it — and this is
 *    the rung that matters, because drilling in is how a user gets deep enough
 *    to create a cycle they cannot see.
 * 3. **The open class slug**, the document itself. For a plain package this is
 *    the same string as the address root, hence the dedup.
 *
 * ## What this deliberately cannot see
 *
 * An address carries a root slug and then **mount ids**, not slugs
 * (`a/wf-one/wf-two`), so the class slug of an *intermediate* hop in a chain
 * three or more deep is not derivable here — only the backend's mounts endpoint
 * knows it. Those rungs are therefore missing from the trail.
 *
 * That is a gap in the right direction and it is the reason it is acceptable.
 * The server is the authority (`node_runtime.py::_subgraph`,
 * `api/mount_resolution.py`) and refuses every case; this only reports the
 * verdict earlier. Missing a rung costs an early warning. *Inventing* one would
 * refuse a mount the compiler would accept, leaving a user to fight the editor
 * with no way out — which is why the trail is built only from slugs actually
 * known here, and never guessed from a mount id.
 */
export function openAncestry(): readonly string[] {
  const address = getOpenAddress();
  const here = getOpenSlug();
  const rungs = [
    ...readDrillStack().map((frame) => frame.slug),
    ...(address ? [address.root] : []),
    ...(here ? [here] : []),
  ];
  // Insertion order preserved, so the chain still reads oldest first. A plain
  // package contributes its slug twice (address root and open slug) and must
  // not produce `concierge -> concierge -> concierge`.
  return [...new Set(rungs.filter((slug) => slug.trim() !== ''))];
}
