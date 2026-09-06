import { describe, expect, it } from 'vitest';
import { Workbench } from '@app/Workbench';
import { WORKFLOW_SCHEMA_VERSION } from '@core/model/WorkflowModel';

/**
 * The editor half of schema v2 → v3 — production-ready ticket 16.
 *
 * `backend/openstategraph/schema.py` carries the same number and the same
 * step, because a document is written by one side and read by the other. That
 * is not theoretical: stamping the shipped documents v3 while this constant
 * was still 2 made every one of them refuse to load as "saved by a newer
 * version", and nine tests went red at once.
 *
 * So this exists to keep the editor's own chain honest. The Python side has
 * its own suite; neither proves the other.
 */
describe('v2 → v3: a Team mount loads as a Workflow mount', () => {
  const v2Document = {
    version: 2,
    name: 'A v2 document that mounts a Team',
    nodes: [
      { id: 'in1', type: 'input.text', position: { x: 0, y: 0 }, data: {} },
      {
        id: 'team1',
        type: 'team.workflow',
        position: { x: 200, y: 0 },
        data: {
          workflow: 'sourcing-team',
          outcome: 'Every claim carries a source.',
          overrides: '{"grader1":{"maxAttempts":4}}',
        },
      },
      { id: 'out1', type: 'output.formatted', position: { x: 400, y: 0 }, data: {} },
    ],
    edges: [
      {
        source: { nodeId: 'in1', portId: 'text' },
        target: { nodeId: 'team1', portId: 'input' },
      },
      {
        source: { nodeId: 'team1', portId: 'result' },
        target: { nodeId: 'out1', portId: 'result' },
      },
    ],
  };

  interface Exported {
    readonly version: number;
    readonly nodes: readonly { id: string; type: string; data: Record<string, unknown> }[];
    readonly edges: readonly unknown[];
  }

  /** Load the v2 document and read back what the editor would save. */
  const roundTrip = (): Exported => {
    const workbench = new Workbench();
    const outcome = workbench.controller.document.importJSON(JSON.stringify(v2Document));
    expect(outcome.ok, JSON.stringify(outcome)).toBe(true);
    return JSON.parse(workbench.controller.document.exportJSON()) as Exported;
  };

  it('declares the same version the backend does', () => {
    expect(WORKFLOW_SCHEMA_VERSION).toBe(3);
  });

  it('loads a v2 document at all, rather than refusing it', () => {
    expect(roundTrip().nodes.length).toBe(3);
  });

  it('turns the collapsed type into the one mount type', () => {
    const types = roundTrip().nodes.map((node) => node.type);
    expect(types).not.toContain('team.workflow');
    expect(types).toContain('workflow.subgraph');
  });

  it('keeps the node id, so the edges either side still resolve', () => {
    const exported = roundTrip();
    expect(exported.nodes.some((node) => node.id === 'team1')).toBe(true);
    expect(exported.edges.length).toBe(2);
  });

  it('does not lose the slug, the overrides or the authored outcome', () => {
    // The outcome is the one a migration could most easily drop: it belonged
    // to the node type that ceased to exist. `workflow.subgraph` gained the
    // field in the same change precisely so it would have somewhere to land.
    const node = roundTrip().nodes.find((candidate) => candidate.id === 'team1');
    expect(node?.data['workflow']).toBe('sourcing-team');
    expect(node?.data['outcome']).toBe('Every claim carries a source.');
    expect(String(node?.data['overrides'])).toContain('maxAttempts');
  });

  it('re-saves at the current version, not the one it read', () => {
    expect(roundTrip().version).toBe(WORKFLOW_SCHEMA_VERSION);
  });
});
