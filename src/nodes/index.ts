import type { ModelRegistry } from '@core/model/ModelRegistry';
import type { Registry } from '@core/kernel/Registry';
import type { INodeExecutor } from '@core/execution/INodeExecutor';
import type { ProviderRegistry } from '@core/providers/ProviderRegistry';
import type { INodeDefinition } from '@core/model/contracts/node';

import { CATEGORIES, PORT_TYPES } from './vocabulary';
import { withReasoningEffort } from './effortField';
import { textInputExecutor, textInputNode } from './inputs/TextInputNode';
import { markdownFileExecutor, markdownFileNode } from './inputs/MarkdownFileNode';
import { skillExecutor, skillNode } from './inputs/SkillNode';
import { agentExecutor, createAgentNode } from './agent/AgentNode';
import { redditSearchExecutor, redditSearchNode } from './tools/RedditSearchNode';
import { GRADER_TYPE, createGraderNode, graderExecutor } from './routing/GraderNode';
import { ROUTER_TYPE, createRouterNode, routerExecutor } from './routing/RouterNode';
import { humanApprovalExecutor, humanApprovalNode } from './routing/HumanApprovalNode';
import { formattedOutputExecutor, formattedOutputNode } from './output/FormattedOutputNode';
import { groupNode } from './annotate/GroupNode';
import { noteNode } from './annotate/NoteNode';
import {
  ORCHESTRATOR_TYPE,
  createOrchestratorNode,
  orchestratorExecutor,
} from './orchestrate/OrchestratorNode';
import { WORKER_TYPE, createWorkerNode, workerExecutor } from './orchestrate/WorkerNode';
import {
  FORMAT_REPORT_TYPE,
  createFormatReportNode,
  formatReportExecutor,
} from './orchestrate/FormatReportNode';
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

  // Every node family that drives a model is built with the provider
  // registry, because every one of them now offers the shared model
  // picker (`./modelField`) that only the agent used to have.
  const agentNode = createAgentNode(providers);
  const routerNode = createRouterNode(providers);
  const graderNode = createGraderNode(providers);
  const orchestratorNode = createOrchestratorNode(providers);
  const workerNode = createWorkerNode(providers);
  const formatReportNode = createFormatReportNode(providers);

  // Reasoning effort is given to every definition that carries the model
  // picker, here rather than in six node modules. See `withReasoningEffort`:
  // a shared concern declared per family is the exact defect `modelField.ts`
  // was created to undo, and a rule applied at the registration point cannot
  // be forgotten by the seventh family.
  const withEffort = (definition: INodeDefinition): INodeDefinition =>
    withReasoningEffort(definition, providers);

  registry.nodeTypes.registerAll(
    [
      textInputNode,
      markdownFileNode,
      skillNode,
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
    ].map(withEffort),
  );

  executors.registerAll([
    textInputExecutor,
    markdownFileExecutor,
    skillExecutor,
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

/**
 * Type ids, for the seeded demo and for tests.
 *
 * Ids come from each module's exported `*_TYPE` constant, not from a built
 * definition. Six families are now *factories* over the `ProviderRegistry`
 * (they all carry the shared model picker), and a module-scope map cannot
 * hold a registry — nor should it: an id is a literal fact about a node type,
 * knowable without constructing one.
 */
export const NODE_TYPE = {
  textInput: textInputNode.id,
  markdownFile: markdownFileNode.id,
  skill: skillNode.id,
  agent: 'agent.llm',
  redditSearch: redditSearchNode.id,
  router: ROUTER_TYPE,
  grader: GRADER_TYPE,
  humanApproval: humanApprovalNode.id,
  orchestrator: ORCHESTRATOR_TYPE,
  worker: WORKER_TYPE,
  formatReport: FORMAT_REPORT_TYPE,
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
