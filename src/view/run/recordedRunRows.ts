import type { RecordedBurst, RecordedRun } from '@core/runtime/RecordedRunsClient';
import type { ActivityRow } from '../ask/traceTree';
import type { RunView } from './runView';

/**
 * A stored recording, as the rows the dock already draws.
 *
 * `memory-and-replay` 73, and it is the second half of `51`'s promise: **one
 * component, two data sources**. Live, the rows arrive frame by frame from the
 * SSE stream. Stored, they are built here from what `47` wrote down. The dock
 * is written against neither — it is written against `RunView` — so the lane
 * rules, the dash-for-no-clock rule and every fix a future defect earns are
 * learned once rather than twice.
 *
 * ## Why this converts rather than folds
 *
 * The obvious alternative was a second builder producing `RunLanes` straight
 * from bursts, and it was rejected for the reason the dock's own docstring
 * gives: a panel with two folds is two records, and the one nobody is looking
 * at is the one that drifts. A burst carries a node, a namespace, a kind and
 * two offsets, which is exactly what `TimelineRow` asks for — so the recording
 * is expressed in the vocabulary the fold already speaks, and the fold is
 * untouched.
 *
 * ## What a burst becomes, and what that claims
 *
 * Each burst is an **internal** row naming the loop step it came from —
 * `model` or `tools`, which is what `isModelStep`/`isToolStep` read — so the
 * bar it lands on is charged as a model call or a tool call rather than
 * staying the hollow default, and carries that burst's text as what the step
 * produced.
 *
 * A **completion** row is emitted once per contiguous stretch of bursts
 * sharing an owner, at that stretch's last chunk. That is the shape of the
 * live wire and not a simplification of it: an agent's loop streams many
 * `token` frames and reports **one** completion, so one bar. A real
 * `chinook-assistant` turn is nine bursts and one agent, and a completion row
 * per burst would draw it as nine bars of one node.
 *
 * Everything is attributed to `activeNode` — *the canvas node the run said was
 * working* — and not to `node`, which inside an agent is LangGraph's own loop
 * node. A real nine-burst `chinook-assistant` recording is eight `model` and
 * `tools` bursts and one `agent-sql`; read by `node` it draws a chart of the
 * machinery, and read by the owner it draws the node somebody put on a canvas.
 * `launch-readiness/108` settled that for the live chart and
 * `memory-and-replay/74` is the store keeping it. A recording older than that
 * ticket says `''`, and then `node` is the only name the bar has and it keeps
 * it — never a node inferred after the fact.
 *
 * A bar therefore runs from **the end of the previous burst to the last chunk
 * of this one**, which is a span and not a measurement — the same footing
 * every non-mount bar on this chart already stands on, and the reason
 * `measured` stays `false`. The gap between two bursts is real time that the
 * recording does not attribute to anybody: a tool executing, a graph hop, a
 * node that never streamed. Charging it forward to the node about to speak is
 * what the live path does with the identical evidence, and drawing the two
 * differently would make one workflow read as two.
 *
 * **Per burst, not per node.** `RunRecord.answer` is one string for the whole
 * run, so a revise loop's two drafts would show the second against the first
 * bar. The live fold keeps output per frame for exactly that reason, and this
 * keeps it per burst.
 *
 * ## A recording cannot tell a mount from an agent, and does not guess
 *
 * `RunBurst.namespace` is kept, and the first version of this module read it
 * the way the fold does — *a namespace is a mount* — because that is what
 * `buildTimeline` says. **Run against a real recording it drew the whole of
 * `chinook-assistant` as one hatched box**, because `create_agent` compiles
 * its own tool-calling loop into a subgraph and every burst of that run
 * carries `namespace: ["agent_sql:b65e7270-…"]`.
 *
 * The live fold is not wrong; it has more evidence. There, a namespaced frame
 * is `internal` and never opens a bar of its own, and a **mount** is known
 * because the run announces it — a `spawn` of kind `subgraph`, closed by a
 * `settled` (`memory-and-replay` 54 and 57). `47` records `token` frames and
 * nothing else, so neither of those is in this store, and an agent's namespace
 * and a mount's namespace are the same shape: `<node>:<uuid>`.
 *
 * So the namespace is deliberately **not** carried onto these rows. A
 * recording says which canvas node was working and what it produced; it does
 * not say that node was another document. Inventing the distinction from a
 * string's shape is exactly the kind of guess `52` forbids, and the cost of
 * not making it is one hatch — a mounted run's bursts still land on the mount
 * node's bar, because `activeNode` resolves to it.
 *
 * ## The size of a recording is bounded before it gets here
 *
 * `the-cost-of-one-more/20` left a replayed 80,000-frame recording as a known
 * unfinished case. It cannot arise on this path: `BURST_CAP` bounds a run at
 * 400 bursts *while it is being recorded*, so the largest recording this
 * function can be handed is 800 rows, and the last burst kept says `capped` so
 * a reader is told the recording ends there rather than that the run did.
 */

