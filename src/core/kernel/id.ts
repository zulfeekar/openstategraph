/**
 * Identifier minting.
 *
 * Ids are prefixed and human-readable so a serialized workflow can be
 * diffed and debugged by eye (`node:agent-3`, `edge:7`) rather than being
 * a wall of UUIDs. Uniqueness only has to hold within one document.
 */

const counters = new Map<string, number>();

/** `nextId('node', 'agent')` → `node:agent-1`, `node:agent-2`, … */
export function nextId(kind: string, hint?: string): string {
  const key = hint ? `${kind}:${hint}` : kind;
  const next = (counters.get(key) ?? 0) + 1;
  counters.set(key, next);
  return hint ? `${kind}:${hint}-${next}` : `${kind}:${next}`;
}

/**
 * Re-seeds the counters from ids already present in a document, so ids
 * minted after an import cannot collide with imported ones.
 */
export function seedIds(existing: Iterable<string>): void {
  for (const id of existing) {
    const match = /^(.*)-(\d+)$/.exec(id);
    if (!match) continue;
    const [, key, num] = match;
    if (!key || !num) continue;
    const value = Number.parseInt(num, 10);
    if (Number.isFinite(value)) {
      counters.set(key, Math.max(counters.get(key) ?? 0, value));
    }
  }
}

/** Test/reset hook — also used when loading a fresh document. */
export function resetIds(): void {
  counters.clear();
}
