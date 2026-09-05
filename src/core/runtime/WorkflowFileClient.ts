import { Err, Ok, type Result } from '@core/kernel/Result';
import { formatMountAddress, isInstance, type MountAddress } from '@core/model/MountAddress';
import { LiveEventStream, liveEvents } from './LiveEventStream';
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

/**
 * What a save that landed hands back — `osg-agent-experience/45`.
 *
 * `digest` is the file's version **after** this write, so a client saving
 * repeatedly quotes the answer to its previous save instead of re-reading the
 * file between keystrokes. Without it the second consecutive autosave would
 * conflict with the first one's own work.
 */
export interface SaveReceipt {
  readonly digest: string;
}

/**
 * Why a save did not happen, and the two cases are not the same event.
 *
 * A union rather than a string because the difference has a consequence a
 * caller must act on: an `error` is something that went wrong, and a
 * `conflict` is somebody else's work sitting in the file. Making it a type
 * means a surface cannot print a conflict as "could not save" by accident —
 * it has to look at `kind` to get the message out.
 */
export type SaveFailure =
  | { readonly kind: 'error'; readonly message: string }
  | {
      readonly kind: 'conflict';
      /** The backend's sentence — one copy owner, on the side that knows. */
      readonly reason: string;
      /** What the file holds now. Saving again quoting this is "keep mine". */
      readonly digest: string;
    };

