import { Err, Ok, type Result } from '@core/kernel/Result';
import { describeRuntimeBase, runtimeBaseUrl } from './runtimeBaseUrl';

/**
 * File-backed workflow persistence (tickets 10/14/16).
 *
 * The browser cannot write to disk — the File System Access API is
 * Chromium-only and permission-gated, not a production answer (ticket 16's
 * own hard constraint) — so this, like `RuntimeClient`, only ever posts a
 * document and receives one back. `workflows/<slug>/workflow.json` on the
 * backend is the actual source of truth; this class holds no file handles
 * and knows nothing about the filesystem.
 *
 * Same shape as `RuntimeClient` on purpose: one class, `fetch` injected for
 * testability under Vitest's node environment, errors turned into a message
 * a developer can act on rather than a raw status code.
 */

/** A stable, filesystem-safe identity, derived once from a name and never
 * recomputed on a later rename — see `workflow_store.py`'s own docstring on
 * why the slug is frozen. Kept in lockstep with the backend's `slugify()`;
 * the backend is the enforcement point (a mismatched slug is a 422), this is
 * only what lets the frontend compute the *same* one client-side.
 */
export function slugify(name: string): string {
  const slug = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'workflow';
}

export interface WorkflowSummary {
  readonly slug: string;
  readonly name: string;
  readonly savedAt: string;
  readonly nodeCount: number;
  readonly edgeCount: number;
  /** Draft→publish lifecycle (launch-readiness ticket 04): drafts stay off
   * the customer /chat surface. A backend row without the field counts as
   * published — the same back-compat default the backend applies. */
  readonly published: boolean;
}

/** Ticket 18: one `BaseTool` subclass discovered in a workflow's `tools/` folder. */
export interface ToolCapability {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly argsSchema: Record<string, unknown>;
}

/** One control a plugin's tool asks the editor to put on its card. */
export interface PluginToolField {
  readonly key: string;
  readonly label: string;
  /** `text` | `textarea` | `select` | `toggle` | `number`; anything else is text. */
  readonly kind: string;
  readonly defaultValue: string | number | boolean;
  readonly placeholder: string;
  readonly hint: string;
  readonly options: readonly { readonly value: string; readonly label: string }[];
}

/**
 * A tool contributed by an **installed distribution** (register PK-06).
 *
 * Reported separately from `tools` because the two have different lifetimes,
 * and the palette says so: a workflow's own tool disappears when another
 * workflow is opened; a plugin's is available in every workflow until it is
 * uninstalled. Its `nodeType` **is** its id — a plugin's tool is process-wide,
 * so unlike a workflow-local capability there is no slug to qualify it with,
 * and the document binds the same string at both ends.
 */
export interface PluginToolCapability {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly argsSchema: Record<string, unknown>;
  readonly nodeType: string;
  /** The distribution that shipped it — always shown, never inferred. */
  readonly distribution: string;
  readonly fields: readonly PluginToolField[];
  /** True when it replaces a bundled tool of the same node type. */
  readonly replacesBuiltin: boolean;
}

export interface WorkflowCapabilities {
  readonly tools: readonly ToolCapability[];
  /** App-scoped tools installed distributions contribute. */
  readonly pluginTools: readonly PluginToolCapability[];
  /**
   * Everything that failed to appear, and everything that appeared under
   * someone else's name: a tool module that would not import, a plugin that
   * replaced a built-in, a Python tool with no editor card at all. The
   * capability-warning channel, applied to discovery — a developer who
   * authored half a tool must get a message, not silence.
   */
  readonly warnings: readonly string[];
}

/**
 * One starting point offered by `openstategraph new` (scale-and-adopt ticket
 * 04), already rendered into a document the canvas can import.
 *
 * A template is a **scaffold input**: it produces a document and stops
 * existing. Nothing here is a node type, and no saved workflow records which
 * template it came from — a document with a second, invisible owner is exactly
 * what this boundary exists to prevent.
 */
