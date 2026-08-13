"""Request/response models — the wire contracts (ticket 72 split)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """`GET /api/health` — is this process up, and does it know a model?

    Named rather than left a bare dict (scale-and-adopt ticket 05): a
    published contract whose first endpoint answers `{}` teaches a reader
    that the rest of the document is decoration too.
    """

    # `model_` is Pydantic's own protected prefix; `model_configured` is on the
    # wire already and both clients read it, so the namespace is disabled here
    # rather than the field renamed under them.
    model_config = {"protected_namespaces": ()}

    ok: bool
    #: Always true since Ollama cloud became the default — `resolve_model` can
    #: always name *a* model. Whether that provider is reachable is a different
    #: question this endpoint has never answered.
    model_configured: bool = Field(
        description="A model name can be resolved. Not a reachability check."
    )


class NodeContractResponse(BaseModel):
    """The two LOCKED prompt sections of one model-driven node type.

    Served from the Python ladder classes, which are the single source of
    truth. An editor shows these read-only beside the developer's editable
    rules; a custom editor should do the same rather than restate them.
    """

    preamble: str
    contract: str


class CompiledGraphResponse(BaseModel):
    """`GET /api/workflows/{slug}/graph` — the compiled topology as Mermaid.

    Text, never a PNG: `draw_mermaid_png()` posts the graph to a third-party
    API, and a user's graph is not ours to send anywhere.
    """

    mermaid: str


class AskRequest(BaseModel):
    model_config = {"extra": "forbid"}

    question: str = Field(min_length=1, description="A natural-language question.")
    #: Provider-prefixed, e.g. `anthropic:claude-haiku-4-5` or `ollama:llama3.1:8b`.
    model: str | None = None
    #: Superstep budget, **not** an iteration count. See graph.py.
    recursion_limit: int = Field(default=50, ge=10, le=1000)


class RunRequest(BaseModel):
    """Run **the posted document**, not a server-side graph.

    This is what makes the editor's Run button honest: the workflow the developer
    can see on the canvas is the workflow that executes. The document is
    vendor-neutral `workflow.json`, so the compile seam stays one-directional.
    """

    model_config = {"extra": "forbid"}

    workflow: dict[str, Any] = Field(description="A workflow.json document.")
    question: str = Field(min_length=1)
    model: str | None = None
    recursion_limit: int = Field(default=50, ge=10, le=1000)
    #: Set by the client on a fresh send; echoed back so a paused run's
    #: eventual resume call can target the same checkpointed thread.
    thread_id: str | None = None
    #: Customer-client identity (ticket 64): a browser session and the person.
    #: Neither ever enters a Store namespace by itself — per the memory
    #: research (ticket 65), `user_email` namespaces long-term memory and
    #: `thread_id`/`session_id` scope only the checkpointer/config.
    session_id: str | None = None
    user_email: str | None = None
    #: The open workflow's slug, when the client knows it. Tools discovered
    #: in that workflow's own `tools/` folder are layered over the defaults,
    #: so a document can bind the tools that live beside it. Optional and
    #: additive — omitting it runs with the default registry, never a crash.
    workflow_slug: str | None = None
    #: Who this run is for. `developer` additionally gets the `developer`
    #: channel on the `done` frame (authoring warnings, capability
    #: suggestions) and gives every agent the advisor context block that lets
    #: it name a missing capability. `customer` — the default, and what
    #: `/chat` sends by never setting this — gets the answer and the run.
    #:
    #: One field rather than the `advisor` boolean it replaces: the boolean
    #: was the same fact spelled a second way, and a flag and an audience can
    #: disagree. See `api/audience.py` for the raw payload that proved they
    #: did.
    audience: Literal["customer", "developer"] = "customer"
    #: Per-request provider credentials, e.g. `{"ANTHROPIC_API_KEY": "..."}`.
    #: The editor's "Models and credentials" dialog stores keys in the
    #: browser; without this field they would only ever reach the in-browser
    #: preview, never a backend run — so a developer who pasted a key would
    #: still see "no model configured" from Chat. Applied as a **fallback
    #: only**: an env var already set server-side always wins (see
    #: `apply_credentials`). Never logged, never echoed back.
    credentials: dict[str, str] | None = None


class ResumeRequest(BaseModel):
    """Continues a run a `human.approval` node paused.

    Carries the whole workflow again (not just the thread id) for the same
    reason `RunRequest` does — the compile seam is one-directional and
    stateless per call; nothing server-side remembers *which* document a
    thread belongs to between requests, only the checkpointed graph state
    LangGraph itself owns.
    """

    model_config = {"extra": "forbid"}

    thread_id: str = Field(min_length=1)
    session_id: str | None = None
    user_email: str | None = None
    workflow: dict[str, Any]
    decision: Literal["approve", "reject"]
    feedback: str | None = None
    model: str | None = None
    recursion_limit: int = Field(default=50, ge=10, le=1000)
    #: Same as `RunRequest.workflow_slug` — and it must exist on BOTH models:
    #: this class forbids extras, so a client that echoes the slug on resume
    #: (as ours does) would otherwise be rejected 422 and every approval
    #: would die at validation. A resumed run must also bind the *same*
    #: tool set as the run it resumes.
    workflow_slug: str | None = None
    #: Same as `RunRequest.audience`, and it must exist on BOTH models for the
    #: same reason `workflow_slug` does: this model forbids extras, so the
    #: editor — which declares its audience on every send — would 422 on every
    #: approval resume if only `RunRequest` carried it. A resumed run must also
    #: compose the *same* agent context, and be entitled to the same channel,
    #: as the run it resumes.
    audience: Literal["customer", "developer"] = "customer"
    #: Same as `RunRequest.credentials`, and for the same "must exist on
    #: BOTH models" reason as `workflow_slug` above: this model forbids
    #: extras, so a client that sends credentials on the run must be able to
    #: send them on the resume too, or every approval would 422.
    credentials: dict[str, str] | None = None


class DeveloperChannelResponse(BaseModel):
    """What only a workflow editor may see — see `api/audience.py`.

    One object rather than loose fields, because "developer-only" is the
    property they share and it should be visible in the contract: a reader of
    this schema can tell at a glance which half of a run is guidance about the
    workflow and which half is the answer to the question.
    """

    #: Plan findings plus `runtime_warnings()`: unbound tools, unresolved
    #: functions and subgraphs, mount overrides, discovery failures.
    warnings: list[str] = []
    #: The capability-gap suggestion the run produced, if any. Free-form here
    #: on purpose — the editor validates it against its *live* registry and
    #: canvas (`src/view/ask/suggestion.ts`), which is a question no schema on
    #: this side can answer.
    suggestion: dict[str, Any] | None = None


class RunResponse(BaseModel):
    answer: str
    #: The thread this run happened in. Send it back as `thread_id` on the
    #: next question and that question is the next *turn* — the same contract
    #: every terminal SSE frame carries. Top level, not in `developer`: a
    #: customer surface needs continuity as much as an editor does, and the
    #: streaming side already discloses it to both.
    thread_id: str = ""
    #: node id -> branch taken, so the editor can highlight the path that ran.
    decisions: dict[str, str] = {}
    #: node id -> that node's output, for per-node inspection in the sidebar.
    outputs: dict[str, str] = {}
    attempts: int = 0
    mermaid: str = ""
    #: Present only for `audience: "developer"`. Absent — not empty — for a
    #: customer, so nothing can read "there were no warnings" out of a
    #: response that was never entitled to carry any. `warnings` used to sit
    #: at the top level and reach every caller; see `docs/api.md`.
    developer: DeveloperChannelResponse | None = None


class SaveWorkflowRequest(BaseModel):
    """The whole document plus the display name — never the slug: the slug
    is the URL path parameter, frozen at creation (see `workflow_store.py`).
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    document: dict[str, Any]


