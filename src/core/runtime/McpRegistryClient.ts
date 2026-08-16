import { Err, Ok, type Result } from '@core/kernel/Result';
import { describeFailure, type FetchLike } from './RuntimeClient';
import { describeRuntimeBase } from './runtimeBaseUrl';
import { mcpServerCatalogue } from './mcpServerCatalogue';

/**
 * The MCP server registry — a collaborator of `RuntimeClient`, not four more
 * methods on it.
 *
 * CLAUDE.md's ceiling is the reason and it is a real one: `RuntimeClient` was
 * at eight public members and these four would have taken it to twelve, which
 * the census test catches. *"Extend it by adding a collaborator, never a
 * method"* — so `client.mcp.servers()`, and the client gains one member
 * instead of four. The split also happens to be the honest one: a run seam
 * and a project-level registry are two reasons to change.
 *
 * Everything here is names, URLs and booleans. **No request this object makes
 * has a field a credential fits in**: the panel collects the NAME of an
 * environment variable and the runtime resolves it from its own environment
 * at bind time, so a token never enters the browser to be posted back.
 */

/**
 * How one MCP server is authenticated — **the variable name, never a value**.
 *
 * Mirrors `McpAuthPayload`, which has no field a credential fits in. That is
 * the property, not a convention: the browser never holds one, because the
 * value lives in the runtime's environment and is read there at bind time.
 */
export interface McpServerAuth {
  /** `none` · `bearer` · `header`. */
  readonly kind: string;
  /** `header` only — the vendor's own header, e.g. `LANGSMITH-API-KEY`. */
  readonly headerName: string;
  /** The NAME of an environment variable. */
  readonly tokenEnv: string;
}

/** What the panel may save. `origin` and `credentialConfigured` are the
 *  runtime's to decide, so a draft cannot claim either. */
export interface McpServerDraft {
  readonly name: string;
  readonly url: string;
  /** `streamable_http` or `sse`. */
  readonly transport: string;
  readonly auth: McpServerAuth;
}

/** One registered server, as `GET /api/mcp/servers` reports it. */
export interface McpServer extends McpServerDraft {
  /** `built-in` for the two defaults, `project` for a config entry. */
  readonly origin: string;
  /** Whether the named variable is set on the runtime. Presence, not validity. */
  readonly credentialConfigured: boolean;
}

/**
 * The verdicts a handshake can reach — the research's taxonomy, verbatim.
 *
 * They are several and not one because each sends a developer somewhere
 * different: a network, a credential, a URL. Every failure arrives from the
 * library as one opaque `ExceptionGroup`, and the runtime is what unwraps it
 * into these; collapsing them again in the browser would undo that work.
 *
 * `not_installed` is the odd one and the newest (mcp-connect ticket 05): the
 * only verdict that is a fact about the **runtime**, not the server. The
 * `[mcp]` extra is absent, so nothing was contacted at all.
 */
export type McpStatus = 'live' | 'unreachable' | 'auth_required' | 'not_mcp' | 'not_installed';

export const MCP_STATUSES: readonly McpStatus[] = [
  'live',
  'unreachable',
  'auth_required',
  'not_mcp',
  'not_installed',
];

/** One handshake's verdict. `tools` is what a Validate button is actually for. */
export interface McpValidation {
  readonly status: McpStatus;
  readonly message: string;
  readonly serverName: string;
  readonly serverVersion: string;
  readonly tools: readonly string[];
  readonly elapsedSeconds: number;
}

interface McpBadge {
  /** Two or three words, for a badge. */
  readonly label: string;
  /** The sentence to fall back on when the runtime sent none. */
  readonly detail: string;
}

const BADGES: Record<McpStatus, McpBadge> = {
  live: { label: 'live', detail: 'The server answered and offers tools.' },
  unreachable: { label: 'unreachable', detail: 'Nothing answered at that address.' },
  auth_required: {
    label: 'auth required',
    detail: 'The server answered, but rejected the credential.',
  },
  not_mcp: { label: 'not an MCP server', detail: 'Something answered, but it does not speak MCP.' },
  not_installed: {
    label: 'MCP not installed',
    // Every word names something the reader can type. No URL, no server name,
    // and none of the three verbs that imply a socket opened.
    detail: "MCP support is not installed here — pip install 'openstategraph[mcp]'.",
  },
};

