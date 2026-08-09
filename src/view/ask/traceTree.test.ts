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
