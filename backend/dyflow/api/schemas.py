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


class CapabilitiesResponse(BaseModel):
    tools: list[ToolCapabilityResponse]
    functions: list[FunctionCapabilityResponse]


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

