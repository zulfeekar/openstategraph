/**
 * Which *instance* of a reusable workflow is being addressed — ticket 42.
 *
 * A workflow package is a **class**: `chinook-assistant` is one definition on
 * disk, and every mount of it shares that definition. A mount node in a parent
 * document is an **instance**: it carries its own `data.overrides`, applied to
 * a copy at compile time and never written back
 * (`docs/decisions/mount-overrides.md`, and `apply_mount_overrides` in the
 * backend). Drag the package into two parents — or twice into one — and you
 * get two instances with independent props. That is `new Instance()`, and it
 * has been true since mount overrides shipped.
 *
 * What has been missing is a way to *name* one. `?w=` was a flat slug, which
 * names the class, so a drill-in could not be linked, reloaded, or told apart
 * from its sibling.
 *
 * ## The unit is the mount node id, not the slug
 *
 * `concierge/wf-music` is "the `chinook-assistant` instance mounted at
 * `wf-music` of `concierge`". A second mount of the same package is
 * `concierge/wf-other` — same class, different instance, different address.
 * Addressing by slug could not distinguish them, which is exactly the
 * distinction that makes an instance an instance.
 *
 * A bare `concierge` keeps its existing meaning: **open the class.** Two
 * spellings, two meanings, and every bookmark already in a browser still
 * resolves.
 *
 * ## Why this vocabulary and not a new one
 *
 * A run frame already names a node inside a mounted document this way — the
 * `path` field, canvas node ids outermost-in, shipped in ticket 34. Reusing it
 * for the address (and, next, for the terminal frame's keys) is the DRY rule
 * as CLAUDE.md states it: duplication of *knowledge* is the defect, and "how
 * do you name a node inside a mounted document" is one piece of knowledge that
 * had grown three spellings.
 *
 * Pure and framework-free, like the rest of `core/`: parsing an address is a
 * question about two strings, so nothing here knows about a model, a canvas or
 * a request.
 */

/** The separator between the root slug and each mount node id. */
const SEPARATOR = '/';

/**
 * A slug, as the backend defines one: lowercase alphanumerics and hyphens, no
 * separator of any kind. Mirrors `slugify`/`directory_for` in
 * `backend/openstategraph/api/workflow_store.py` — the authority — so a
 * malformed address is refused here and never becomes a request.
 */
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * A mount node id. Deliberately permissive about punctuation, because minted
 * ids really do contain colons and dots (`nextId('node', 'workflow.subgraph')`
 * → `node:workflow.subgraph-1`, see `core/kernel/id.ts`) and hand-authored
 * ones in shipped packages are plain (`wf-music`). The only characters that
 * cannot appear are the ones that would make the address ambiguous or
 * traversable.
 */
const SEGMENT = /^[^/\\\s]+$/;

/** Segments that are path traversal in every filesystem this could reach. */
const TRAVERSAL = new Set(['.', '..']);

export interface MountAddress {
  /** The root workflow's slug — the document the address is rooted in. */
  readonly root: string;
  /**
   * Mount node ids from the root inward. Empty means the address names the
   * root document itself, i.e. the class.
   */
  readonly mountPath: readonly string[];
}

/**
 * Parses `concierge/wf-music`, or `null` if the text cannot name an instance.
 *
 * **Refuses rather than repairs.** A lenient parser that trims a stray
 * separator or drops an empty segment turns a malformed link into a link that
 * opens the *wrong instance* — silently, and with the user's edits going
 * somewhere they did not intend. A `null` is recoverable; a plausible wrong
 * answer is not.
 */
export function parseMountAddress(raw: string): MountAddress | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  const segments = trimmed.split(SEPARATOR);
  const [root, ...mountPath] = segments;
  if (!root || !SLUG.test(root)) return null;

  for (const segment of mountPath) {
    if (!segment || !SEGMENT.test(segment) || TRAVERSAL.has(segment)) return null;
  }

  return { root, mountPath };
}

export function formatMountAddress(address: MountAddress): string {
  return [address.root, ...address.mountPath].join(SEPARATOR);
}

/**
 * One mount-path segment as a person should read it.
 *
 * A segment is a raw canvas node id — `node:workflow.subgraph-1` — and the
 * drill-in banner rendered it unchanged, so the bar a user reads to know where
 * they are said `Editing Untitled node:workflow.subgraph-1`
 * (consistency-sweep ticket 10). That is both an internal id on a user surface
 * and the leaked LangGraph name the lexicon forbids.
 *
 * The ordinal is the only part that identifies *which* mount, and it is the
 * part a reader can use: two mounts of one package are `mount 1` and
 * `mount 2`. Anything that does not end in an ordinal is returned untouched —
 * a label that invents a number it cannot see would be worse than a raw id.
 */
export function mountLabel(segment: string): string {
  const trimmed = segment.trim();
  const ordinal = /-(\d+)$/.exec(trimmed);
  return ordinal ? `mount ${ordinal[1]}` : trimmed;
}

/** Whether this address names a mount rather than the root document. */
export function isInstance(address: MountAddress): boolean {
  return address.mountPath.length > 0;
}

/**
 * The address one level out, or `null` at the root.
 *
 * The navigation trail is **derived** from the address rather than remembered
 * beside it. `drillStack` kept `{slug, name}` frames and deduped by slug, so a
 * chain passing through two mounts of one package collapsed into a single
 * frame and offered "Back" to the wrong place. Prefixes of an address cannot
 * make that mistake.
 */
export function parentAddress(address: MountAddress): MountAddress | null {
  if (!isInstance(address)) return null;
  return { root: address.root, mountPath: address.mountPath.slice(0, -1) };
}

/**
 * The address of the mount `mountId` *inside* this one — drilling in by one
 * level. `null` when the id could not be a segment, so a document with an
 * unaddressable node id fails loudly at the click rather than producing a
 * link that resolves somewhere else.
 */
export function childAddress(address: MountAddress, mountId: string): MountAddress | null {
  const id = mountId.trim();
  if (!id || !SEGMENT.test(id) || TRAVERSAL.has(id)) return null;
  return { root: address.root, mountPath: [...address.mountPath, id] };
}

export function addressEquals(a: MountAddress, b: MountAddress): boolean {
  return (
    a.root === b.root &&
    a.mountPath.length === b.mountPath.length &&
    a.mountPath.every((segment, index) => segment === b.mountPath[index])
  );
}
