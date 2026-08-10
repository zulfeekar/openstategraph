"""Request/response models — the wire contracts (ticket 72 split)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


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
    #: Editor-only (never `/chat`): give every agent one extra context block
    #: telling it to name a missing capability and emit a ```suggestion fence
    #: the editor can turn into a real node. Off by default, so the customer
    #: chat surface — which simply never sets it — can never be told to
    #: propose edits to a workflow its user cannot edit.
    advisor: bool = False
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
    #: Same as `RunRequest.advisor`, and it must exist on BOTH models for the
    #: same reason `workflow_slug` does: this model forbids extras, so the
    #: editor — which sets the flag on every send — would 422 on every
    #: approval resume if only `RunRequest` carried it. A resumed run must
    #: also compose the *same* agent context as the run it resumes.
    advisor: bool = False
    #: Same as `RunRequest.credentials`, and for the same "must exist on
    #: BOTH models" reason as `workflow_slug` above: this model forbids
    #: extras, so a client that sends credentials on the run must be able to
    #: send them on the resume too, or every approval would 422.
    credentials: dict[str, str] | None = None


class RunResponse(BaseModel):
    answer: str
    #: node id -> branch taken, so the editor can highlight the path that ran.
    decisions: dict[str, str] = {}
    #: node id -> that node's output, for per-node inspection in the sidebar.
    outputs: dict[str, str] = {}
    attempts: int = 0
    mermaid: str = ""
    warnings: list[str] = []


class SaveWorkflowRequest(BaseModel):
    """The whole document plus the display name — never the slug: the slug
    is the URL path parameter, frozen at creation (see `workflow_store.py`).
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
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


class KnowledgeTopicSaveRequest(BaseModel):
    model_config = {"extra": "forbid"}

    body: str