export interface WorkflowTemplate {
  readonly name: string;
  /** One line, shown beside the name in the picker. */
  readonly summary: string;
  /** A v2 workflow document, ready for `document.importJSON`. */
  readonly document: unknown;
}

/**
 * The scaffold catalogue, read over HTTP — its own interface, for the same
 * reason `ICatalogueEvents` is: `loadWorkflowIntoEditor` persists documents
 * and has no business declaring a method about starting points it never asks
 * for. One class implements all three, because it is one backend.
 *
 * There is deliberately **no second list** in the frontend. The templates the
 * editor offers are the ones `openstategraph new --list-templates` prints,
 * fetched from the package that owns them; a TypeScript copy would agree on
 * the day it was written and drift on the first port rename.
 */
export interface IWorkflowTemplates {
  /** `name` is substituted into the returned documents, so a template that
   * titles a node after the workflow comes back correct rather than close. */
  templates(name: string): Promise<Result<readonly WorkflowTemplate[], string>>;
}

export interface IWorkflowFileClient {
  list(): Promise<Result<readonly WorkflowSummary[], string>>;
  load(slug: string): Promise<Result<unknown, string>>;
  loadIfPresent(slug: string): Promise<Result<unknown | null, string>>;
  save(slug: string, name: string, document: unknown): Promise<Result<void, string>>;
  remove(slug: string): Promise<Result<void, string>>;
  setPublished(slug: string, published: boolean): Promise<Result<void, string>>;
  capabilities(slug: string): Promise<Result<WorkflowCapabilities, string>>;
  compiledGraph(slug: string): Promise<Result<string, string>>;
}

/** Why the catalogue changed — the backend's `workflows.changed` vocabulary. */
export type CatalogueChangeReason = 'published' | 'unpublished' | 'saved' | 'deleted';

/**
 * One live catalogue change.
 *
 * A **hint, not a row**: it says what moved, never what the catalogue now
 * contains. A listener refetches, so there is exactly one spelling of the list
 * and no event-built cache that can drift from it.
 */
export interface CatalogueChange {
  readonly reason: CatalogueChangeReason;
  readonly slug: string;
  /** Whether that slug is on the customer `/chat` surface after the change. */
  readonly surfaceVisible: boolean;
}

/**
 * Live catalogue changes — deliberately its own interface, not another method
 * on `IWorkflowFileClient`.
 *
 * `loadWorkflowIntoEditor` wants to load a document and nothing else; making it
 * declare a subscription it never opens is the Interface Segregation failure
 * this codebase keeps `INodeExecutor` and `IToolExecutor` apart to avoid. One
 * class implements both, because it is one backend and one base URL.
 */
export interface ICatalogueEvents {
  /** Subscribe until the returned function is called. */
  watchCatalogue(onChange: (change: CatalogueChange) => void): () => void;
}

export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

/** Just enough of `EventSource` to be faked in a test with no DOM. */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}
export type EventSourceFactory = (url: string) => EventSourceLike;

export class WorkflowFileClient implements IWorkflowFileClient, ICatalogueEvents, IWorkflowTemplates {
  constructor(
    private readonly baseUrl: string = runtimeBaseUrl(),
    private readonly fetchImpl: FetchLike = (url, init) => fetch(url, init),
    /** Injected only by tests — Vitest's node environment has no `EventSource`. */
    private readonly eventSourceImpl: EventSourceFactory | null = typeof EventSource === 'undefined'
      ? null
      : (url) => new EventSource(url),
  ) {}

