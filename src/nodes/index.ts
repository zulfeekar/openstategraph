import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';

import { CATEGORIES, PORT_TYPES } from './vocabulary';
import { textInputExecutor, textInputNode } from './inputs/TextInputNode';
import { markdownFileExecutor, markdownFileNode } from './inputs/MarkdownFileNode';
import { agentExecutor, createAgentNode } from './agent/AgentNode';
import { redditSearchExecutor, redditSearchNode } from './tools/RedditSearchNode';
import { formattedOutputExecutor, formattedOutputNode } from './output/FormattedOutputNode';
import { groupNode } from './annotate/GroupNode';
import { noteNode } from './annotate/NoteNode';

/**
 * The catalogue's single registration point.
 *
 * This is the only file that knows the full list of node types. Everything
 * else — palette, canvas, inspector, serializer, scheduler — discovers nodes
 * through the registries, so shipping a new node means adding a module and
 * one line here.
 *
 * Annotation and container types are registered too, but the palette shows
 * them in their own section rather than hiding them, since dropping a group
 * or a note onto the canvas is a normal thing to want.
 */
export function registerNodeCatalogue(
  registry: ModelRegistry,
  executors: Registry<INodeExecutor>,
  providers: ProviderRegistry,
): void {
  registry.categories.registerAll(CATEGORIES);
  registry.portTypes.registerAll(PORT_TYPES);

  const agentNode = createAgentNode(providers);

  registry.nodeTypes.registerAll([
    textInputNode,
    markdownFileNode,
    agentNode,
    redditSearchNode,
    formattedOutputNode,
    groupNode,
    noteNode,
  ]);

  executors.registerAll([
    textInputExecutor,
    markdownFileExecutor,
    agentExecutor,
    redditSearchExecutor,
    formattedOutputExecutor,
  ]);
}

/** Type ids, for the seeded demo and for tests. */
export const NODE_TYPE = {
  textInput: textInputNode.id,
  markdownFile: markdownFileNode.id,
  agent: 'agent.llm',
  redditSearch: redditSearchNode.id,
  formattedOutput: formattedOutputNode.id,
  group: groupNode.id,
  note: noteNode.id,
} as const;

export { TextInputNodeModel } from './inputs/TextInputNode';
export { MarkdownFileNodeModel } from './inputs/MarkdownFileNode';
export { AgentNodeModel } from './agent/AgentNode';
export { RedditSearchNodeModel } from './tools/RedditSearchNode';
export { FormattedOutputNodeModel } from './output/FormattedOutputNode';
export { GroupNodeModel } from './annotate/GroupNode';
export { NoteNodeModel } from './annotate/NoteNode';
export { CATEGORY, PORT } from './vocabulary';
