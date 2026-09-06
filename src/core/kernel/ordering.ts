/**
 * Canonical ordering for serialised output.
 *
 * `workflow.json` is git-tracked and read by humans in diffs and by coding
 * agents, so the same logical graph must always produce the same bytes.
 * Anything that reaches the file needs a total order that does not depend on
 * the sequence a user happened to build things in.
 */

/**
 * Compares ids the way a person reads them, so `node:agent-2` sorts before
 * `node:agent-10`.
 *
 * A plain lexical sort would order those the other way round, because `'1'`
 * precedes `'2'`. That is still *deterministic*, so it would satisfy a naive
 * determinism test while making the file order visibly wrong to anyone reading
 * a diff — a worse outcome than the original bug, because it looks correct.
 */
export function compareNatural(a: string, b: string): number {
  const CHUNK = /(\d+)|(\D+)/g;
  const left = a.match(CHUNK) ?? [];
  const right = b.match(CHUNK) ?? [];

  const shared = Math.min(left.length, right.length);
  for (let i = 0; i < shared; i += 1) {
    const l = left[i] ?? '';
    const r = right[i] ?? '';
    if (l === r) continue;

    const lNum = Number.parseInt(l, 10);
    const rNum = Number.parseInt(r, 10);
    const bothNumeric = !Number.isNaN(lNum) && !Number.isNaN(rNum);

    if (bothNumeric) {
      if (lNum !== rNum) return lNum - rNum;
      // Equal values, different text ("2" vs "02") — fall back to the raw
      // comparison so the order is still total.
      return l < r ? -1 : 1;
    }
    return l < r ? -1 : 1;
  }

  return left.length - right.length;
}

/** Returns a new array sorted by a natural comparison of the derived key. */
export function sortByIdNatural<T>(items: readonly T[], key: (item: T) => string): T[] {
  return [...items].sort((a, b) => compareNatural(key(a), key(b)));
}

/**
 * Rebuilds a record with its keys in sorted order.
 *
 * `JSON.stringify` emits object keys in insertion order, so a node whose
 * fields were edited in a different sequence would serialise differently
 * despite holding identical values. This is the second, less obvious source
 * of diff noise after row ordering.
 */
export function withSortedKeys<T>(record: Readonly<Record<string, T>>): Record<string, T> {
  const sorted: Record<string, T> = {};
  for (const key of Object.keys(record).sort()) {
    sorted[key] = record[key] as T;
  }
  return sorted;
}