  /**
   * Catalogue changes as they happen, over the backend's `/api/events` SSE
   * stream — so a second tab publishing shows up in this one's Workflows panel
   * without a reload.
   *
   * SSE and not a WebSocket because the flow is one-way and `EventSource`
   * reconnects by itself; the same reasoning, and the same endpoint, `/chat`
   * uses. Where `EventSource` is unavailable (an old browser, a unit test) this
   * returns a no-op unsubscribe and the panel keeps its refresh-on-open
   * behaviour — a live update is an improvement, never a dependency.
   *
   * Limits inherited from the backend, worth knowing at the call site: the
   * fan-out is in-process, so it covers one worker (the documented ceiling),
   * and a `workflow.json` edited by hand on disk emits nothing — the editor
   * writes through the API, a text editor does not.
   */
  watchCatalogue(onChange: (change: CatalogueChange) => void): () => void {
    if (!this.eventSourceImpl) return () => {};
    const source = this.eventSourceImpl(`${this.baseUrl}/api/events`);
    source.addEventListener('workflows.changed', (event) => {
      try {
        const record = JSON.parse(event.data as string) as Record<string, unknown>;
        onChange({
          reason: asString(record['reason']) as CatalogueChangeReason,
          slug: asString(record['slug']),
          surfaceVisible: record['surface_visible'] === true,
        });
      } catch {
        // One unparseable frame is not a reason to tear the stream down — the
        // next is very likely fine, and the listener refetches regardless.
      }
    });
    // Closing here is what frees the server's subscription, rather than
    // leaving it for a socket timeout that may never come.
    return () => source.close();
  }

  /**
   * The base said out loud. Same-origin resolves to an empty prefix, which is
   * exactly right in a URL and meaningless in a sentence.
   */
  private unreachable(): string {
    return `Could not reach the runtime at ${describeRuntimeBase(this.baseUrl)}. Is the backend running?`;
  }

