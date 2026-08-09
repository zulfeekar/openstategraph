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
}

/** One node's subtree: the node plus the internal steps it ran. */
export interface TraceNode {
  readonly node: string;
  readonly taskId: string | null;
  readonly durationMs: number;
  readonly output: string | null;
  readonly children: readonly Omit<ActivityRow, 'internal'>[];
}

/** Nests internal steps under the most recent canvas node — the stream is
 * ordered, so ownership is positional (LangGraph reports a namespace only
 * for true nested subgraphs, not for loop internals). */
export function buildTrace(rows: readonly ActivityRow[]): TraceNode[] {
  const tree: TraceNode[] = [];
  for (const row of rows) {
    const last = tree[tree.length - 1];
    if (row.internal && last) {
      (last.children as ActivityRow[]).push(row);
    } else if (!row.internal) {
      tree.push({ ...row, children: [] });
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
  const trace = buildTrace(rows);
  return (
    <div className="ask__activity">
      {rows.length === 0 ? <p className="ask__meta">Waiting for the first node to run…</p> : null}
      {trace.map((step, index) => (
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
      ))}
    </div>
  );
}
