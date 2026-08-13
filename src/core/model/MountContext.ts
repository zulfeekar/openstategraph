import { formatMountAddress, isInstance, type MountAddress } from './MountAddress';

type Json = Record<string, unknown>;

/**
 * The document an instance's edits are written to — ticket 42, tranche 4.
 *
 * A mount node is an instance of a workflow package, and its own state is
 * `data.overrides`. So editing a field while `concierge/wf-music` is displayed
 * does not touch the `chinook-assistant` package at all: it writes
 * `wf-music`'s overrides, in `concierge`. The package stays the single source
 * of truth, sibling mounts keep their own values, and
 * `docs/decisions/mount-overrides.md`'s rejection of fork-on-configure holds.
 *
 * ## Only the root document is retained, because nesting composes as JSON
 *
 * The obvious design keeps each level's effective document and writes to the
 * nearest one. It is wrong twice over: an intermediate effective document is
 * *derived*, so it is not a thing that can be saved, and retaining several
 * would put two mutable documents in an editor built around one.
 *
 * The backend already showed the better shape. `apply_mount_overrides` applies
 * a mount's overrides to the child **before** the child's own mounts resolve,
 * so a grandparent expresses a grandchild's override as an override of the
 * parent's `overrides` field:
 *
 *     concierge.wf-music.overrides = { "wf-inner": { "overrides": { … } } }
 *
 * That is one nested write into the root package, at a path derived from the
 * address. The two ends agree by construction rather than by comment — the
 * composition order this relies on is pinned server-side by
 * `test_mount_effective_document`.
 *
 * The blob is stored as a **JSON string**, which is the one spelling the
 * inspector's textarea saves and the mount card's "n overridden" badge parses.
 * `apply_mount_overrides` accepts either, so the choice is about the editor's
 * own consistency rather than the runtime's.
 */
export class MountContext {
  constructor(
    readonly address: MountAddress,
    /** The root package document. Mutated in place; it is ours to hold. */
    readonly rootDocument: Json,
    /**
     * What this instance would run if it overrode nothing — served by
     * `?inherited=true`, because the override has already replaced the
     * inherited value in the document on screen and no amount of client-side
     * work can recover it. Optional: without it a field can still be *marked*
     * as overridden, only not reverted.
     */
    private readonly inheritedDocument?: Json,
  ) {
    if (!isInstance(address)) {
      throw new Error(`${formatMountAddress(address)} names a workflow, not a mount inside one`);
    }
  }

  /** The mount node id being displayed — the innermost segment. */
  get mountId(): string {
    return this.address.mountPath[this.address.mountPath.length - 1] ?? '';
  }

  /** Whether this instance says anything of its own about that field. */
  isOverridden(childNodeId: string, key: string): boolean {
    return this.readOverride(childNodeId, key) !== undefined;
  }

  /**
   * The package's own value for a field — what a revert puts back, and what
   * the inspector shows beside an overridden one. `undefined` when the
   * inherited document was not loaded, which a caller must treat as "cannot
   * revert" rather than as "the default is empty".
   */
  inheritedValue(childNodeId: string, key: string): unknown {
    const nodes = this.inheritedDocument?.['nodes'];
    if (!Array.isArray(nodes)) return undefined;
    const node = (nodes as Json[]).find((entry) => entry['id'] === childNodeId);
    const data = node?.['data'];
    return isJson(data) ? data[key] : undefined;
  }

  /** Whether a revert is possible at all — see `inheritedValue`. */
  get knowsInherited(): boolean {
    return this.inheritedDocument !== undefined;
  }

  readOverride(childNodeId: string, key: string): unknown {
    const blob = this.blob();
    const container = descend(blob, this.address.mountPath.slice(1), false);
    const fields = container?.[childNodeId];
    return isJson(fields) ? fields[key] : undefined;
  }

  writeOverride(childNodeId: string, key: string, value: unknown): void {
    const blob = this.blob();
    const container = descend(blob, this.address.mountPath.slice(1), true)!;
    const fields = isJson(container[childNodeId]) ? (container[childNodeId] as Json) : {};
    fields[key] = value;
    container[childNodeId] = fields;
    this.commit(blob);
  }

  /**
   * Back to the package default.
   *
   * Removes the key rather than writing an empty value, and prunes every
   * container it empties — including the mount's whole `overrides` field. An
   * override that is `null` is not "no override": `apply_mount_overrides`
   * would happily apply the `null` over the package's real value, and the
   * card would keep counting it.
   */
  clearOverride(childNodeId: string, key: string): void {
    const blob = this.blob();
    const container = descend(blob, this.address.mountPath.slice(1), false);
    const fields = container?.[childNodeId];
    if (!container || !isJson(fields)) return;
    delete fields[key];
    if (Object.keys(fields).length === 0) delete container[childNodeId];
    prune(blob, this.address.mountPath.slice(1));
    this.commit(blob);
  }

  /** This mount's overrides blob, parsed; `{}` when absent or unreadable. */
  private blob(): Json {
    const raw = this.mountNode().data?.['overrides'];
    if (isJson(raw)) return structuredClone(raw);
    if (typeof raw === 'string' && raw.trim()) {
      try {
        const parsed: unknown = JSON.parse(raw);
        if (isJson(parsed)) return parsed;
      } catch {
        // Malformed JSON someone hand-edited. Starting from `{}` would delete
        // it silently, so refuse instead — the inspector's own validator is
        // where a person is told about it.
        throw new Error(`The ${this.rootMountId()} mount's overrides are not valid JSON`);
      }
    }
    return {};
  }

  private commit(blob: Json): void {
    const node = this.mountNode();
    node.data ??= {};
    if (Object.keys(blob).length === 0) delete node.data['overrides'];
    else node.data['overrides'] = JSON.stringify(blob, null, 2);
  }

  private rootMountId(): string {
    return this.address.mountPath[0] ?? '';
  }

  private mountNode(): { data: Json } {
    const nodes = this.rootDocument['nodes'];
    const id = this.rootMountId();
    const found = Array.isArray(nodes)
      ? (nodes as Json[]).find((node) => node['id'] === id)
      : undefined;
    if (!found) {
      // The root package changed under an open instance. Inventing the node
      // would write an override nothing will ever read; saying so is the only
      // honest answer.
      throw new Error(`${this.rootDocument['name'] ?? 'the workflow'} no longer has a ${id} mount`);
    }
    return found as unknown as { data: Json };
  }
}

/**
 * Walk `[segment].overrides` once per nesting level below the first.
 *
 * `create: false` returns `undefined` at the first missing hop, so a read
 * never brings structure into existence as a side effect.
 */
function descend(blob: Json, segments: readonly string[], create: boolean): Json | undefined {
  let container = blob;
  for (const segment of segments) {
    let step = container[segment];
    if (!isJson(step)) {
      if (!create) return undefined;
      step = {};
      container[segment] = step;
    }
    const entry = step as Json;
    let nested = entry['overrides'];
    if (!isJson(nested)) {
      if (!create) return undefined;
      nested = {};
      entry['overrides'] = nested;
    }
    container = nested as Json;
  }
  return container;
}

/** Drops every container the last clear emptied, innermost first. */
function prune(blob: Json, segments: readonly string[]): void {
  if (segments.length === 0) return;
  const [head, ...rest] = segments as [string, ...string[]];
  const entry = blob[head];
  if (!isJson(entry)) return;
  const nested = entry['overrides'];
  if (isJson(nested)) {
    prune(nested, rest);
    if (Object.keys(nested).length === 0) delete entry['overrides'];
  }
  if (Object.keys(entry).length === 0) delete blob[head];
}

function isJson(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
