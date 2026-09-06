/**
 * Which node types are **mounts** — a card that stands for another workflow's
 * whole graph rather than for one step.
 *
 * Declared once, here, because three places need the same fact and none of
 * them may own a private copy: `nodeBodyRegistry` registers the composition
 * body from it, `NodeCard` reads it to badge and tint the card, and the tests
 * assert against it. That is the DRY rule as written in CLAUDE.md.
 *
 * It is a list of one since schema v3 — `team.workflow` collapsed into
 * `workflow.subgraph` (production-ready ticket 16) — and stays a list because
 * what it declares is the *category*, not a count. A registered plugin mount
 * would join it without reopening any of the three readers.
 */
export const MOUNT_TYPES: readonly string[] = ['workflow.subgraph'];

/** Whether a node type id is a mount rather than an ordinary atom. */
export function isMountType(nodeTypeId: string): boolean {
  return MOUNT_TYPES.includes(nodeTypeId);
}

/**
 * What the badge says — and, just as importantly, what it does not.
 *
 * It states the **kind**, not the shape: *there is a graph in here*. That is
 * true of every mount, whatever the child document contains,
 * and it is knowable from the node type alone — no fetch, nothing to go stale,
 * nothing to be wrong about while a slug is still resolving.
 *
 * Stating the *shape* instead ("loop") was the tempting alternative and is a
 * lie on half the cards: only a mount whose child's grader has a wired
 * `revise` edge loops, and most do not. That claim already has an owner — `summarizeComposition` derives it and the census line
 * prints "loops until its grader passes" when, and only when, it holds. A
 * second, less careful loop claim in the header would be the same fact said
 * twice with one of the two eventually wrong.
 *
 * One word, one vocabulary: the chip is the `.node__scope` chip
 * (`node__chip`), not a second badge system.
 */
export const MOUNT_BADGE = {
  label: 'graph',
  title:
    'This card is a mount: it runs another workflow — a whole graph of nodes — as one step. Expand the disclosure below to see inside, or use Edit to open it.',
} as const;