class TemplateResponse(BaseModel):
    """One entry of `GET /api/templates` — scale-and-adopt ticket 04.

    The editor's New Workflow picker and `openstategraph new --list-templates`
    read the **same** catalogue (`openstategraph.templates`); this endpoint is
    the seam, not a second list. It carries the rendered `document` so picking
    a template is one call: the canvas imports what it is given rather than
    re-deriving a starting point the CLI would have built differently.
    """

    name: str
    summary: str
    document: dict[str, Any]


class WorkflowSummaryResponse(BaseModel):
    slug: str
    name: str
    saved_at: str
    node_count: int
    edge_count: int
    #: Package-contract findings (ticket 49) — "error: ..." / "warning: ...".
    findings: list[str] = []
    #: Draft→publish lifecycle (launch-readiness ticket 04). Drafts stay off
    #: the customer /chat surface until published.
    published: bool = True
    #: Whether this package is advertised on any surface (ticket 21).
    #: `GET /api/workflows?surface=editor` (the default) returns hidden
    #: packages too, so this flag carries real information there — the editor
    #: uses it to mark a row as hidden. It is always ``False`` on
    #: `surface=chat`, which omits hidden packages outright, and it carries
    #: real information on `GET /api/workflows/{slug}/summary`, the endpoint
    #: that answers existence rather than visibility.
    hidden: bool = False