/** The sentence a surface says. Both shapes carry prose; only the key moves. */
export function saveFailureMessage(failure: SaveFailure): string {
  return failure.kind === 'conflict' ? failure.reason : failure.message;
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
   * The marking that sentence promises is real since ticket 57, and there are
   * exactly two surfaces doing it — the Packages palette and the mount
   * combobox — both from `WorkflowChoice.hidden`, which is where a third one
   * should read it rather than fetching the row again.
   *
   * (Until production-ready ticket 33 this said "always `false` on a row from
   * `list()` — that endpoint omits hidden packages outright". It never did,
   * on the editor surface; the Packages palette and the mount combobox both
   * matched the behaviour, and this sentence was the odd one out.)
   */
  readonly hidden: boolean;
  /**
   * What the backend found wrong with the **package folder** — ticket 49's
   * `validate_package`, one string per line, `"error: …"` blocking and
   * `"warning: …"` advice.
   *
   * Not the document's validation, which the editor derives itself from the
   * same rules in `core/model` and is right not to re-read. These are facts
   * only a process that can open `workflows/<slug>/` can know: no
   * `workflow.json` at all, a `workflow.json` that will not parse, `tools/`
   * with no `tests/` beside it. A package in the first two states cannot run,
   * and until `the-cost-of-one-more/14` its row in the Workflows panel looked
   * exactly like a healthy one.
   *
   * Empty is the answer, not the absence of one — the contract defaults it to
   * `[]`, and a row from an older backend that omits the key is a row with
   * nothing to report rather than a row that was not checked.
   */
  readonly findings: readonly string[];
  /**
   * The digest of the bytes this row was read from (`osg-agent-experience/45`).
   *
   * Opaque — nothing here computes or compares it against a document; it is
   * quoted back to the backend on a save so a file that moved in between is
   * refused rather than overwritten. Empty means the backend could not say,
   * which a caller must read as *unknown*, never as *unchanged*: a row from a
   * backend that predates the field, or a package caught mid-write, both
   * arrive that way, and treating either as a match would turn the guard off
   * exactly when it matters.
   */
  readonly digest: string;
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

/**
 * One top-level callable discovered in a workflow's `functions/` folder.
 *
 * Reported by the backend since ticket 18 and dropped on the floor by this
 * client until `export-and-eject/01` — which is the whole of why a function
 * that ran perfectly well could not be put on a canvas.
 *
 * Note what is **not** here: a `nodeType`. A tool declares the card meant to
 * represent it; a function's identity is its name, and the node type a
 * document must name is derived from it by the runtime's own convention —
 * see `nodes/functions/DiscoveredFunctionNode.ts`.
 */
export interface FunctionCapability {
  readonly id: string;
  readonly name: string;
  /** The function's own docstring, or `''`. Becomes card copy, never config. */
  readonly docstring: string;
  /** `(text: str) -> str` — the contract, shown verbatim rather than parsed. */
  readonly signature: string;
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
  /**
   * Tool names **every agent on this server** binds without being wired —
   * today the prebuilt memory tools, and only when a store is configured
   * (`every-workflow-green` 05a).
   *
   * Empty is a real answer, not a missing one: a server with no store binds
   * none. Defaulted here rather than left optional so a backend that predates
   * the field reads as "binds none" instead of `undefined`, which is the same
   * courtesy `pluginTools` already gets one line down.
   */
  readonly ambientTools: readonly string[];
  /**
   * The package's own `functions/` folder — plain Python between two nodes.
   *
   * Same lifetime as `tools`: a function belongs to the open package and
   * leaves the palette when another one is opened. Defaulted to empty for a
   * backend that predates the field, exactly as the lists around it are.
   */
  readonly functions: readonly FunctionCapability[];
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
 * Who mounts a package, before a "push to package" writes it —
 * `production-ready` ticket 17.
 *
 * `count` is every direct mount of the package across the whole workspace,
 * so the confirmation dialog can name how many instances change.
 * `shadowedHosts` names the packages whose mount already overrides this
 * exact field, so the dialog can say those instances will not see the
 * correction — the shadowing warning the ticket requires, not an
 * afterthought.
 */
export interface MountUsage {
  readonly count: number;
  readonly shadowedHosts: readonly string[];
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
  /** Who mounts `slug` and would be affected by pushing this field to it. */
  mountUsage(slug: string, childNodeId: string, key: string): Promise<Result<MountUsage, string>>;
  loadIfPresent(slug: string): Promise<Result<unknown | null, string>>;
  /** Create a workflow and receive the slug the backend minted for it. */
  create(name: string, document: unknown): Promise<Result<string, string>>;
  save(
    slug: string,
    name: string,
    document: unknown,
    baseDigest?: string,
  ): Promise<Result<SaveReceipt, SaveFailure>>;
  remove(slug: string): Promise<Result<void, string>>;
  setPublished(slug: string, published: boolean): Promise<Result<PublishOutcome, string>>;
  /** Copy a whole package to a new slug — see `DuplicatedWorkflow`. */
  duplicate(slug: string, name?: string): Promise<Result<DuplicatedWorkflow, string>>;
  capabilities(slug: string): Promise<Result<WorkflowCapabilities, string>>;
  compiledGraph(slug: string): Promise<Result<string, string>>;
}

/**
 * What `POST /api/workflows/{slug}/publish` answered with, beyond the flag.
 *
 * **The note was dropped on the floor until `the-cost-of-one-more/18`** — by a
 * method whose own docstring named the note it was dropping. The backend
 * sends it because publishing deliberately does *not* rebuild concierge
 * routing knowledge as a side effect (`routes/workflows.py::publish_workflow`:
 * knowledge builds are build-time-only), so a developer publishes, sees
 * *"customers can find it in their list"*, and never learns that automatic
 * routing will not send anyone there until somebody rebuilds.
 *
 * It is carried **verbatim and unread by this client**, which has no opinion
 * about wording. What a surface may do with it is the other half of that
 * ticket, and the answer is *not* "print it": the sentence names an HTTP verb
 * and a path template, and it is addressed to an API caller. `consequences.ts`
 * reads its **presence** — the backend still declining to rebuild — and writes
 * the editor's own sentence about the editor's own control.
 *
 * `null` when the response carried none, so a build that did rebuild on
 * publish makes the toast stop claiming otherwise rather than requiring this
 * client to be edited.
 */
export interface PublishOutcome {
  readonly note: string | null;
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

/** One package's `workflow.json` now holds different bytes. */
export interface WorkflowDocumentChange {
  readonly slug: string;
  /** The revision — the digest a save quotes back as `base_digest`. */
  readonly digest: string;
}

/**
 * A different subject from `ICatalogueEvents`, and so a different interface.
 *
 * A catalogue change says a package appeared, vanished or changed visibility
 * and every open surface cares; this says one package's document has new
 * bytes and only a tab editing that package cares. `/chat` implements neither
 * and consumes only the first — which is the Interface Segregation reason
 * these are not one wider `ILiveEvents` (`osg-agent-experience/71`).
 */
export interface IWorkflowDocumentEvents {
  /** Subscribe until the returned function is called. */
  watchWorkflow(slug: string, onChange: (change: WorkflowDocumentChange) => void): () => void;
}

export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

export class WorkflowFileClient
  implements
    IWorkflowFileClient,
    ICatalogueEvents,
    IWorkflowDocumentEvents,
    IWorkflowTemplates,
    IWorkflowExamples
{
  constructor(
    private readonly baseUrl: string = runtimeBaseUrl(),
    private readonly fetchImpl: FetchLike = (url, init) => fetch(url, init),
    /**
     * The tab's one live connection, shared with every other client object
     * — `osg-agent-experience/71`. This used to be an `EventSourceFactory`
     * and this class used to open its own socket; a browser allows six per
     * origin and an editor tab spent three, so two tabs on one workflow
     * saturated the budget and the last stream never left `CONNECTING`.
     * Injected only by tests, and `null` where `EventSource` does not exist.
     */
    private readonly live: LiveEventStream | null = liveEvents,
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
   * **The socket is not this object's** (`osg-agent-experience/71`).
   * `LiveEventStream` owns the tab's one connection and this asks it for the
   * catalogue subject; the parsing stays here, because the wire shape of a
   * catalogue frame is this client's knowledge and not the connection's.
   *
   * Limits inherited from the backend, worth knowing at the call site: the
   * fan-out is in-process, so it covers one worker (the documented ceiling),
   * and a `workflow.json` edited by hand on disk emits no *catalogue* event —
   * the editor writes through the API, a text editor does not. That gap is
   * what `watchWorkflow` below covers, on the same connection.
   */
  watchCatalogue(onChange: (change: CatalogueChange) => void): () => void {
    if (!this.live) return () => {};
    return this.live.subscribe({ topic: 'catalogue' }, (record) => {
      onChange({
        reason: asString(record['reason']) as CatalogueChangeReason,
        slug: asString(record['slug']),
        surfaceVisible: record['surface_visible'] === true,
      });
    });
  }

  /**
   * One package's document changing on disk, whoever wrote it —
   * `osg-agent-experience/69`, reaching the editor at last through `71`.
   *
   * A `workflow.json` has four kinds of writer — this tab, a second tab, the
   * CLI, a coding agent through the MCP server — and only the first of them
   * goes through the save route, so `watchCatalogue` above hears one in four.
   * The backend watches the **file**, which covers all of them by
   * construction.
   *
   * The frame carries the slug and the digest and nothing else: the digest is
   * the revision, the same string a save quotes back as `base_digest`, so a
   * tab can tell its own write from somebody else's without diffing
   * documents. A caller that decides to take the change refetches through
   * `load`, the one spelling of a document.
   */
  watchWorkflow(slug: string, onChange: (change: WorkflowDocumentChange) => void): () => void {
    if (!this.live) return () => {};
    return this.live.subscribe({ topic: 'workflow', slug }, (record) => {
      onChange({ slug: asString(record['slug']), digest: asString(record['digest']) });
    });
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
   * Who mounts `slug`, before a "push to package" write lands there — see
   * `MountUsage`.
   */
  async mountUsage(
    slug: string,
    childNodeId: string,
    key: string,
  ): Promise<Result<MountUsage, string>> {
    const params = new URLSearchParams({ child_node_id: childNodeId, key });
    let response: Response;
    try {
      response = await this.fetchImpl(
        `${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}/mount-usage?${params.toString()}`,
      );
    } catch {
      return Err(this.unreachable());
    }
    if (!response.ok) return Err(await describeFailure(response));

    try {
      const payload = (await response.json()) as { count?: unknown; shadowed_hosts?: unknown };
      return Ok({
        count: typeof payload.count === 'number' ? payload.count : 0,
        shadowedHosts: Array.isArray(payload.shadowed_hosts)
          ? payload.shadowed_hosts.map(asString)
          : [],
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

  /**
   * Overwrite a package this editor already holds — **and never create one.**
   *
   * `PUT /api/workflows/{slug}` creates a package when the slug is free, on
   * purpose: naming a directory explicitly is how the CLI, a script and a test
   * write a package they intend to own. It is the wrong answer for exactly one
   * caller, and that caller is this one.
   *
   * launch-readiness 147, reproduced live twice. Another tab deletes the open
   * workflow; this tab is told within five seconds and keeps its autosave
   * baseline; somebody types **one character**; the `PUT` re-creates the
   * directory holding `workflow.json` and `AGENTS.md`, and the `tools/`,
   * `functions/`, `tests/`, `skills/`, `middlewares/` and `data/` that made
   * the workflow work are gone for good — with `published` reset to `False`,
   * no prompt, no toast and no error, because the save genuinely succeeded.
   *
   * So `must_exist` goes on every save this client makes. It costs nothing to
   * say and is true of all of them: a document with no slug is created through
   * `create`, which is what mints the slug in the first place. The flag rather
   * than a `summary` call first, because two round trips have a delete-shaped
   * gap between them — the store answers the existence question in the same
   * call that does the write.
   */
  async save(
    slug: string,
    name: string,
    document: unknown,
    baseDigest?: string,
  ): Promise<Result<SaveReceipt, SaveFailure>> {
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}/api/workflows/${encodeURIComponent(slug)}`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        // The field is **absent**, not `null`, when there is nothing to
        // quote: the backend reads `None` as "unguarded, this caller owns the
        // package", and sending an empty string instead would claim to be
        // editing a version that never existed and conflict with every file.
        body: JSON.stringify(
          baseDigest
            ? { name, document, must_exist: true, base_digest: baseDigest }
            : { name, document, must_exist: true },
        ),
      });
    } catch {
      return Err({ kind: 'error', message: this.unreachable() });
    }
    if (response.status === 409) {
      const conflict = await describeConflict(response);
      if (conflict) return Err(conflict);
      // A 409 with no digest offers no way to keep your own version, so it is
      // reported as the failure it is rather than as a choice the editor
      // cannot honour. Tolerant in reading, strict in trusting.
      return Err({
        kind: 'error',
        message: 'The workflow folder changed and the save was refused.',
      });
    }
    if (!response.ok) return Err({ kind: 'error', message: await describeFailure(response) });

    try {
      const payload = (await response.json()) as { digest?: unknown };
      return Ok({ digest: asString(payload.digest) });
    } catch {
      // The write landed; only the receipt was unreadable. An empty digest is
      // "I cannot tell you", which the caller must treat as no longer knowing
      // the file's version rather than as a version.
      return Ok({ digest: '' });
    }
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

  async setPublished(slug: string, published: boolean): Promise<Result<PublishOutcome, string>> {
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
    try {
      const payload = (await response.json()) as { note?: unknown };
      return Ok({
        note: typeof payload.note === 'string' && payload.note !== '' ? payload.note : null,
      });
    } catch {
      // The flag flipped server-side before this body was written. Failing
      // here would report an error for work that succeeded, and the note is
      // advice — losing it costs a sentence, not the publish.
      return Ok({ note: null });
    }
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
        functions?: unknown[];
        plugin_tools?: unknown[];
        ambient_tools?: unknown[];
        warnings?: unknown[];
      };
      const tools = Array.isArray(payload.tools) ? payload.tools : [];
      // Every list defaults to empty rather than failing the parse: an older
      // backend that predates plugin capabilities must still load a workflow,
      // and a missing key is exactly the "nothing to report" it looks like.
      const functions = Array.isArray(payload.functions) ? payload.functions : [];
      const pluginTools = Array.isArray(payload.plugin_tools) ? payload.plugin_tools : [];
      const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
      // Same default, same reason: a backend that predates this field binds
      // nothing ambient as far as this editor can tell, which is the honest
      // reading of a missing key.
      const ambientTools = (Array.isArray(payload.ambient_tools) ? payload.ambient_tools : []).map(
        (entry) => asString(entry),
      );
      return Ok({
        ambientTools,
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
        functions: functions.map((entry) => asFunction(entry as Record<string, unknown>)),
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

/**
 * A 409 from `PUT /api/workflows/{slug}`, read back into the two facts it
 * carries: the sentence and the digest the file actually has now.
 *
 * `null` for anything that does not carry both — including a 409 whose detail
 * is a plain string, which is what an older backend or a proxy produces.
 */
async function describeConflict(
  response: Response,
): Promise<{ kind: 'conflict'; reason: string; digest: string } | null> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    const detail = payload.detail;
    if (typeof detail !== 'object' || detail === null) return null;
    const reason = asString((detail as Record<string, unknown>)['reason']);
    const digest = asString((detail as Record<string, unknown>)['digest']);
    return reason && digest ? { kind: 'conflict', reason, digest } : null;
  } catch {
    return null;
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
    // Every entry coerced, not the array trusted: a non-string in this list
    // reaches a surface that prints it, and `String(undefined)` on a row is a
    // worse answer than an empty one.
    findings: Array.isArray(record['findings']) ? record['findings'].map(asString) : [],
    digest: asString(record['digest']),
  };
}

/** One `functions` row. Every field is text; nothing here is parsed. */
function asFunction(record: Record<string, unknown>): FunctionCapability {
  return {
    id: asString(record['id']),
    name: asString(record['name']),
    docstring: asString(record['docstring']),
    signature: asString(record['signature']),
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
