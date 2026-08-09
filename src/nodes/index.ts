import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';

import { CATEGORIES, PORT_TYPES } from './vocabulary';
import { textInputExecutor, textInputNode } from './inputs/TextInputNode';
import { markdownFileExecutor, markdownFileNode } from './inputs/MarkdownFileNode';
import { agentExecutor, createAgentNode } from './agent/AgentNode';
import { redditSearchExecutor, redditSearchNode } from './tools/RedditSearchNode';
import { graderExecutor, graderNode } from './routing/GraderNode';
import { routerExecutor, routerNode } from './routing/RouterNode';
import { humanApprovalExecutor, humanApprovalNode } from './routing/HumanApprovalNode';
import { formattedOutputExecutor, formattedOutputNode } from './output/FormattedOutputNode';
import { groupNode } from './annotate/GroupNode';
import { noteNode } from './annotate/NoteNode';
import { orchestratorExecutor, orchestratorNode } from './orchestrate/OrchestratorNode';
import { workerExecutor, workerNode } from './orchestrate/WorkerNode';
import { formatReportExecutor, formatReportNode } from './orchestrate/FormatReportNode';
import { subgraphExecutor, subgraphNode } from './compose/SubgraphNode';
import { teamExecutor, teamNode } from './compose/TeamNode';
import { PLATFORM_TOOL_NODES } from './tools/PlatformToolsNode';

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
    // Routing is the editor's grammar, so it ships globally — unlike the
    // Chinook tools, which belong to their workflow (ticket 08 scoping) and
    // are registered only while a document using them is open — see
    // `syncWorkflowScopedNodes`, called from `Workbench`.
    routerNode,
    graderNode,
    humanApprovalNode,
    // Loop/graph engineering: split -> fan-out -> dispatch -> join.
    orchestratorNode,
    workerNode,
    formatReportNode,
    subgraphNode,
    teamNode,
    ...PLATFORM_TOOL_NODES.map((entry) => entry.definition),
    formattedOutputNode,
    groupNode,
    noteNode,
  ]);

  executors.registerAll([
    textInputExecutor,
    markdownFileExecutor,
    agentExecutor,
    redditSearchExecutor,
    routerExecutor,
    graderExecutor,
    humanApprovalExecutor,
    orchestratorExecutor,
    workerExecutor,
    formatReportExecutor,
    subgraphExecutor,
    teamExecutor,
    ...PLATFORM_TOOL_NODES.map((entry) => entry.executor),
    formattedOutputExecutor,
  ]);
}

/** Type ids, for the seeded demo and for tests. */
export const NODE_TYPE = {
  textInput: textInputNode.id,
  markdownFile: markdownFileNode.id,
  agent: 'agent.llm',
  redditSearch: redditSearchNode.id,
  router: routerNode.id,
  grader: graderNode.id,
  humanApproval: humanApprovalNode.id,
  orchestrator: orchestratorNode.id,
  worker: workerNode.id,
  formatReport: formatReportNode.id,
  subgraph: subgraphNode.id,
  team: teamNode.id,
  formattedOutput: formattedOutputNode.id,
  group: groupNode.id,
  note: noteNode.id,
  // Chinook database tools
  chinookGetSchema: 'tool.chinook-get-schema',
  chinookGetAllTables: 'tool.chinook-get-all-tables',
  chinookExecuteSql: 'tool.chinook-execute-sql',
} as const;

// Concrete node model classes are deliberately NOT re-exported here. Nothing
// imported them through this barrel, only 7 of the 15 were listed (so it was
// never a contract anyway), and CLAUDE.md's ladder is explicit that consumers
// depend on `INodeModel`, never on a concrete class. The registry's `create`
// is how a model gets instantiated.
export { CATEGORY, PORT } from './vocabulary';
