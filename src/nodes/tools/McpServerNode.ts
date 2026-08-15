import { Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { INodeExecutor, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { FieldOption } from '@core/model/contracts/fields';
import { ToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';
import { MCP_FIELD, mcpServerFields } from './mcpServerFields';

export const MCP_SERVER_TYPE = 'tool.mcp';

/**
 * The one card that carries a whole MCP server.
 *
 * ## Why one node is a server and not a tool
 *
 * The alternative was one node per remote tool, and it dies on arithmetic: a
 * thirty-tool server would be thirty cards, wired thirty times, and every one
 * of them would go stale the moment the server changed. So the node is the
 * *connection*, the filter below narrows it, and the tool list is discovered
 * at compile time rather than stored.
 *
 * ## What this card cannot show, and does not pretend to
 *
 * **No tool count, and no tool names.** Both are facts about a remote server,
 * reachable only by a network round trip, and a card that showed them before
 * a run would be showing something it cannot know — the same reason the
 * Memory segment's card shows no entry count. What the subtitle says is what
 * the *document* says: which server, and how narrowly it is filtered.
 *
 * ## The field set is not defined here
 *
 * It lives in `mcpServerFields.ts`, because the app-level panel renders the
 * same controls for a project-wide server. One declaration, two consumers —
 * the alternative is two spellings of what an MCP server is, drifting apart
 * the first time a fourth auth type appears.
 */
export class McpServerNodeModel extends ToolNodeModel {
  /** The registered server this node names, if any. */
  get server(): string {
    return this.getText(MCP_FIELD.server).trim();
  }

  get url(): string {
    return this.getText(MCP_FIELD.url).trim();
  }

  /**
   * The tool filter, as names.
   *
   * Blank rows are dropped rather than treated as a filter. Somebody pressing
   * *Add tool* and then changing their mind must not silently bind nothing —
   * the same rule the Python side applies, because a filter that means "all"
   * in one language and "none" in the other is a bug with two homes.
   */
  get selectedTools(): string[] {
    const rows = this.data[MCP_FIELD.tools];
    if (!Array.isArray(rows)) return [];
    return rows
      .map((row) => String((row as Record<string, unknown>)['name'] ?? '').trim())
      .filter((name) => name !== '');
  }

  /** What a developer can read off the card with no run behind it. */
  override get subtitle(): string {
    const target = this.server || this.url;
    if (!target) return 'No server yet — pick one, or give it a URL.';
    const filter = this.selectedTools;
    if (filter.length === 0) return `${target} · every tool it offers`;
    return `${target} · ${filter.length} tool${filter.length === 1 ? '' : 's'} only`;
  }
}

/**
 * Declares the node.
 *
 * A factory taking the registered-server list, in the same shape as
 * `createAgentNode(providers)`: which servers exist is runtime state fetched
 * from `GET /api/mcp/servers`, not a literal. Called with nothing, it
 * suggests the two built-in defaults, which is what a project that has
 * configured none actually has.
 */
export function createMcpServerNode(servers?: () => readonly FieldOption[]): INodeDefinition {
  return defineToolNode(
    {
      id: MCP_SERVER_TYPE,
      label: 'MCP server',
      description:
        'Binds every tool a Model Context Protocol server offers onto an agent — the LangChain docs, an internal service, anything that speaks MCP over HTTP.',
      iconId: 'node-mcp',
      accent: 'violet',
      keywords: [
        'mcp',
        'model context protocol',
        'server',
        'remote',
        'docs',
        'langchain',
        'integration',
        'connect',
        'external',
      ],
      defaultSize: { width: 300, height: 170 },
      fields: mcpServerFields(servers ? { servers } : {}),
    },
    McpServerNodeModel,
  );
}

/** The default declaration, for consumers with no live server list. */
export const mcpServerNode: INodeDefinition = createMcpServerNode();

/**
 * The browser preview refuses, by name.
 *
 * Registered rather than omitted, because a node with **no** registered
 * executor is *silently skipped* by the preview engine — the run would look
 * successful and the agent would answer from parametric knowledge, which is
 * precisely the failure an MCP docs server exists to prevent. A refusal that
 * names where the answer lives is the honest version, and it is the same
 * pattern the Grader, the Guardrail and the Memory segment already use.
 *
 * The reason it must refuse is not a missing feature: the browser cannot open
 * the connection at all. The credential lives in the *server's* environment
 * and the browser never has it, which is the secrets rule working as designed
 * rather than a gap to close later.
 */
const mcpServerTool: IToolExecutor = {
  describeTool(node: AbstractNodeModel): ToolSpec {
    const model = node as McpServerNodeModel;
    return {
      name: 'mcp_server',
      description: `Tools from the MCP server ${model.server || model.url || '(unconfigured)'}.`,
      parameters: { type: 'object', properties: {}, additionalProperties: false },
    };
  },

  async invokeTool(): Promise<Result<string, string>> {
    return Err(
      'An MCP server is reached by the Python runtime, which holds the credential — the ' +
        'browser preview has no connection to open. Use “Run” against the backend, or Chat.',
    );
  },
};

export const mcpServerExecutor: INodeExecutor = createToolExecutor(MCP_SERVER_TYPE, mcpServerTool);

export const MCP_SERVER_NODES = [{ definition: mcpServerNode, executor: mcpServerExecutor }];
