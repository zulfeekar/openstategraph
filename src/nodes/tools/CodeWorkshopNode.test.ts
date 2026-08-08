/**
 * Code Workshop tool nodes — definition tests (not registration, since these
 * are workflow-scoped, same stance as TabularDataNode.test.ts).
 */

import { describe, expect, it } from 'vitest';
import {
  WORKSHOP_NODES,
  createPrNode,
  runWorkspaceTestsNode,
} from './CodeWorkshopNode';

describe('code workshop nodes definition', () => {
  it('exports all seven workshop tool nodes', () => {
    const ids = WORKSHOP_NODES.map((n) => n.definition.id);
    expect(ids).toEqual([
      'tool.workshop-reset',
      'tool.workshop-list-files',
      'tool.workshop-read-file',
      'tool.workshop-write-file',
      'tool.workshop-run-tests',
      'tool.workshop-diff',
      'tool.workshop-create-pr',
    ]);
  });

  it('the PR node ships with gh OFF — dry-run is the default, opt-in is explicit', () => {
    const useGhField = createPrNode.fields.find((f) => f.key === 'useGh');
    expect(useGhField).toBeDefined();
    expect(useGhField?.kind).toBe('toggle');
    expect(useGhField?.defaultValue).toBe(false);
  });

  it('run-tests relies on the shared timeout field — the command itself is not configurable', () => {
    const keys = runWorkspaceTestsNode.fields.map((f) => f.key);
    // Only the registry-injected shared fields; nothing that could vary the command.
    expect(keys).toContain('timeoutSeconds');
    expect(keys.filter((k) => k !== 'maxRetries' && k !== 'timeoutSeconds')).toEqual([]);
  });

  it('every node has exactly one out port: the tool bus connector', () => {
    for (const { definition } of WORKSHOP_NODES) {
      expect(definition.id).toMatch(/^tool\.workshop-/);
      const outPorts = definition.ports({}).filter((p) => p.direction === 'out');
      expect(outPorts).toHaveLength(1);
      expect(outPorts[0]?.id).toBe('tool');
    }
  });

  it('every executor refuses local preview honestly instead of fabricating a result', async () => {
    for (const { executor } of WORKSHOP_NODES) {
      const tool = executor as unknown as {
        invokeTool: (...args: unknown[]) => Promise<{ ok: boolean; error?: string }>;
      };
      const result = await tool.invokeTool(null, {}, null);
      expect(result.ok).toBe(false);
      expect(String(result.error)).toContain('backend');
    }
  });
});