/** The loop step a burst's `kind` names, in the wire's own vocabulary. */
function loopStep(kind: string): string {
  return kind === 'tool' ? 'tools' : 'model';
}

/** Whose bar this burst belongs on — the run's own answer, else the only name it has. */
function owner(burst: RecordedBurst): string {
  return burst.activeNode || burst.node;
}

export function recordedRunRows(run: RecordedRun): readonly ActivityRow[] {
  const rows: ActivityRow[] = [];
  let open: RecordedBurst | null = null;
  const close = (): void => {
    if (open !== null) rows.push(completionRow(open));
    open = null;
  };
  for (const burst of run.bursts) {
    if (open !== null && owner(open) !== owner(burst)) close();
    rows.push(internalRow(burst));
    open = burst;
  }
  close();
  return rows;
}

function internalRow(burst: RecordedBurst): ActivityRow {
  return {
    node: loopStep(burst.kind),
    taskId: null,
    internal: true,
    // The arrival clock is a fact about a browser that was watching, and
    // nothing was. `0` rather than a fabricated gap: the timeline reads
    // `elapsedMs`, and this field's own docstring calls itself an
    // approximation of what a tab waited through.
    durationMs: 0,
    // The burst's **last** chunk, so the clock advances by the whole burst and
    // the bar is charged for all of it. Its first chunk buys nothing extra: a
    // second row at that offset would split one burst into two spans and count
    // one model call as two.
    elapsedMs: burst.lastMs,
    // Charged above the fold's `internal` gate, which is where a mounted
    // document's own answer already reaches its bar. A withheld burst is empty
    // because the recorder never held the bytes, and `null` is that absence.
    output: burst.text === '' ? null : burst.text,
    activeNode: owner(burst),
  };
}

function completionRow(burst: RecordedBurst): ActivityRow {
  return {
    node: owner(burst),
    taskId: null,
    internal: false,
    durationMs: 0,
    elapsedMs: burst.lastMs,
    // A withheld burst is empty because the recorder never held the bytes —
    // `_token_frame` empties the frame before it is built. `null` is that
    // absence, and the bar stays so the stall shows.
    output: burst.text === '' ? null : burst.text,
    activeNode: owner(burst),
  };
}

/**
 * The whole recording, as the snapshot the dock reads.
 *
 * `source: 'stored'` is the field that tells the dock this run has an end —
 * and therefore that a transport can honestly be offered — and it is the same
 * word the header already prints as *Stored run*. Nothing new is invented to
 * say what this is.
 */
export function recordedRunView(run: RecordedRun): RunView {
  return {
    source: 'stored',
    question: run.question,
    rows: recordedRunRows(run),
    // A stored run is never running. Not a default: it is the definition.
    running: false,
    threadId: run.threadId,
    usage: run.usage,
  };
}
