import { Err, Ok, type Result } from '@core/kernel/Result';
import { formatMountAddress, isInstance, type MountAddress } from '@core/model/MountAddress';
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

/*
 * There used to be a `slugify()` here, "kept in lockstep with the backend's",
 * and `WorkflowManager` minted a new workflow's slug with it. Ticket 20
 * removed it, because a slug is not a transform of a name — it is an identity
 * nobody else holds, and only the process that can see `workflows/` knows
 * which ones are taken. Two workflows named "My Workflow" both minted
 * `my-workflow` here and the second `PUT` silently overwrote the first.
 * `create()` below asks the backend to mint instead, and the response says
 * which slug it got. Nothing in the editor derives a slug from a name.
 */

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
  /**
   * Ticket 21: whether a **customer** surface advertises this package.
   *
   * Meaningful on every row, `list()` included. That endpoint is the
   * *editor's* surface and returns hidden packages with the flag set, so the
   * UI can mark one rather than pretend it is not there — the backend decided
   * that deliberately (launch-readiness ticket 04,
   * `api/routes/workflows.py::list_workflows`), and the editor depends on it:
   * the mount combobox is fed from `list()` via `WorkflowCatalogue`, and
   * `concierge` mounts `workflow-architect`, which is hidden. Filtering here
   * would make a shipped composition undrawable.
   *
   * `hidden` is absolute on `surface=chat` only, which is the customer's.
   *
   * (Until production-ready ticket 33 this said "always `false` on a row from
   * `list()` — that endpoint omits hidden packages outright". It never did,
   * on the editor surface; the Packages palette and the mount combobox both
   * matched the behaviour, and this sentence was the odd one out.)
   */
  readonly hidden: boolean;
}