class PublishWorkflowRequest(BaseModel):
    """POST /api/workflows/{slug}/publish — one endpoint for both directions;
    the flag IS the whole state, so publish/unpublish is one body field."""

    model_config = {"extra": "forbid"}
    published: bool


class PublishWorkflowResponse(BaseModel):
    slug: str
    published: bool
    #: Build-time-only invariant: publishing never auto-runs the knowledge
    #: model builder — this note reminds the caller it can be rebuilt.
    note: str


class WorkflowDocumentResponse(BaseModel):
    slug: str
    document: dict[str, Any]


class MountDocumentResponse(BaseModel):
    """One **instance** of a mounted workflow, as that instance actually runs.

    A package is a class and a mount node is an instance of it: the mount
    carries `data.overrides`, which are merged onto a copy of the package at
    compile time and never written back. Two mounts of one package therefore
    run two different documents, and this is how a client asks for one of them
    rather than for the shared definition.

    `slug` is the **class** — the package the instance is of — because
    capabilities, knowledge, the SQL schema and the palette all belong to the
    package and a client still asks about those by slug. `mount_path` is the
    chain of mount node ids that identifies *which* instance, and the two
    together are what the editor's address bar spells `root/mount-id`.

    `warnings` carries the merge's own loud-but-not-fatal reports — an
    override naming a child node id that does not exist runs the package
    default and says so, rather than refusing to open.
    """

    #: The workflow the root document is; the first segment of the address.
    root: str
    #: The class this instance is of — what to ask about capabilities with.
    slug: str
    #: Mount node ids from the root inward. Never empty: an empty path is the
    #: root document, which has its own endpoint.
    mount_path: list[str]
    #: The package document with this instance's overrides applied.
    document: dict[str, Any]
    warnings: list[str] = []


class ToolCapabilityResponse(BaseModel):
    id: str
    name: str
    description: str
    args_schema: dict[str, Any]
    #: The canvas node type the tool declares (`BaseTool.node_type`); empty
    #: when the tool is listable but not placeable.
    node_type: str = ""


class FunctionCapabilityResponse(BaseModel):
    id: str
    name: str
    docstring: str
    signature: str


class ToolFieldResponse(BaseModel):
    """One control a plugin's tool asks the editor to put on its card.

    Mirrors `openstategraph.abc.ToolField`; `options` is always a
    `{value,label}` list by the time it gets here, so the editor never has to
    guess whether a plugin wrote bare strings or pairs.
    """

    key: str
    label: str
    kind: str
    default_value: Any = ""
    placeholder: str = ""
    hint: str = ""
    options: list[dict[str, str]] = []


class PluginToolCapabilityResponse(BaseModel):
    """A tool an installed distribution contributes — app-scoped, not workflow.

    Reported separately from `tools` because the two have different lifetimes
    and the palette says so: a workflow's own tool disappears when another
    workflow is opened, a plugin's is available everywhere until it is
    uninstalled.
    """

    id: str
    name: str
    description: str
    args_schema: dict[str, Any]
    node_type: str
    distribution: str
    fields: list[ToolFieldResponse] = []
    replaces_builtin: bool = False


class CapabilitiesResponse(BaseModel):
    tools: list[ToolCapabilityResponse]
    functions: list[FunctionCapabilityResponse]
    #: App-scoped: installed distributions (`openstategraph.tools` entry
    #: points), the same objects the runtime binds.
    plugin_tools: list[PluginToolCapabilityResponse] = []
    #: Everything that failed to appear, and everything that appeared under
    #: someone else's name — the capability-warning channel `runtime_warnings()`
    #: already carries for a *run*, applied to discovery. Silence here would
    #: mean a developer who authored half a tool gets no message at all.
    warnings: list[str] = []


class PluginExportResponse(BaseModel):
    """A preview of this workflow as an Agent Plugins v1 package.

    A report, not a write: `paths` is the layout a caller would materialize,
    and `notes` names every lossy edge (see `docs/decisions/agent-plugins.md`).
    The mapping itself lives entirely in `plugin_interop.py` — this schema
    carries their manifest as opaque data and adds no vocabulary of its own.
    """

    manifest: dict[str, Any]
    paths: list[str]
    notes: list[str]


class AskResponse(BaseModel):
    """What the editor renders.

    The SQL and rows are returned alongside the prose deliberately: an answer a
    developer cannot audit is not much use, and seeing the query is how they tell
    a right answer from a plausible one.
    """

    answer: str
    sql: str
    rows: str
    attempts: int
    passed: bool
    reason: str