/**
 * Every verdict in the words a reader sees.
 *
 * Beside the taxonomy rather than in the panel that first needed it, because
 * the panel is no longer the only reader: since mcp-connect ticket 04 a
 * `tool.mcp` row checks itself from the canvas, and two spellings of
 * *unreachable* would be two things to change when the wording changes.
 */
export const describeMcpStatus = (status: McpStatus): McpBadge => BADGES[status];

/**
 * One handshake, as anything that shows a badge wants it.
 *
 * Three rules live here rather than in each surface. Green means **live** and
 * nothing else. A live server reports the tool *names*, which is what a
 * validate press was actually for — a count proves something answered, the
 * names prove it is the server you meant. And a failure prefers the runtime's
 * own sentence over the badge's: concatenating both printed "Nothing answered
 * at that address." twice, because the runtime's message *is* the taxonomy
 * sentence, and where it differs it is the more specific of the two ("within
 * 15 seconds", "Connected, but the MCP handshake failed").
 */
export function summariseMcpValidation(verdict: McpValidation): {
  ok: boolean;
  label: string;
  detail: string;
} {
  const badge = describeMcpStatus(verdict.status);
  if (verdict.status !== 'live') {
    return { ok: false, label: badge.label, detail: verdict.message || badge.detail };
  }
  const count = verdict.tools.length;
  return {
    ok: true,
    label: badge.label,
    detail: `${count} tool${count === 1 ? '' : 's'}: ${verdict.tools.join(', ')}`,
  };
}

/** Name a registered server, or post a URL to check one before saving it. */
export interface McpValidateRequest {
  readonly server?: string;
  readonly url?: string;
  readonly transport?: string;
  readonly auth?: McpServerAuth;
}

/**
 * Reads and writes what this project can bind.
 *
 * Constructed by `RuntimeClient`, which owns the base URL and the injected
 * `fetch` — the same two dependencies, resolved once.
 */
export class McpRegistryClient {
  constructor(
    private readonly baseUrl: string,
    private readonly fetchImpl: FetchLike,
  ) {}

  /**
   * Which MCP servers this project can bind — the two defaults plus its own.
   *
   * Names, URLs and booleans. `credentialConfigured` is presence, not
   * validity, exactly as `providers()` means it: only a handshake can tell
   * you the second, and that is what `validate()` is for.
   */
  async servers(): Promise<Result<readonly McpServer[], string>> {
    return this.list(`${this.baseUrl}/api/mcp/servers`);
  }

