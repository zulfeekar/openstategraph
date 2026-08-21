import { useMemo } from 'react';
import type { RunResult } from '@core/runtime/RuntimeClient';
import { RichText } from '@view/common/RichText';
import { traceStepKey } from './traceKeys';
import { formatDuration } from './traceDuration';

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
   * collapse a whole subgraph to one lane. The trace tree reads `path`
   * rather than this, because `path` is this namespace *already resolved*
   * to canvas ids by the server (see `traceOwner`); until ticket 72 it read
   * neither and nested by arrival order instead. */
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

/**
 * The canvas node a frame belongs to, or `null` when the frame cannot say.
 *
 * The stream already answers this: `path` is `RunPathResolver`'s walk of the
 * checkpoint namespace against a known name->id map, and it runs **outermost
 * first** — an agent's inner `model` step arrives with
 * `namespace: ['agent_sql:<uuid>']` and therefore `path: ['agent-sql']`, and a
 * step three levels down inside a mount arrives as
 * `['wf-music', 'agent-sql']`.
 *
 * The **first** entry is the one this trace wants, not the last. A trace is a
 * record of one document — the one that was run and is on screen — and
 * `path[0]` is always a card on it, while the deeper entries are cards on a
 * document this reader is not looking at. Taking the last entry gave the
 * mounted child's `router1` a row of its own on the parent's trace, where the
 * name lookup resolved it against the *parent's* nodes and printed the
 * parent's router's title on the child's step: the same id collision
 * `pathSlugs` exists to warn about. Outermost-first, a whole mounted run
 * collapses to the mount's own row, which is what a mount is.
 *
 * `activeNode` is the server's own top-level answer and says the same thing;
 * it is the fallback because it is *sticky* across frames that resolve to
 * nothing, and stickiness is the failure mode this ticket is about.
 *
 * `null` means an older frame with neither field, and the caller falls back to
 * the positional rule this module used to apply to everything.
 */
export function traceOwner(row: ActivityRow): string | null {
  const path = row.path;
  if (path && path.length > 0) return path[0] ?? null;
  return row.activeNode ?? null;
}

/** Ids reach this module from two producers — a frame's `node` and a
 * resolved `path` entry — and one of them may carry the `node:` prefix the
 * view strips for display. Comparing them raw is how a match is missed. */
const same = (id: string) => id.replace(/^node:/, '');

/**
 * Nests internal steps under the canvas node **that ran them** (ticket 72),
 * which is not the node above them in the stream.
 *
 * The old rule was positional — "charge an internal frame to the last node
 * row" — and it was wrong in the one direction nobody checks: LangGraph emits
 * a node's inner frames *before* that node's own completion frame. So every
 * agent's loop was charged to whatever ran immediately **before** it, and the
 * agent's own row arrived milliseconds later carrying nothing. On the shipped
 * `chinook-assistant` that read as a tool-less classifier making eight
 * database calls in 11 seconds while the SQL agent, which owns those tools,
 * showed `2 ms`. Read literally the trace sent a developer to optimise the
 * wrong node.
 *
 * So ownership is now a **lookup**, not a position: `traceOwner` reads the
 * `path` the server already resolves for the canvas highlight, and the first
 * internal frame of a node *opens* that node's row rather than joining the
 * previous one. The node's own frame, when it arrives, closes the row it
 * already has instead of pushing a second one — which is also why a revision
 * loop still reads as two visits and not one merged blob.
 *
 * A frame with no `path` and no `activeNode` keeps the positional rule: it is
 * an older client's wire format, and guessing is still better than dropping.
 *
 * A spawn row is always top-level, even though it usually arrives while an
 * agent's internal loop is running: it is the announcement of a *new* actor,
 * so burying it under the parent's collapsed step count would hide exactly
 * the moment the user came here to see.
 */
export function buildTrace(rows: readonly ActivityRow[]): TraceNode[] {
  interface Mutable {
    node: string;
    taskId: string | null;
    durationMs: number;
    output: string | null;
    spawn?: SpawnDetail;
    children: Omit<ActivityRow, 'internal'>[];
  }
  const tree: Mutable[] = [];
  // Rows opened by an internal frame and still waiting for their node's own
  // completion frame. Keyed by canvas id: at most one visit of a node can be
  // open at a time, because its completion frame closes it.
  const open = new Map<string, Mutable>();
  // The positional fallback, for frames that carry no path at all.
  let last: Mutable | undefined;

  const push = (row: ActivityRow): Mutable => {
    const node: Mutable = {
      node: row.node,
      taskId: row.taskId,
      durationMs: row.durationMs,
      output: row.output,
      ...(row.spawn ? { spawn: row.spawn } : {}),
      children: [],
    };
    tree.push(node);
    return node;
  };

  for (const row of rows) {
    if (row.spawn) {
      push(row);
      continue;
    }
    const owner = traceOwner(row);
    if (row.internal) {
      // The owner's row, opened now if its completion frame has not arrived.
      const key = owner === null ? null : same(owner);
      let target = key === null ? last : open.get(key);
      if (!target && key !== null) {
        target = push({
          ...row,
          node: owner as string,
          internal: false,
          output: null,
          durationMs: 0,
          spawn: undefined,
        });
        open.set(key, target);
      }
      if (!target) continue;
      target.children.push(row);
      // The steps are where a node's time actually went: the completion
      // frame's own gap is the millisecond after the last one. Summing them
      // is what stops a 36-step agent reading `3 ms`.
      target.durationMs += row.durationMs;
      continue;
    }
    const key = same(owner ?? row.node);
    const opened = open.get(key);
    if (opened) {
      // Close the row its own steps already opened, rather than pushing a
      // second, empty one directly beneath it.
      opened.durationMs += row.durationMs;
      opened.output = row.output ?? opened.output;
      opened.taskId = opened.taskId ?? row.taskId;
      open.delete(key);
      last = opened;
      continue;
    }
    last = push(row);
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
            // Same root as the step key below: the turn marker cannot
            // discriminate across turns, because being identical every turn is
            // what it is for.
            key={`spawn-${step.spawn.label}-${traceStepKey(step, index)}`}
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
            // Index AND task id — see `traceStepKey`. `??` used the turn
            // marker as a discriminator, and that marker is identical on every
            // turn by design, so two turns of one node collided.
            key={traceStepKey(step, index)}
            className="ask__trace-step"
            open={false}
          >
            <summary className="ask__activity-row">
              <span className="ask__activity-node">{step.node.replace(/^node:/, '')}</span>
              {step.taskId ? <span className="ask__activity-task">{step.taskId}</span> : null}
              <span className="ask__activity-ms">{formatDuration(step.durationMs)}</span>
              {step.children.length > 0 ? (
                <span className="ask__activity-count">{step.children.length} steps</span>
              ) : null}
            </summary>
            {step.children.map((child, childIndex) => (
              <div key={childIndex} className="ask__activity-row ask__activity-row--child">
                <span className="ask__activity-node">{child.node}</span>
                <span className="ask__activity-ms">{formatDuration(child.durationMs)}</span>
              </div>
            ))}
            {step.output ? <RichText className="ask__trace-output" text={step.output} /> : null}
          </details>
        ),
      )}
    </div>
  );
}
