/**
 * What one run spawned, one entry per child, folded out of the frames the
 * panel already holds.
 *
 * `canvas-feels-right/07`. The limitation this exists to fix is
 * `launch-readiness/140`'s own: a `Send` fan-out creates **tasks, not canvas
 * nodes**, so three parallel workers all narrate into the one card that
 * dispatched them and a reader cannot see that three things are happening.
 * The overlay is a **pill per child**, and a pill is deliberately not a node:
 * nothing here is savable, nothing here is written to the model, and no
 * gesture on a pill reaches the graph.
 *
 * ## A pure fold over `ActivityRow`, and no new state
 *
 * `AskPanel` already records every frame as an `ActivityRow` — the spawn
 * moment as a `spawn` row, and every completed step with the `taskId` it
 * carried. So there is nothing to accumulate and nothing to keep in sync: the
 * pills are a *view* of the same rows the trace tree and the timeline read,
 * exactly as `liveLine.ts` and `timeline.ts` are views of them. A second
 * store of spawn state would be a second thing to get wrong on reconnect.
 *
 * ## Three rules, and each one is a frame this session measured
 *
 * The frames below were captured on 2026-08-28 against the real streaming
 * endpoint, because this surface has now fooled a green suite four times and
 * a fixture invented at the desk is how that happens.
 *
 * 1. **The announced parent is not always a canvas node.** `async-first/08`
 *    records the attribution rule as *the agent node that launched the task*,
 *    and `SpawnWatcher` implements it as the frame's `node_id`. For an
 *    orchestrator that is `lead1` and correct. For a **deep agent** the tool
 *    call is read off the agent's inner model step, so the frame said
 *    `parent: "model"` — a graph step, not a card. The namespace head is the
 *    evidence that survives (`agent1:c00c273d…`), and taking the part before
 *    the `:` is the same move `SpawnWatcher` itself makes for a `subgraph`
 *    spawn one branch above.
 * 2. **A mount gets no pill.** `kind: "subgraph"` announces a mounted
 *    workflow, which *is* a node in the saved document with a card of its
 *    own. A chip beside it would claim runtime-only-ness about the one child
 *    that is genuinely part of the file.
 * 3. **A frame joins a task only by its own id.** `__turn_reset__` rides the
 *    input node's frame as a real `taskId` and belongs to no spawn; matching
 *    on the owning node instead would hand a worker the question it never
 *    saw.
 *
 * ## What a popover can honestly show, per kind
 *
 * Measured, and it is not the same for all three:
 *
 * | kind | do that child's own frames reach this stream? |
 * | --- | --- |
 * | `fanout` | **yes** — `update` frames carry the same `taskId` the spawn announced |
 * | `subagent` | no — `create_deep_agent` hands the parent one `ToolMessage` |
 * | `async` | no — the desk's loop is outside every run context |
 *
 * So `reported` is a field rather than an assumption, and `taskAccountNote`
 * is what a reader sees instead of a blank box. Saying "its steps are not on
 * this stream" is the isolation rule stated on the surface; inventing an
 * account for it would be the shared-context lie the ticket forbids.
 */

/** The kinds that get a pill. `subgraph` is deliberately absent — see rule 2. */
export type SpawnedKind = 'fanout' | 'subagent' | 'async';

/**
 * The shape this fold needs from an activity row.
 *
 * Declared here rather than imported from `traceTree.tsx` for the reason
 * `timeline.ts` declares its own: this module is pure TypeScript with no
 * React in it, and a structural type keeps it that way while still accepting
 * the real rows.
 */
export interface SpawnedTaskRow {
  readonly node: string;
  readonly taskId: string | null;
  readonly namespace?: readonly string[];
  readonly output: string | null;
  readonly spawn?: {
    readonly kind: 'fanout' | 'subagent' | 'async' | 'subgraph';
    readonly label: string;
    readonly instruction: string;
  };
}