  /**
   * Register or replace one server, by name.
   *
   * The body has four keys and none of them can hold a credential: the panel
   * collects the *name* of an environment variable, and the runtime resolves
   * it from its own environment at bind time. Answers with the whole list,
   * because that is the panel's next question and two round trips is two
   * chances for the panel and the file to disagree.
   */
  async save(server: McpServerDraft): Promise<Result<readonly McpServer[], string>> {
    return this.list(`${this.baseUrl}/api/mcp/servers`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        name: server.name,
        url: server.url,
        transport: server.transport,
        auth: server.auth,
      }),
    });
  }

  /** Remove one server. A built-in default is tombstoned in the project file. */
  async remove(name: string): Promise<Result<readonly McpServer[], string>> {
    return this.list(`${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    });
  }

  /**
   * Built-in defaults this project has hidden.
   *
   * The other half of `remove` on a `default` row, and the reason it needed
   * one: every other route filters `enabled` out before answering, so the
   * editor could not tell a default that had never existed from one somebody
   * deleted last week (mcp-connect ticket 06).
   */
  async hidden(): Promise<Result<readonly string[], string>> {
    return this.names(`${this.baseUrl}/api/mcp/servers/hidden`, 'names');
  }

  /** Lift a tombstone, putting a built-in back as a built-in. */
  async restore(name: string): Promise<Result<readonly McpServer[], string>> {
    return this.list(`${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}/restore`, {
      method: 'POST',
    });
  }

  /**
   * Saved packages whose `tool.mcp` cards name this server.
   *
   * Asked only when somebody is about to press Delete: a card names a server
   * and the project defines it, so deleting one can break a document that is
   * not open, and nothing said so.
   */
  async usage(name: string): Promise<Result<readonly string[], string>> {
    return this.names(`${this.baseUrl}/api/mcp/servers/${encodeURIComponent(name)}/usage`, 'slugs');
  }

  /**
   * The list inside a named envelope, for the two routes that answer with one.
   *
   * An envelope rather than a bare array because `test_openapi_contract`
   * refuses an anonymous response shape, and it is right to: a `list[str]`
   * publishes no clue what the strings are.
   */
  private async names(url: string, key: string): Promise<Result<readonly string[], string>> {
    try {
      const response = await this.fetchImpl(url);
      if (!response.ok) return Err(await describeFailure(response));
      const rows = asRecordOfUnknown(await response.json())[key];
      return Ok((Array.isArray(rows) ? rows : []).map((row) => String(row)));
    } catch {
      return Err(this.unreachable());
    }
  }

  /**
   * Shake hands with one server and report what it offers.
   *
   * **Never a refusal.** Every network outcome comes back as a verdict with a
   * status the panel renders as a badge — that is the map's decision that
   * validation *saves* rather than blocks. An `Err` here means the request
   * never reached the runtime at all, which is a different failure and a
   * different message.
   */
  async validate(request: McpValidateRequest): Promise<Result<McpValidation, string>> {
    try {
      const response = await this.fetchImpl(`${this.baseUrl}/api/mcp/validate`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          server: request.server ?? '',
          url: request.url ?? '',
          transport: request.transport ?? 'streamable_http',
          auth: request.auth ?? { kind: 'none', headerName: '', tokenEnv: '' },
        }),
      });
      if (!response.ok) return Err(await describeFailure(response));
      return Ok(asMcpValidation(asRecordOfUnknown(await response.json())));
    } catch {
      return Err(this.unreachable());
    }
  }

  /**
   * The three registry routes all answer with the list; this reads it once —
   * and publishes it, which is the only reason the `tool.mcp` card's picker
   * knows anything.
   *
   * Here rather than at each caller on purpose. The card's picker was designed
   * to take a live list from the start, and the wiring was simply never done
   * (mcp-connect ticket 07); a fix that asks every future caller to remember
   * to publish is the same defect with a longer fuse. This is the one place
   * every registry answer passes through, so listing, saving and deleting all
   * keep the catalogue current without knowing it exists.
   */
  private async list(
    url: string,
    init?: RequestInit,
  ): Promise<Result<readonly McpServer[], string>> {
    try {
      const response = await this.fetchImpl(url, init);
      if (!response.ok) return Err(await describeFailure(response));
      const rows = (await response.json()) as unknown[];
      const servers = (Array.isArray(rows) ? rows : []).map((row) =>
        asMcpServer(asRecordOfUnknown(row)),
      );
      mcpServerCatalogue.set(servers);
      return Ok(servers);
    } catch {
      return Err(this.unreachable());
    }
  }

  private unreachable(): string {
    return `Could not reach the runtime at ${describeRuntimeBase(this.baseUrl)}. Is the backend running?`;
  }
}

function asMcpAuth(row: Record<string, unknown>): McpServerAuth {
  return {
    kind: asString(row['kind']) || 'none',
    headerName: asString(row['headerName']),
    tokenEnv: asString(row['tokenEnv']),
  };
}

function asMcpServer(row: Record<string, unknown>): McpServer {
  return {
    name: asString(row['name']),
    url: asString(row['url']),
    transport: asString(row['transport']) || 'streamable_http',
    auth: asMcpAuth(asRecordOfUnknown(row['auth'])),
    origin: asString(row['origin']) || 'project',
    credentialConfigured: row['credentialConfigured'] === true,
  };
}

function asMcpValidation(row: Record<string, unknown>): McpValidation {
  const status = asString(row['status']);
  return {
    // A status this client does not know is a server it cannot vouch for, and
    // `not_mcp` is the safe direction to round towards: rounding the other
    // way would paint a green badge on an answer nobody understood.
    status: MCP_STATUSES.includes(status as McpStatus) ? (status as McpStatus) : 'not_mcp',
    message: asString(row['message']),
    serverName: asString(row['serverName']),
    serverVersion: asString(row['serverVersion']),
    tools: Array.isArray(row['tools']) ? row['tools'].map(String) : [],
    elapsedSeconds: typeof row['elapsedSeconds'] === 'number' ? row['elapsedSeconds'] : 0,
  };
}
function asRecordOfUnknown(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');
