import { Ok, type Result } from '@core/kernel/Result';
import { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import { defineNode, type NodeSpec } from '@core/model/ModelRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { IPortDescriptor } from '@core/model/contracts/ports';
import type {
  ExecutionContext,
  INodeExecutor,
  IToolExecutor,
  PortOutputs,
} from '@core/execution/INodeExecutor';
import { PORT } from '../vocabulary';

/**
 * The single output every tool node exposes.
 *
 * The dot sits on the top edge because tools live *below* the agent they
 * serve and link upward into its tool bus, while the label still renders in
 * the card footer alongside every other port.
 */
export const TOOL_PORT: IPortDescriptor = {
  id: 'tool',
  direction: 'out',
  type: PORT.tool,
  label: 'tool',
  side: 'top',
  description: 'Connect to an agent’s tool bus.',
};

/** Base for tool nodes. Subclasses add typed accessors for their fields. */
export abstract class AbstractToolNodeModel extends AbstractNodeModel {}

/**
 * Declares a tool node.
 *
 * Fixes the parts every tool shares — the category, the accent-tinted tool
 * port, the palette keywords — so a new tool is just its fields, its schema
 * and its invocation. Adding one touches no other file.
 */
export function defineToolNode(
  spec: Omit<NodeSpec, 'category' | 'ports'> & { ports?: readonly IPortDescriptor[] },
  Model: new (definition: INodeDefinition, init: never) => AbstractNodeModel,
): INodeDefinition {
  return defineNode(
    {
      ...spec,
      category: 'tools',
      keywords: [...(spec.keywords ?? []), 'tool'],
      ports: [TOOL_PORT, ...(spec.ports ?? [])],
    },
    Model as never,
  );
}

/**
 * Wraps a tool implementation as an executor.
 *
 * The dataflow half is uniform: running a tool node just publishes its
 * handle so the link carries a callable to the agent. Only `describeTool`
 * and `invokeTool` differ per tool, so those are all a caller supplies.
 */
export function createToolExecutor(
  nodeTypeId: string,
  tool: IToolExecutor,
): INodeExecutor & IToolExecutor {
  return {
    id: nodeTypeId,
    describeTool: tool.describeTool,
    invokeTool: tool.invokeTool,

    execute(ctx: ExecutionContext): Promise<Result<PortOutputs, string>> {
      const spec = tool.describeTool(ctx.node);
      ctx.log(`Ready as "${spec.name}"`);
      return Promise.resolve(Ok({ tool: { nodeId: ctx.node.id, spec } }));
    },
  };
}