export interface SpawnedTask {
  /** Stable across re-folds — the React key and the popover's identity. */
  readonly key: string;
  /** The id the run itself uses. `null` when the frame carried none. */
  readonly taskId: string | null;
  /** The canvas node this child was launched from. */
  readonly owner: string;
  readonly kind: SpawnedKind;
  /** What to call it: archetype, or the declared subagent type. */
  readonly label: string;
  /** The brief it was given, as the spawn frame carried it. */
  readonly instruction: string;
  /** Its own account, oldest first — what `ThinkingStack` renders. */
  readonly lines: readonly string[];
  /**
   * Whether this run's stream ever carried a frame under this task's id.
   *
   * Not the same as `lines.length > 0`: a frame can come back carrying an
   * empty output, and "it reported and said nothing" is a different fact
   * from "nothing about it ever reached this stream".
   */
  readonly reported: boolean;
  /**
   * Whether this child outlives the run that launched it.
   *
   * True only for `async`, and it is the whole reason `async-first/08` gave
   * that launch a kind of its own: the other two end when this run ends, so
   * a finished run is a finished child. A background worker's answer arrives
   * on a *later* turn, which is why nothing here ever calls it finished.
   */
  readonly detached: boolean;
}

/**
 * The canvas node a spawn belongs to — never the announced parent alone.
 *
 * Exported because it is rule 1, and a rule inlined into a fold is a rule
 * nobody can test on its own. `launch-readiness/105` is the standing reason.
 */
export function spawnOwner(
  parent: string,
  namespace: readonly string[] | undefined,
  hasNode: (id: string) => boolean,
): string {
  if (parent && hasNode(parent)) return parent;
  const head = namespace?.[0] ?? '';
  // `agent1:c00c273d-…` — the mounted node, then LangGraph's checkpoint id.
  const mounted = head.split(':')[0] ?? '';
  if (mounted && hasNode(mounted)) return mounted;
  return parent;
}

/**
 * Every child this run spawned, in the order the run announced them.
 *
 * `hasNode` answers whether an id names a node on the open document — the
 * same question `frameTarget` is asked, and for the same reason: a frame's
 * own claim about where it is has been wrong before.
 */
export function spawnedTasks(
  rows: readonly SpawnedTaskRow[],
  hasNode: (id: string) => boolean,
): readonly SpawnedTask[] {
  const order: string[] = [];
  const byKey = new Map<string, { task: SpawnedTask; lines: string[] }>();
  const byTaskId = new Map<string, string>();
  let anonymous = 0;

  for (const row of rows) {
    const detail = row.spawn;
    if (!detail) continue;
    if (detail.kind === 'subgraph') continue;

    const taskId = row.taskId ?? null;
    // A run can legitimately re-announce a spawn (a reconnect, a replayed
    // row); the same id is the same child, never a second pill.
    if (taskId && byTaskId.has(taskId)) continue;

    const key = taskId ?? `${row.node}/${detail.label}/${anonymous++}`;
    if (byKey.has(key)) continue;
    if (taskId) byTaskId.set(taskId, key);
    order.push(key);
    byKey.set(key, {
      lines: [],
      task: {
        key,
        taskId,
        owner: spawnOwner(row.node, row.namespace, hasNode),
        kind: detail.kind,
        label: detail.label,
        instruction: detail.instruction,
        lines: [],
        reported: false,
        detached: detail.kind === 'async',
      },
    });
  }

  for (const row of rows) {
    if (row.spawn) continue;
    const taskId = row.taskId;
    if (!taskId) continue;
    const key = byTaskId.get(taskId);
    if (!key) continue;
    const entry = byKey.get(key);
    if (!entry) continue;
    entry.task = { ...entry.task, reported: true };
    const line = (row.output ?? '').trim();
    if (line) entry.lines.push(line);
  }

  return order.map((key) => {
    const entry = byKey.get(key)!;
    return { ...entry.task, lines: entry.lines };
  });
}

/**
 * What to say in place of an account that does not exist.
 *
 * Empty once the child's own frames are here, because then the account *is*
 * the answer and a sentence explaining it would be noise.
 */
export function taskAccountNote(task: {
  readonly kind: SpawnedKind;
  readonly reported: boolean;
}): string {
  if (task.reported) return '';
  switch (task.kind) {
    case 'async':
      return (
        'This worker runs in the background and the run does not wait for it. ' +
        'It was given the brief above and nothing else about this conversation; ' +
        'its answer is collected on a later message.'
      );
    case 'subagent':
      return (
        'This helper was given the brief above and nothing else about this conversation. ' +
        'It reports back as a single result, so its own steps are not on this run’s stream.'
      );
    case 'fanout':
      return 'Nothing has come back under this task yet.';
  }
}
