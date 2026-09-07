import { Err, type Result } from '@core/kernel/Result';
import type { INodeDefinition } from '@core/model/contracts/node';
import type { INodeExecutor, IToolExecutor } from '@core/execution/INodeExecutor';
import type { ToolSpec } from '@core/providers/ILLMProvider';
import type { AbstractNodeModel } from '@core/model/AbstractNodeModel';
import type { FieldOption } from '@core/model/contracts/fields';
import { ToolNodeModel, createToolExecutor, defineToolNode } from './AbstractToolNode';
import {
  MCP_FIELD,
  MCP_GROUPING_GUIDE,
  MCP_LOCKED_NOTE,
  mcpServersField,
  parseToolFilter,
} from './mcpServerFields';
import { mcpRowProbe } from './mcpRowProbe';

export const MCP_SERVER_TYPE = 'tool.mcp';

/** One server row, as the card writes it and the model reads it back. */
export interface McpServerRow {
  readonly id: string;
  /** A registered server by name, if this row picks one. */
  readonly server: string;
  /** An inline URL, if it configures one instead. */
  readonly url: string;
  /** Whichever of the two this row is identified by. */
  readonly target: string;
  readonly tools: readonly string[];
}

/**
 * The one card that carries a group of MCP servers.
 *
 * ## Why one node is a server list and not a tool
 *
 * The alternative was one node per remote tool, and it dies on arithmetic: a
 * thirty-tool server would be thirty cards, wired thirty times, and every one
 * of them would go stale the moment the server changed. So the node is the
 * *connection*, each row's filter narrows it, and the tool list is discovered
 * at compile time rather than stored.
 *
 * ## Why one node is N servers
 *
 * Ticket 04, and the trade is on the card in `MCP_GROUPING_GUIDE`: rows share
 * a consumer, because the card has one output and every row's tools travel to
 * it together. Where that is what you wanted — several services, one agent
 * choosing per task — rows cost nothing and save a canvas full of near-identical
 * cards. Where it is not, the answer is a second node.
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
  /**
   * Every row that names a server, in card order.
   *
   * A document written before ticket 04 carries its one server in the node's
   * own fields, and is read as the single row it is — compatibility rather
   * than migration, because opening a saved workflow must not rewrite it.
   * `prebuilt_mcp._server_rows` reads the same two shapes, for the same
   * reason and in the same order.
   */
  get rows(): McpServerRow[] {
    const listed = this.data[MCP_FIELD.servers];
    const rows = Array.isArray(listed) ? (listed as Array<Record<string, unknown>>) : [];
    // The flat fallback is reached when **no row names anything**, not when
    // the row list is absent: a new card seeds one empty row, so an old
    // document opened in a new editor carries both, and a fallback keyed on
    // absence would show nothing where a server is configured.
    const raw = rows.some(namesAServer) ? rows : [this.data as Record<string, unknown>];

    return raw.flatMap((row, index): McpServerRow[] => {
      const server = text(row[MCP_FIELD.server]);
      const url = text(row[MCP_FIELD.url]);
      if (!server && !url) return [];
      return [
        {
          id: text(row['id']) || `row${index}`,
          server,
          url,
          target: server || url,
          // Blank entries are dropped rather than treated as a filter.
          // Somebody who types a comma and stops must not silently bind
          // nothing — the same rule the Python side applies, because a filter
          // that means "all" in one language and "none" in the other is a bug
          // with two homes.
          tools: parseToolFilter(row[MCP_FIELD.tools] as never),
        },
      ];
    });
  }

  /**
   * What a developer can read off the card with no run behind it.
   *
   * Still the document's own words and never the server's: no tool count, no
   * tool names, nothing that needs a round trip. What changed with rows is
   * only the arithmetic.
   */
  override get subtitle(): string {
    const rows = this.rows;
    if (rows.length === 0) return 'No server yet — pick one, or give it a URL.';
    if (rows.length === 1) {
      const [row] = rows as [McpServerRow];
      const filtered = row.tools.length;
      if (filtered === 0) return `${row.target} · every tool it offers`;
      return `${row.target} · ${filtered} tool${filtered === 1 ? '' : 's'} only`;
    }
    const shown = rows
      .slice(0, 2)
      .map((row) => row.target)
      .join(', ');
    const rest = rows.length - 2;
    return `${rows.length} servers · ${shown}${rest > 0 ? ` +${rest} more` : ''}`;
  }
}

const text = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

/** Whether a row points at anything at all. Mirrors `prebuilt_mcp._names_a_server`. */
const namesAServer = (row: Record<string, unknown>): boolean =>
  Boolean(text(row[MCP_FIELD.server]) || text(row[MCP_FIELD.url]));

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
      fields: [
        mcpServersField({ probe: mcpRowProbe, ...(servers ? { servers } : {}) }),
        {
          // The trade a second row makes, where the second row is added.
          // Read-only beside what you own, never a pre-filled editable box.
          kind: 'readonly',
          key: MCP_FIELD.guide,
          label: 'One node, one consumer',
          defaultValue: MCP_GROUPING_GUIDE,
          group: 'MCP servers',
        },
        {
          kind: 'readonly',
          key: MCP_FIELD.note,
          label: 'What the machinery already does',
          defaultValue: MCP_LOCKED_NOTE,
          onCard: false,
          group: 'MCP servers',
        },
      ],
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
    const named = model.rows.map((row) => row.target).join(', ') || '(unconfigured)';
    return {
      name: 'mcp_server',
      description: `Tools from the MCP servers ${named}.`,
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