/** Ticket 18: one `BaseTool` subclass discovered in a workflow's `tools/` folder. */
export interface ToolCapability {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly argsSchema: Record<string, unknown>;
  /**
   * The hand-authored editor card meant to represent this tool, or `''`.
   *
   * A Python `BaseTool` declares it (`node_type`) and the backend has always
   * sent it; `workflowScoped.isAlreadyHandAuthored` is the consumer, and its
   * whole job is to stop discovery minting a generic twin of a card that
   * already exists. Declaring it here is not decoration — the field was read
   * before it was declared or parsed, so at runtime it was `undefined`, the
   * guard could never fire, and the palette listed every Chinook tool twice
   * (ticket 32). The repository's `tsc --noEmit` gate resolves a solution-style
   * config with `files: []`, so the type error that would have said so was
   * never reported.
   */
  readonly nodeType: string;
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

/**
 * One worked example shipped inside the distribution (workflow-gallery ticket
 * 07) — a **package**, not a document, which is the difference from
 * `WorkflowTemplate`.
 *
 * There is no `document` field here on purpose. An example carries its tests,
 * its knowledge store, its eval fixture and (for `sql-qa`) a database; a
 * canvas that imported the document alone would produce nodes bound to tools
 * that do not exist in the result. So taking one is a copy the backend
 * performs, and `requires` says beforehand which directories that will write.
 */
export interface WorkflowExample {
  readonly slug: string;
  readonly name: string;
  /** One line, the package's own `settings.purpose`. */
  readonly summary: string;
  /** What shape it demonstrates — "revision loop", "orchestrator-worker". */
  readonly pattern: string;
  /** This slug first, then every package it mounts, transitively. */
  readonly requires: readonly string[];
}

/**
 * The shipped gallery, read over HTTP — its own interface for the same reason
 * `IWorkflowTemplates` is one: a consumer that only ever loads documents has
 * no business declaring methods about examples it never asks for.
 *
 * The examples are **not** in `list()`. They live outside the workflows root,
 * so they cannot pollute the user's own catalogue however they are flagged;
 * copying one is what puts a package in it, and from that moment it is an
 * ordinary draft of theirs.
 */
export interface IWorkflowExamples {
  examples(): Promise<Result<readonly WorkflowExample[], string>>;
  /** Resolves with every slug written, the requested one first. */
  copyExample(slug: string): Promise<Result<readonly string[], string>>;
}

/**
 * One mounted **instance**, as it actually runs — ticket 42.
 *
 * `document` is the child package with this mount's `data.overrides` already
 * merged in, done on the backend because the merge has exactly one owner
 * (`apply_mount_overrides`) and a second implementation here would be
 * duplicated knowledge buying only a round trip.
 *
 * `slug` is the **class** the instance is of, and it is not redundant: the
 * address names the instance, but capabilities, knowledge, the SQL schema and
 * the palette are all questions about the package, and only the backend can
 * say which package sits at the end of a chain of mount ids.
 */
export interface LoadedMount {
  readonly slug: string;
  readonly document: unknown;
  /** Loud-but-not-fatal merge reports — an override naming a node that is gone. */
  readonly warnings: readonly string[];
}

/**
 * What `POST /api/workflows/{slug}/duplicate` answers with (ticket 01).
 *
 * The slug is the part a caller cannot predict and the part it needs next, to
 * open the copy or put it in the address bar. The name comes back too because
 * the backend defaults it — the obvious "<original> (copy)" depends on the
 * original's name, which a client would have to fetch to compute.
 */
export interface DuplicatedWorkflow {
  readonly slug: string;
  readonly name: string;
  /** The package this was copied from, unchanged by the operation. */
  readonly source: string;
}

export interface IWorkflowFileClient {
  list(): Promise<Result<readonly WorkflowSummary[], string>>;
  summary(slug: string): Promise<Result<WorkflowSummary | null, string>>;
  load(slug: string): Promise<Result<unknown, string>>;
  /** The effective document for one mount — see `LoadedMount`. */
  loadMount(
    address: MountAddress,
    options?: { inherited?: boolean },
  ): Promise<Result<LoadedMount, string>>;
  loadIfPresent(slug: string): Promise<Result<unknown | null, string>>;
  /** Create a workflow and receive the slug the backend minted for it. */
  create(name: string, document: unknown): Promise<Result<string, string>>;
  save(slug: string, name: string, document: unknown): Promise<Result<void, string>>;
  remove(slug: string): Promise<Result<void, string>>;
  setPublished(slug: string, published: boolean): Promise<Result<void, string>>;
  /** Copy a whole package to a new slug — see `DuplicatedWorkflow`. */
  duplicate(slug: string, name?: string): Promise<Result<DuplicatedWorkflow, string>>;
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

export class WorkflowFileClient
  implements IWorkflowFileClient, ICatalogueEvents, IWorkflowTemplates, IWorkflowExamples
{
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
      // The editor's surface is explicit: everything the developer owns —
      // drafts AND hidden packages included, each row carrying `published`
      // and `hidden` so the UI can mark a package rather than lose it.
      // `/chat` asks for `surface=chat` and sees published, non-hidden only.
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows?surface=editor`);
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as unknown[];
      return Ok(payload.map((entry) => asSummary(entry as Record<string, unknown>)));
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  /**
   * Does **this one** workflow exist, and when was it last saved?
   *
   * Ticket 21's seam. `list()` is a *surface* — it answers what a picker
   * should offer, and a surface omits things that exist: unreadable packages
   * on either surface, and hidden ones (`concierge`, `workflow-architect`) on
   * `surface=chat`. Scanning that list for your own slug and concluding
   * "deleted" on a miss reads a visibility answer as an existence answer,
   * which is precisely how the file watch came to announce "This workflow was
   * deleted on disk" over a file the backend was serving 200.
   *
   * So this asks the backend about the slug directly, and **`Ok(null)` — a 404
   * — is the only "it is gone"**. An unreachable backend or a 500 stays an
   * `Err`, because "I could not ask" must never be mistaken for "the answer is
   * no": that would turn every network blip into a deletion warning.
   */
  async summary(slug: string): Promise<Result<WorkflowSummary | null, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}/summary`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (response.status === 404) return Ok(null);
    if (!response.ok) return Err(await describeFailure(response));

    try {
      return Ok(asSummary((await response.json()) as Record<string, unknown>));
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

  /**
   * The shipped gallery.
   *
   * Failure degrades the same way `templates` does — an Examples shelf is a
   * shortcut, and a backend too old to know the endpoint must cost a user the
   * shelf, never anything they already have.
   */
  async examples(): Promise<Result<readonly WorkflowExample[], string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/examples`);
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
            summary: asString(record['summary']),
            pattern: asString(record['pattern']),
            requires: Array.isArray(record['requires'])
              ? record['requires'].map(asString)
              : [asString(record['slug'])],
          };
        }),
      );
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  /**
   * Copy one example, and everything it mounts, into this project.
   *
   * The backend does the copying because a package is more than its document;
   * the same reason `duplicate` is a server route. What comes back is every
   * slug that landed, so the caller can refresh its list and open the first.
   */
  async copyExample(slug: string): Promise<Result<readonly string[], string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/examples/${encodeURIComponent(slug)}/copy`,
        { method: 'POST' },
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as Record<string, unknown>;
      const copied = Array.isArray(payload['copied']) ? payload['copied'].map(asString) : [];
      // Without the slugs the copy exists on disk and the caller cannot name
      // it — the same failure `duplicate` refuses to paper over.
      return copied.length > 0
        ? Ok(copied)
        : Err('The runtime copied the example but did not say under which slug.');
    } catch {
      return Err('The runtime copied the example but its answer could not be read.');
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

  async loadMount(
    address: MountAddress,
    options: { inherited?: boolean } = {},
  ): Promise<Result<LoadedMount, string>> {
    if (!isInstance(address)) {
      // Not a fallback to `load`: this method answers about an instance, and
      // quietly becoming the class call would give one question two spellings
      // that can drift. The caller decides which it wants.
      return Err(`${formatMountAddress(address)} names a workflow, not a mount inside one`);
    }
    // Each segment encoded separately — encoding the whole path in one go
    // would turn the separator into `%2F` and the route would stop matching,
    // while leaving segments raw would let a colon in a minted id through
    // unescaped.
    const path = address.mountPath.map((segment) => encodeURIComponent(segment)).join('/');
    const url =
      `${this.baseUrl}/api/workflows/${encodeURIComponent(address.root)}/mounts/${path}` +
      // What this instance would run if it overrode nothing — the value the
      // inspector shows beside an overridden field, and the one a revert puts
      // back. Not computable here: the override has already replaced it.
      (options.inherited ? '?inherited=true' : '');

    let response: Response;
    try {
      response = await this.fetchImpl(url);
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as {
        slug?: unknown;
        document?: unknown;
        warnings?: unknown;
      };
      return Ok({
        slug: asString(payload.slug),
        document: payload.document,
        warnings: Array.isArray(payload.warnings) ? payload.warnings.map(asString) : [],
      });
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

  /**
   * Create a new workflow; the backend mints its slug and tells us which.
   *
   * The one call that must **not** address a slug, because there isn't one
   * yet. Deriving it here from the name is what destroyed work (ticket 20):
   * `slugify` cannot see `workflows/`, so it happily proposed a directory
   * another workflow was already living in and the `PUT` overwrote it. The
   * returned slug is the identity — frozen from here on, never recomputed
   * when the workflow is renamed.
   */
  async create(name: string, document: unknown): Promise<Result<string, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ name, document }),
      });
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as { slug?: unknown };
      return typeof payload.slug === 'string' && payload.slug !== ''
        ? Ok(payload.slug)
        : Err('The runtime created the workflow but did not say under which slug.');
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
  /**
   * Copy a whole package — `tools/`, `tests/`, `knowledge/`, everything.
   *
   * The backend does the copying because a browser cannot: a client-side
   * "load the document, create a new workflow" copies `workflow.json` alone
   * and leaves the copy's nodes bound to tools that are not in it, which
   * fails at run time rather than at copy time.
   *
   * `name` is optional on purpose — omitted, the backend names it
   * `<original> (copy)`, which it can do without the client fetching the
   * original first.
   */
  async duplicate(slug: string, name?: string): Promise<Result<DuplicatedWorkflow, string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}/duplicate`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(name === undefined ? {} : { name }),
        },
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as Partial<DuplicatedWorkflow>;
      // The slug is the whole point of the call: without it the copy exists on
      // disk and the caller cannot name it, which is worse than a clean error.
      return typeof payload.slug === 'string' && payload.slug !== ''
        ? Ok({
            slug: payload.slug,
            name: typeof payload.name === 'string' ? payload.name : payload.slug,
            source: typeof payload.source === 'string' ? payload.source : slug,
          })
        : Err('The runtime copied the workflow but did not say under which slug.');
    } catch {
      return Err('The runtime copied the workflow but its answer could not be read.');
    }
  }

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
            // Dropping this was ticket 32: the field the duplicate-card guard
            // reads never made it off the wire. `asString` gives `''` for a
            // backend that predates it, which the guard treats as "no card
            // declared" — the correct reading of silence.
            nodeType: asString(record['node_type']),
          };
        }),
        pluginTools: pluginTools.map((entry) => asPluginTool(entry as Record<string, unknown>)),
        warnings: warnings.filter((w): w is string => typeof w === 'string'),
      });
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }

  /**
   * The tables this workflow's SQL tools can actually reach.
   *
   * Read from the database the tool opens, never from a list typed into this
   * repository — the whole point of the endpoint. The schema tools take their
   * table as a *model* argument, so this is the agent's field of view, not a
   * per-node selection.
   */
  async sqlSchema(slug: string): Promise<Result<readonly SqlSource[], string>> {
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}/sql-schema`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as { sources?: unknown[] };
      const sources = Array.isArray(payload.sources) ? payload.sources : [];
      return Ok(sources.map((entry) => asSqlSource(entry as Record<string, unknown>)));
    } catch {
      return Err('The runtime returned a response that was not valid JSON');
    }
  }
}