class KnowledgeBuildRequest(BaseModel):
    """POST /api/workflows/{slug}/knowledge/build — everything optional.

    `model`/`credentials` follow the run endpoints' resolution chain; `source`
    names one registered builder (default: every builder that finds topics).
    """

    model_config = {"extra": "forbid"}

    model: str | None = None
    credentials: dict[str, str] | None = None
    source: str | None = None
    #: Optional developer steering text for the agentic builders (the
    #: instructed explorer / codebase builder) — "focus on billing; fiscal
    #: year starts April". Additive; mechanical builders ignore it.
    instruction: str | None = None


class KnowledgeBuildResponse(BaseModel):
    """The build report: topic names written/skipped, grouped per source."""

    written: list[str]
    skipped: list[str]
    #: Additive (backward compatible): cross-builder topic collisions —
    #: refused writes, invariant 5 — and recognized-but-unavailable sources.
    collisions: list[str] = []
    warnings: list[str] = []
    sources: dict[str, dict[str, list[str]]]


class KnowledgeTopicStatusResponse(BaseModel):
    """One row of GET /api/workflows/{slug}/knowledge — the curation list."""

    name: str
    hint: str
    #: True while the builder's marker is present; the first saved edit
    #: strips it (auto-claim) and this flips to False forever.
    generated: bool
    #: The owning builder's kind (sql/root/explorer/codebase); "" once claimed.
    source: str
    #: The source content-hash behind this doc no longer matches — the doc
    #: (generated OR claimed) describes a source that has since changed.
    stale: bool


class KnowledgeTopicDocResponse(BaseModel):
    """GET/PUT /api/workflows/{slug}/knowledge/{topic} — the raw doc."""

    name: str
    body: str
    generated: bool
    source: str
    stale: bool


class SqlTableResponse(BaseModel):
    """One table a workflow's SQL tools can reach."""

    name: str
    #: Columns, types, primary key and foreign keys both directions, Markdown.
    detail: str


class SqlSourceResponse(BaseModel):
    """One database the document's SQL tool nodes are wired to."""

    #: Workflows-root-relative path (SQLite) or the connection URL.
    database: str
    engine: str
    tables: list[SqlTableResponse] = []
    #: Recognized but not fully readable, or a truncated table list. Reported
    #: rather than served as an empty list that reads as "no tables".
    warning: str = ""


class SqlSchemaResponse(BaseModel):
    """`GET /api/workflows/{slug}/sql-schema` — the agent's field of view.

    The schema tools take their table as a *model* argument: the agent sees
    every table and picks. This is that same set, read from the same file, so
    the editor can show it instead of implying a per-node table choice that
    the runtime never had.
    """

    sources: list[SqlSourceResponse] = []


class KnowledgeTopicSaveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    body: str


class ThreadStep(BaseModel):
    """One checkpoint of a past run — the state as it stood at that moment.

    A *view*, never a re-execution: these values were recorded while the run
    happened and are read straight back out of the checkpointer. Nothing is
    called again, so no tool sends a second email and no model is billed
    twice.
    """

    checkpoint_id: str
    #: LangGraph's own superstep counter. `-1` is the input that started it.
    step: int
    at: str = Field(description="ISO-8601 timestamp the checkpoint was written.")
    #: LangGraph's `metadata.source`: `input`, `loop`, `update` or `fork`.
    source: str
    #: The run's state at this checkpoint, every value rendered as text.
    #: Internal channels (`__*`, `branch:to:*`) are left out — they are the
    #: scheduler's bookkeeping, not the run's story.
    values: dict[str, str]


class ThreadSummary(BaseModel):
    """One past run, identified by the thread the checkpointer stored it under.

    `session_id` and `user_email` are read back from the checkpoint metadata,
    where LangGraph persists every non-private `configurable` key. They are
    therefore exactly what the *transport* supplied on the run — never
    anything the model claimed about itself.
    """

    thread_id: str
    workflow_slug: str
    session_id: str
    user_email: str
    updated_at: str
    #: How many checkpoints this thread holds; a rough sense of how far it got.
    steps: int
    question: str
    answer: str
    #: `paused` means the run stopped at an `interrupt()` and can be continued
    #: with `POST /api/runs/resume` — which *does* execute. `finished` means
    #: there is nothing pending; reading it back is all that is on offer.
    status: Literal["paused", "finished"]


class ThreadListResponse(BaseModel):
    """`GET /api/threads` — past runs, newest first."""

    threads: list[ThreadSummary]


class ThreadHistoryResponse(BaseModel):
    """`GET /api/threads/{thread_id}` — one past run, checkpoint by checkpoint."""

    thread: ThreadSummary
    #: Oldest first, so reading top to bottom is watching the run happen.
    steps: list[ThreadStep]
