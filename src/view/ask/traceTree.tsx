import { useMemo } from 'react';
import type { RunResult } from '@core/runtime/RuntimeClient';
import { RichText } from '@view/common/RichText';

/**
 * The execution trace tree (ticket 63), extracted from AskPanel (ticket 72):
 * the model of a run's steps, the nesting rule, the JSON export, and the
 * expandable view. AskPanel keeps the *streaming* concern; this module owns
 * the *record* of what streamed.
 */
export interface ActivityRow {
  readonly node: string;
  /** Distinguishes concurrently dispatched worker instances (ticket 27). */
  readonly taskId: string | null;
  /** A step inside a node's own loop (model call, tool, middleware) —
   * rendered as a tree child, never a top-level row (ticket 63). */
  readonly internal: boolean;
  /** LangGraph's checkpoint namespace — non-empty only inside a true nested
   * subgraph (a mounted Workflow or Team). Carried so the timeline can
   * collapse a whole subgraph to one lane; the trace tree does not use it,
   * because its own nesting rule is positional (see `buildTrace`). */
  readonly namespace?: readonly string[];
  /** Wall-clock gap since the previous frame — the same honest
   * approximation the Inspector's duration badge uses. */
  readonly durationMs: number;
  readonly output: string | null;
  /**
   * Where this frame was, on every canvas it touched (ticket 34) — see the
   * stream's `path` field and `frameTarget`.
   *
   * Kept on the row, not only consumed as the frame arrives, because the
   * document under the run can *change*: opening a mount mid-run swaps the
   * canvas for one that has seen none of this run. Replaying these rows is
   * what lets the newly-opened document catch up to where the run already is,
   * rather than starting from a blank diagram.
   */
  readonly path?: readonly string[];
  /**
   * Which document each entry of `path` belongs to — carried for the same
   * reason `path` is, and useless without it.
   *
   * `frameTarget`'s exact rule matches the open document by *slug*, because
   * ids are unique only within a document and the shipped pair proves it:
   * `concierge` and `chinook-assistant` share `in1`, `router1` and `out1`.
   * Dropping this field left every replayed frame to the ambiguous id walk —
   * so the live path and the replay path resolved the same frame by different
   * rules, which is exactly the drift `frameTarget` was written to end.
   */
  readonly pathSlugs?: readonly string[];
  /** The top-level owner the stream resolved for this frame — the fallback
   * `frameTarget` uses when `path` says nothing about the open document. */
  readonly activeNode?: string;
  /** Set when this row is a *spawn* rather than a completed step: the run
   * announced a child worker or subagent. A first-class row, not an
   * anonymous internal-step tick — seeing the spawn moment is the point. */
  readonly spawn?: SpawnDetail;
}

export interface SpawnDetail {
  readonly kind: 'fanout' | 'subagent' | 'subgraph';
  readonly label: string;
  readonly instruction: string;
}

/** One node's subtree: the node plus the internal steps it ran. */
export interface TraceNode {
  readonly node: string;
  readonly taskId: string | null;
  readonly durationMs: number;
  readonly output: string | null;
  readonly spawn?: SpawnDetail;
  readonly children: readonly Omit<ActivityRow, 'internal'>[];
}

/** Nests internal steps under the most recent canvas node — the stream is
 * ordered, so ownership is positional (LangGraph reports a namespace only
 * for true nested subgraphs, not for loop internals).
 *
 * A spawn row is always top-level, even though it usually arrives while an
 * agent's internal loop is running: it is the announcement of a *new* actor,
 * so burying it under the parent's collapsed step count would hide exactly
 * the moment the user came here to see. */
export function buildTrace(rows: readonly ActivityRow[]): TraceNode[] {
  const tree: TraceNode[] = [];
  // The owner of internal steps is the last *node*, not the last row: a spawn
  // row sits in the tree too, and charging a tool loop to it would turn the
  // announcement into the work.
  let owner: TraceNode | undefined;
  for (const row of rows) {
    if (row.spawn) {
      tree.push({ ...row, children: [] });
    } else if (row.internal) {
      if (owner) (owner.children as ActivityRow[]).push(row);
    } else {
      owner = { ...row, children: [] };
      tree.push(owner);
    }
  }
  return tree;
}

/** The downloadable run record — ticket 63's "export as tree JSON". */
export function exportTrace(turn: {
  readonly question: string;
  readonly activity: readonly ActivityRow[];
  readonly result: RunResult | null;
}): void {
  const payload = {
    question: turn.question,
    trace: buildTrace(turn.activity),
    answer: turn.result?.answer ?? null,
    attempts: turn.result?.attempts ?? null,
    decisions: turn.result?.decisions ?? {},
    exportedAt: new Date().toISOString(),
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'openstategraph-trace.json';
  a.click();
  URL.revokeObjectURL(url);
}

export function Activity({ rows }: { rows: readonly ActivityRow[] }) {
  // Keyed on the array identity, which changes only for the turn currently
  // streaming: `AskPanel` appends to `turn.activity` per frame, so without
  // this every *finished* turn refolds its whole (already final) trace on
  // every frame of the live run — O(turns x frames x rows) for a record
  // that cannot have changed. `buildTrace` is a pure fold of `rows`, so
  // caching it is referentially transparent (see traceTree.test.ts).
  const trace = useMemo(() => buildTrace(rows), [rows]);
  return (
    <div className="ask__activity">
      {rows.length === 0 ? <p className="ask__meta">Waiting for the first node to run…</p> : null}
      {trace.map((step, index) =>
        step.spawn ? (
          <div
            key={`spawn-${step.spawn.label}-${step.taskId ?? index}`}
            className="ask__activity-row ask__activity-row--spawn"
            title={step.spawn.instruction || undefined}
          >
            <span className="ask__activity-node">⤷ spawned {step.spawn.label}</span>
            {step.spawn.instruction ? (
              <span className="ask__activity-spawn-task">{step.spawn.instruction}</span>
            ) : null}
            {step.taskId ? <span className="ask__activity-task">{step.taskId}</span> : null}
          </div>
        ) : (
          <details
            key={`${step.node}-${step.taskId ?? index}`}
            className="ask__trace-step"
            open={false}
          >
            <summary className="ask__activity-row">
              <span className="ask__activity-node">{step.node.replace(/^node:/, '')}</span>
              {step.taskId ? <span className="ask__activity-task">{step.taskId}</span> : null}
              <span className="ask__activity-ms">{step.durationMs} ms</span>
              {step.children.length > 0 ? (
                <span className="ask__activity-count">{step.children.length} steps</span>
              ) : null}
            </summary>
            {step.children.map((child, childIndex) => (
              <div key={childIndex} className="ask__activity-row ask__activity-row--child">
                <span className="ask__activity-node">{child.node}</span>
                <span className="ask__activity-ms">{child.durationMs} ms</span>
              </div>
            ))}
            {step.output ? <RichText className="ask__trace-output" text={step.output} /> : null}
          </details>
        ),
      )}
    </div>
  );
}
