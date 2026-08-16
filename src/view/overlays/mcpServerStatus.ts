import { MCP_STATUSES, type McpStatus } from '@core/runtime/McpRegistryClient';

/**
 * What the panel shows about a server it has shaken hands with, and where
 * that survives a reload.
 *
 * **A verdict is a network fact with a timestamp, so it is not a property of
 * the server definition.** It is deliberately *not* written to
 * `openstategraph.yaml` beside the URL: that file is committed, and a
 * committed `live` is a claim about somebody else's network made by somebody
 * else's machine, at a time nobody recorded. It lives in this browser, keyed
 * by server name, and the panel re-checks every row when it opens — a badge
 * that is only ever as fresh as the last time you pressed a button is the
 * badge that misleads.
 *
 * The four verdicts are the research's taxonomy verbatim
 * (`.scratch/mcp-connect/research/01-adapters.md` §3). They are four and not
 * one because each sends a developer somewhere completely different: a
 * network, a credential, a URL. Every failure arrives from the library as one
 * opaque `ExceptionGroup`; the runtime unwraps it into these, and collapsing
 * them again here would throw that work away.
 *
 * **The words** those verdicts wear moved to `McpRegistryClient` when a card's
 * row learned to check itself (ticket 04): two readers, one spelling. What
 * stays here is the *memory* — which is what this module's name says.
 */

/** A `localStorage`-shaped thing. Narrow on purpose, as `onceOnlyFlag`'s is. */
export interface StatusStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const MCP_STATUS_KEY = 'openstategraph.mcpStatus';

export interface McpStatusRecord {
  readonly status: McpStatus;
  /** The runtime's own sentence — never a stack trace. */
  readonly message: string;
  /** What `list_tools` found. The reason Validate takes the second round trip. */
  readonly tools: readonly string[];
  /** When this browser learned it, so the panel can say how old it is. */
  readonly checkedAt: number;
}

/**
 * Green means one thing only.
 *
 * The three failures share a tone because the *tone* answers "can this bind
 * right now", which they answer identically; the word beside it is what says
 * where to go, and that is where they differ.
 */
export const mcpStatusTone = (status: McpStatus): 'success' | 'danger' =>
  status === 'live' ? 'success' : 'danger';

const asStatus = (value: unknown): McpStatus =>
  // Same rounding as the client's: an unrecognised verdict is one nobody
  // understood, and a green badge is not the safe way to round that.
  MCP_STATUSES.includes(value as McpStatus) ? (value as McpStatus) : 'not_mcp';

function ambientStorage(): StatusStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * The verdicts this browser has seen, by server name.
 *
 * One key holding a map rather than a key per server, because the panel reads
 * them all at once and a server can be renamed — a per-server key would leave
 * an orphan behind that nothing ever collects.
 */
export class McpStatusMemory {
  constructor(private readonly storage: StatusStorage | null = ambientStorage()) {}

  recall(name: string): McpStatusRecord | null {
    const row = this.all()[name];
    return row ?? null;
  }

  remember(name: string, record: McpStatusRecord): void {
    this.write({ ...this.all(), [name]: record });
  }

  /** Drop what is known about a server, e.g. one that has just been deleted. */
  forget(name: string): void {
    const all = { ...this.all() };
    delete all[name];
    this.write(all);
  }

  all(): Record<string, McpStatusRecord> {
    try {
      const raw = this.storage?.getItem(MCP_STATUS_KEY) ?? null;
      if (!raw) return {};
      const parsed = JSON.parse(raw) as Record<string, Partial<McpStatusRecord>>;
      const rows: Record<string, McpStatusRecord> = {};
      for (const [name, row] of Object.entries(parsed ?? {})) {
        rows[name] = {
          status: asStatus(row?.status),
          message: typeof row?.message === 'string' ? row.message : '',
          tools: Array.isArray(row?.tools) ? row.tools.map(String) : [],
          checkedAt: typeof row?.checkedAt === 'number' ? row.checkedAt : 0,
        };
      }
      return rows;
    } catch {
      // Written by an older shape, or by something else entirely. Forgetting
      // it costs one re-check, which the panel does on open regardless.
      return {};
    }
  }

  private write(rows: Record<string, McpStatusRecord>): void {
    try {
      this.storage?.setItem(MCP_STATUS_KEY, JSON.stringify(rows));
    } catch {
      /* nothing carried forward; the panel re-checks on open anyway */
    }
  }
}
