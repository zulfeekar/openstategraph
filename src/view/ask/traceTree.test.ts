import { describe, expect, it } from 'vitest';
import { buildTrace, type ActivityRow } from './traceTree';

const row = (patch: Partial<ActivityRow> & { node: string }): ActivityRow => ({
  taskId: null,
  internal: false,
  namespace: [],
  durationMs: 10,
  output: null,
  ...patch,
});

const spawn = (label: string, patch: Partial<ActivityRow> = {}): ActivityRow =>
  row({
    node: 'node:orch',
    ...patch,
    spawn: { kind: 'fanout', label, instruction: `research ${label}` },
  });

describe('buildTrace', () => {
  it('nests internal steps under the canvas node that ran them', () => {
    const trace = buildTrace([
      row({ node: 'node:agent1' }),
      row({ node: 'model', internal: true }),
      row({ node: 'tools', internal: true }),
    ]);
    expect(trace).toHaveLength(1);
    expect(trace[0]!.children.map((c) => c.node)).toEqual(['model', 'tools']);
  });

  it('keeps a spawn as a top-level row rather than an internal-step tick', () => {
    const trace = buildTrace([
      row({ node: 'node:orch' }),
      spawn('researcher', { taskId: 't1' }),
      spawn('analyst', { taskId: 't2' }),
      row({ node: 'model', internal: true }),
    ]);
    expect(trace.map((step) => step.spawn?.label ?? step.node)).toEqual([
      'node:orch',
      'researcher',
      'analyst',
    ]);
    // The internal frame belongs to the node, never to the spawn row that
    // happens to precede it — an announcement does no work.
    expect(trace[0]!.children).toHaveLength(1);
    expect(trace[2]!.children).toHaveLength(0);
  });

  it('carries the instruction snippet through to the row', () => {
    const trace = buildTrace([spawn('researcher', { taskId: 't1' })]);
    expect(trace[0]!.spawn?.instruction).toBe('research researcher');
    expect(trace[0]!.taskId).toBe('t1');
  });
});

describe('buildTrace ownership (ticket 72)', () => {
  // The real frame order, taken off the wire on 2026-08-20: an agent's
  // internal loop frames arrive *before* the agent's own completion frame,
  // so "the last node row" is always the node that ran *before* it.
  const chinook = (): ActivityRow[] => [
    row({ node: 'in1', path: ['in1'], durationMs: 3110 }),
    row({ node: 'router1', path: ['router1'], durationMs: 632 }),
    spawn('agent-sql', { node: 'router1', path: ['router1'], durationMs: 0 }),
    row({
      node: 'model',
      internal: true,
      namespace: ['agent_sql:7ea78ca6'],
      path: ['agent-sql'],
      durationMs: 4000,
    }),
    row({
      node: 'tools',
      internal: true,
      namespace: ['agent_sql:7ea78ca6'],
      path: ['agent-sql'],
      durationMs: 300,
    }),
    row({ node: 'agent-sql', path: ['agent-sql'], durationMs: 3, output: 'the answer' }),
    row({ node: 'grader-sql', path: ['grader-sql'], durationMs: 714 }),
  ];

  it('credits an agent loop to the agent, not to the node before it', () => {
    const trace = buildTrace(chinook());
    expect(trace.map((s) => s.spawn?.label ?? s.node)).toEqual([
      'in1',
      'router1',
      'agent-sql',
      'agent-sql',
      'grader-sql',
    ]);
    // `router1` is a classifier with no tools wired; it ran nothing.
    expect(trace[1]!.children).toHaveLength(0);
    expect(trace[3]!.children.map((c) => c.node)).toEqual(['model', 'tools']);
    expect(trace[3]!.output).toBe('the answer');
  });

  it('gives the owning row the time its own steps took', () => {
    const trace = buildTrace(chinook());
    expect(trace[1]!.durationMs).toBe(632);
    expect(trace[3]!.durationMs).toBe(4303);
  });

  it('opens a fresh row for each visit, so a revision loop reads as two', () => {
    const internal = (path: string) =>
      row({ node: 'model', internal: true, path: [path], durationMs: 5 });
    const trace = buildTrace([
      internal('agent-sql'),
      row({ node: 'agent-sql', path: ['agent-sql'], durationMs: 1 }),
      row({ node: 'grader-sql', path: ['grader-sql'], durationMs: 2 }),
      internal('agent-sql'),
      row({ node: 'agent-sql', path: ['agent-sql'], durationMs: 1 }),
    ]);
    expect(trace.map((s) => s.node)).toEqual([
      'agent-sql',
      'grader-sql',
      'agent-sql',
    ]);
    expect(trace.map((s) => s.children.length)).toEqual([1, 0, 1]);
  });

  it('collapses a mounted run onto the mount, not onto the child\'s own ids', () => {
    // `concierge` mounts `chinook-assistant` at `wf-music`. Every frame from
    // inside the child arrives with the mount at the head of its path — and
    // the child's ids collide with the parent's (`in1`, `router1`, `out1`),
    // so a row named from the deep end prints the parent's node titles on the
    // child's steps.
    const inside = (node: string, tail: string) =>
      row({ node, internal: true, path: ['wf-music', tail], durationMs: 20 });
    const trace = buildTrace([
      row({ node: 'router1', path: ['router1'], durationMs: 5 }),
      inside('in1', 'in1'),
      inside('model', 'agent-sql'),
      inside('grader_sql', 'grader-sql'),
      row({ node: 'wf-music', path: ['wf-music'], durationMs: 1 }),
      row({ node: 'out1', path: ['out1'], durationMs: 2 }),
    ]);
    expect(trace.map((s) => s.node)).toEqual(['router1', 'wf-music', 'out1']);
    expect(trace[1]!.children.map((c) => c.node)).toEqual(['in1', 'model', 'grader_sql']);
    expect(trace[1]!.durationMs).toBe(61);
  });

  it('falls back to the positional rule for a frame carrying no path', () => {
    const trace = buildTrace([
      row({ node: 'node:agent1' }),
      row({ node: 'model', internal: true }),
    ]);
    expect(trace).toHaveLength(1);
    expect(trace[0]!.children.map((c) => c.node)).toEqual(['model']);
  });
  it('carries a skipped model call through the fold, on the grader row only', () => {
    // `production-ready` 92, and both paths in one assertion on purpose: a
    // fold that dropped the marker, and a fold that smeared it onto every
    // row, are the two ways this stops being readable.
    const trace = buildTrace([
      row({ node: 'agent-sql', path: ['agent-sql'], output: 'Error: no such table' }),
      row({
        node: 'grader-sql',
        path: ['grader-sql'],
        check: 'error',
        reason: 'The step failed: Error: no such table',
      }),
      row({ node: 'grader-doc', path: ['grader-doc'], output: 'A firm answer.' }),
    ]);
    expect(trace.map((s) => s.check ?? '')).toEqual(['', 'error', '']);
    expect(trace[1]!.reason).toContain('no such table');
  });

  it("closes an opened grader row with the completion frame's judgement", () => {
    // A grader whose own internal step arrived first opens the row; only the
    // completion frame knows the verdict, so a fold that kept the opener's
    // (empty) marker would render a judged row for a skipped model call.
    const trace = buildTrace([
      row({ node: 'model', internal: true, path: ['grader-sql'], durationMs: 1 }),
      row({ node: 'grader-sql', path: ['grader-sql'], check: 'empty', reason: 'The answer is empty.' }),
    ]);
    expect(trace).toHaveLength(1);
    expect(trace[0]!.check).toBe('empty');
  });
});
