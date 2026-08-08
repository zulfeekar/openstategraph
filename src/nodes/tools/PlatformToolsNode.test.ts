import { describe, expect, it } from 'vitest';
import { makeWorkbench } from '@core/testing/fixtures';
import conciergeEnvelope from '../../../workflows/concierge/workflow.json';

describe('platform tool nodes', () => {
  it('the concierge document survives an editor round-trip intact', () => {
    // The serializer silently drops unregistered node types — this pins that
    // every type the hidden gateway binds exists in the catalogue, so opening
    // it in the editor can never destroy its tools (ticket 67).
    const workbench = makeWorkbench();
    const document = (
      conciergeEnvelope as unknown as { document: { nodes: unknown[]; edges: unknown[] } }
    ).document;
    const outcome = workbench.serializer.loadFromText(
      workbench.model,
      JSON.stringify(document),
    );
    expect(outcome.ok).toBe(true);
    if (outcome.ok) expect(outcome.value.warnings).toEqual([]);
    expect(workbench.model.nodes()).toHaveLength(document.nodes.length);
    expect(workbench.model.edges()).toHaveLength(document.edges.length);
  });
});
