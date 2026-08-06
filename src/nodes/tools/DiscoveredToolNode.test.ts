import { describe, expect, it } from 'vitest';
import type { ToolCapability } from '@core/runtime/WorkflowFileClient';
import { createDiscoveredToolNode } from './DiscoveredToolNode';

const CAPABILITY: ToolCapability = {
  id: 'chinook-nl-to-sql/tools.ListTablesTool',
  name: 'chinook_list_tables',
  description: 'List all tables in the Chinook database.',
  argsSchema: { type: 'object', properties: {}, title: 'NoArgs' },
};

describe('createDiscoveredToolNode', () => {
  it('uses the capability id as the node type id, unmodified', () => {
    const { definition } = createDiscoveredToolNode(CAPABILITY);
    expect(definition.id).toBe(CAPABILITY.id);
  });

  it('carries the capability name and description onto the card', () => {
    const { definition } = createDiscoveredToolNode(CAPABILITY);
    expect(definition.label).toBe('chinook_list_tables');
    expect(definition.description).toBe('List all tables in the Chinook database.');
  });

  it('exposes a tool bus output port, like every other tool node', () => {
    const { definition } = createDiscoveredToolNode(CAPABILITY);
    const ports = definition.ports({});
    expect(ports.some((p) => p.id === 'tool' && p.direction === 'out')).toBe(true);
  });

  it("describeTool advertises the capability's real schema to the model", () => {
    const { executor } = createDiscoveredToolNode(CAPABILITY);
    const definition = createDiscoveredToolNode(CAPABILITY).definition;
    const node = definition.create({ position: { x: 0, y: 0 } });
    const spec = executor.describeTool!(node as never);
    expect(spec.name).toBe('chinook_list_tables');
    expect(spec.parameters).toEqual(CAPABILITY.argsSchema);
  });

  it('invokeTool refuses honestly rather than fabricating a result', async () => {
    const { executor } = createDiscoveredToolNode(CAPABILITY);
    const result = await executor.invokeTool!({} as never, {}, {} as never);
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toMatch(/backend/i);
      expect(result.error).toMatch(/Chat/i);
    }
  });
});
