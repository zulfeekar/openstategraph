import type { McpServer } from './McpRegistryClient';

/**
 * Which MCP servers this project can bind, answerable **synchronously**.
 *
 * The `tool.mcp` card's *Server* picker offered two hardcoded names — the two
 * built-in defaults — in every project, on every install, for ever. A server
 * registered in the MCP panel never appeared, and a built-in deleted there was
 * still offered. You could type a name by hand and it compiled, so the picker
 * did not fail: it simply lied about what existed, and a developer who trusted
 * it concluded the panel and the card were unrelated features (mcp-connect
 * ticket 07).
 *
 * The awkward part is the shape of the seam, not the list, and it is the same
 * seam `workflowCatalogue` already solved for the mount slug picker: a field's
 * `options` is a **synchronous** function called during a render, while the
 * registry arrives over HTTP. So this holds the last answer and something else
 * keeps it current — here `McpRegistryClient`, which publishes every list it
 * reads, so "the registry answered" and "the catalogue knows" cannot diverge.
 *
 * Deliberately holds **names** and nothing else. The panel already owns the
 * full rows and their validation verdicts; a second copy of a URL or an auth
 * variable here would be a second thing to invalidate, and the picker's whole
 * question is which names are legal.
 *
 * `null` and `[]` are different answers, and the difference is the bug. `null`
 * is *nobody has told us yet* — fall back to the built-ins, which is what an
 * unconfigured project actually has. `[]` is *the registry answered, and it is
 * empty* — offer nothing, because the alternative is exactly the ghost entry
 * the ticket is about.
 */
type Listener = () => void;

export class McpServerCatalogue {
  private names: readonly string[] | null = null;
  private readonly listeners = new Set<Listener>();

  /** Every registered server name, or `null` if the registry has not answered. */
  list(): readonly string[] | null {
    return this.names;
  }

  /**
   * Records what the registry answered, notifying only on a real change.
   *
   * The comparison matters for the same reason it does in `workflowCatalogue`:
   * the panel re-lists after every validate press, and a needless notification
   * re-renders every MCP picker on the canvas.
   */
  set(servers: readonly McpServer[]): void {
    const next = servers.map((server) => server.name);
    const same =
      this.names !== null &&
      next.length === this.names.length &&
      next.every((name, index) => this.names?.[index] === name);
    if (same) return;
    this.names = next;
    for (const listener of this.listeners) listener();
  }

  onChange(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  /** Forgets what it was told. For tests, so one file's list is not another's. */
  reset(): void {
    this.names = null;
  }
}

/**
 * The one MCP catalogue the editor reads.
 *
 * A module singleton for the reason `workflowCatalogue` is one, recorded
 * there: a node *definition* is data assembled at import time, so it cannot be
 * handed a dependency the way a React component can. `createMcpServerNode`
 * still takes an explicit thunk, which is what a test uses; the default
 * declaration registered in `nodes/index.ts` reads this.
 */
export const mcpServerCatalogue = new McpServerCatalogue();