/** One table of one wired database, with the Markdown an agent would get. */
export interface SqlTable {
  readonly name: string;
  readonly detail: string;
}

/** One database this workflow's SQL tool nodes are wired to. */
export interface SqlSource {
  readonly database: string;
  readonly engine: string;
  readonly tables: readonly SqlTable[];
  /** Recognized but not fully readable, or a truncated list. Never silent. */
  readonly warning: string;
}

function asSqlSource(record: Record<string, unknown>): SqlSource {
  const tables = Array.isArray(record['tables']) ? record['tables'] : [];
  return {
    database: asString(record['database']),
    engine: asString(record['engine']),
    tables: tables.map((entry) => {
      const table = entry as Record<string, unknown>;
      return { name: asString(table['name']), detail: asString(table['detail']) };
    }),
    warning: asString(record['warning']),
  };
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

/** One catalogue row, snake_case on the wire — shared by the list and the
 * per-slug summary so the two can never disagree about the same package. */
function asSummary(record: Record<string, unknown>): WorkflowSummary {
  return {
    slug: asString(record['slug']),
    name: asString(record['name']),
    savedAt: asString(record['saved_at']),
    nodeCount: typeof record['node_count'] === 'number' ? record['node_count'] : 0,
    edgeCount: typeof record['edge_count'] === 'number' ? record['edge_count'] : 0,
    published: record['published'] !== false,
    hidden: record['hidden'] === true,
  };
}

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