  async list(): Promise<Result<readonly WorkflowSummary[], string>> {
    let response: Response;
    try {
      // The editor's surface is explicit: everything non-hidden, drafts
      // included, each row carrying its `published` flag. `/chat` asks for
      // `surface=chat` and sees published workflows only.
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows?surface=editor`);
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as unknown[];
      return Ok(
        payload.map((entry) => {
          const record = entry as Record<string, unknown>;
          return {
            slug: asString(record['slug']),
            name: asString(record['name']),
            savedAt: asString(record['saved_at']),
            nodeCount: typeof record['node_count'] === 'number' ? record['node_count'] : 0,
            edgeCount: typeof record['edge_count'] === 'number' ? record['edge_count'] : 0,
            published: record['published'] !== false,
          };
        }),
      );
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  /**
   * The scaffold's templates, rendered for `name`.
   *
   * Failure is a plain `Err`, and the caller treats it as "offer a blank
   * canvas only": a backend too old to know this endpoint must cost a user
   * their template picker, never their ability to start a workflow.
   */
  async templates(name: string): Promise<Result<readonly WorkflowTemplate[], string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/templates?name=${encodeURIComponent(name)}`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as unknown[];
      return Ok(
        payload.map((entry) => {
          const record = entry as Record<string, unknown>;
          return {
            name: asString(record['name']),
            summary: asString(record['summary']),
            document: record['document'],
          };
        }),
      );
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  async load(slug: string): Promise<Result<unknown, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`);
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as { document?: unknown };
      return Ok(payload.document);
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  /**
   * `load`, but "there is no such workflow" is an **answer, not a failure**.
   *
   * A slug typed into a mount node is a reference that may not resolve yet —
   * half-typed, or renamed since. `load` folds that into the same `Err`
   * channel as "the backend is down", and a caller that only wants to
   * annotate a card must tell those apart: one says *unknown workflow*, the
   * other must say nothing at all rather than accuse the document.
   */
  async loadIfPresent(slug: string): Promise<Result<unknown | null, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`);
    } catch {
      return Err(this.unreachable());
    }
    if (response.status === 404) return Ok(null);
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as { document?: unknown };
      return Ok(payload.document ?? null);
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  async save(slug: string, name: string, document: unknown): Promise<Result<void, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name, document }),
      });
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));
    return Ok(undefined);
  }

  async remove(slug: string): Promise<Result<void, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`, {
        method: 'DELETE',
      });
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));
    return Ok(undefined);
  }

  /**
   * Flip the draft→publish flag (launch-readiness ticket 04). One endpoint
   * for both directions — the flag IS the whole lifecycle state. Publishing
   * never rebuilds concierge routing knowledge as a side effect; the backend
   * response carries a note saying it can be rebuilt.
   */
  async setPublished(slug: string, published: boolean): Promise<Result<void, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}/publish`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ published }),
        },
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));
    return Ok(undefined);
  }

  /**
   * Ticket 18: what this saved workflow's own `tools/`/`functions/` folders
   * offer, discovered by the backend importing them — not a static
   * registration. An unsaved, canvas-only workflow has no folder yet, so
   * callers should expect this to fail harmlessly for one.
   */
  /**
   * The COMPILED topology as Mermaid text (ticket 54): what the backend
   * compiler actually produced, subgraphs expanded — never a hand-drawn
   * approximation, and never a PNG (that would post the graph to a third
   * party).
   */
  async compiledGraph(slug: string): Promise<Result<string, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}/graph`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));
    const payload = (await response.json()) as { mermaid?: string };
    return typeof payload.mermaid === 'string'
      ? Ok(payload.mermaid)
      : Err('The runtime returned no diagram.');
  }

  async capabilities(slug: string): Promise<Result<WorkflowCapabilities, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}/capabilities`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as {
        tools?: unknown[];
        plugin_tools?: unknown[];
        warnings?: unknown[];
      };
      const tools = Array.isArray(payload.tools) ? payload.tools : [];
      // Every list defaults to empty rather than failing the parse: an older
      // backend that predates plugin capabilities must still load a workflow,
      // and a missing key is exactly the "nothing to report" it looks like.
      const pluginTools = Array.isArray(payload.plugin_tools) ? payload.plugin_tools : [];
      const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
      return Ok({
        tools: tools.map((entry) => {
          const record = entry as Record<string, unknown>;
          return {
            id: asString(record['id']),
            name: asString(record['name']),
            description: asString(record['description']),
            argsSchema: (record['args_schema'] as Record<string, unknown>) ?? {},
          };
        }),
        pluginTools: pluginTools.map((entry) => asPluginTool(entry as Record<string, unknown>)),
        warnings: warnings.filter((w): w is string => typeof w === 'string'),
      });
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string' && payload.detail) return payload.detail;
  } catch {
    // fall through to the generic message below
  }
  if (response.status === 404) return 'That workflow does not exist on the backend.';
  return `The runtime returned ${response.status}`;
}

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');

/** One `plugin_tools` row, snake_case on the wire, camelCase in the editor. */
function asPluginTool(record: Record<string, unknown>): PluginToolCapability {
  const fields = Array.isArray(record['fields']) ? record['fields'] : [];
  const nodeType = asString(record['node_type']);
  return {
    id: asString(record['id']) || nodeType,
    name: asString(record['name']),
    description: asString(record['description']),
    argsSchema: (record['args_schema'] as Record<string, unknown>) ?? {},
    nodeType,
    distribution: asString(record['distribution']),
    fields: fields.map((entry) => asPluginField(entry as Record<string, unknown>)),
    replacesBuiltin: record['replaces_builtin'] === true,
  };
}

function asPluginField(record: Record<string, unknown>): PluginToolField {
  const raw = record['default_value'];
  const options = Array.isArray(record['options']) ? record['options'] : [];
  return {
    key: asString(record['key']),
    label: asString(record['label']),
    kind: asString(record['kind']) || 'text',
    defaultValue:
      typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean' ? raw : '',
    placeholder: asString(record['placeholder']),
    hint: asString(record['hint']),
    options: options.map((entry) => {
      const option = entry as Record<string, unknown>;
      return { value: asString(option['value']), label: asString(option['label']) };
    }),
  };
}
