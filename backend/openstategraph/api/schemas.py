"""Request/response models — the wire contracts (ticket 72 split)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, AliasChoices, BaseModel, Field, WithJsonSchema, model_validator

from openstategraph.api.workflow_store import SLUG_PATTERN, is_slug


def _must_be_a_slug(value: str) -> str:
    if not is_slug(value):
        raise ValueError(
            f"{value!r} is not a workflow slug (lowercase letters, digits and hyphens)"
        )
    return value


#: A slug as it arrives from a client, refused at validation if it is not one.
#:
#: Install-experience ticket 06. This value reached
#: `state_dir(root) / f"checkpoints-{slug}.sqlite"`, so an unvalidated one let
#: a caller choose where this process created a file — the class `7754d13`
#: closed on `credentials`, surviving on a second field. Validated **here**,
#: at the field, rather than at each of the three run endpoints, for the
#: reason `extra="forbid"` is set here too: a rule stated on the contract is
#: inherited by every transport that validates against it, and cannot be
#: forgotten by the fourth endpoint somebody adds.
#:
#: Rejected, never coerced. `slugify("../etc")` returns a perfectly good slug,
#: and running *something else* than what the caller named is how a workflow
#: quietly binds another package's tools.
#:
#: Enforced by `is_slug` (the store's own rule) and *published* as
#: `SLUG_PATTERN`, so `docs/openapi.json` says out loud what a client may
#: send. The two are pinned to each other by a test rather than left to agree
#: by inspection.
WorkflowSlug = Annotated[
    str,
    AfterValidator(_must_be_a_slug),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": SLUG_PATTERN,
            "description": "A workflow slug: lowercase letters, digits and single hyphens.",
        }
    ),
]


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
    #: Whether the editor **this process serves** predates the source it was
    #: built from — `None` when the question does not apply, which is the
    #: normal case for an installed wheel with no `src/` beside it
    #: (production-ready 60).
    #:
    #: Three-valued on purpose. `False` claims "this editor is current" and an
    #: install cannot claim that; a client must treat `None` as *say nothing*
    #: rather than as a falsy `False`.
    editor_stale: bool | None = None
    #: Whether **any** registered provider has the environment it needs. This
    #: was hardcoded `True` while Ollama was treated as always-available, which
    #: meant it reported ready on a machine with nothing configured
    #: (providers-and-credentials ticket 02). Reads environment variables only;
    #: whether a configured provider is *reachable* is a different question
    #: this endpoint has never answered.
    model_configured: bool = Field(
        description=(
            "At least one provider has its credentials set. "
            "Not a reachability check."
        )
    )


class NodeContractResponse(BaseModel):
    """The prompt layers of one model-driven node type that the developer does
    not type — served from the Python ladder classes, which are the single
    source of truth. An editor shows these read-only beside the developer's
    editable rules; a custom editor should do the same rather than restate them.

    Three fields, and the third is not a third *locked* one (ticket 39):

    - `preamble` — what this node **is**. Locked, and runs first.
    - `contract` — the shape of the answer. Locked, and always last, because
      later instructions win ties.
    - `default_rules` — what the base already tells the model, which the
      developer's own rules **extend** unless they choose replace mode. Not
      locked; showing it under a "locked" label would be untrue.

    An agent's `preamble` and `contract` are both empty by design — it answers
    free-form — so `default_rules` is its *only* non-editable layer. Publishing
    two fields meant the editor's read-only panel rendered nothing at all for
    the most-placed node in the product, while 289 characters of honesty and
    tool-discipline rules were prepended to every one of its prompts.
    """

    preamble: str
    contract: str
    #: Defaulted, so a client written against the two-field version still
    #: parses this payload.
    default_rules: str = ""


class CompiledGraphResponse(BaseModel):
    """`GET /api/workflows/{slug}/graph` — the compiled topology as Mermaid.

    Text, never a PNG: `draw_mermaid_png()` posts the graph to a third-party
    API, and a user's graph is not ours to send anywhere.
    """

    mermaid: str


class ProviderStatusResponse(BaseModel):
    """What **the server** is configured for — names and booleans only.

    Deliberately carries no key material, not even masked. A mask still leaks
    length, prefix and entropy, and it would contradict
    `chat_model.credential_error_from`, which drops OpenAI's own
    `sk-defin****-key` out of its 401 rather than forwarding it. Naming the
    *variable* is the fact a person can act on; a mask of the value is not.

    This exists because "Models and credentials" could only describe the
    **browser's** credential store, and told a QA analyst the product runs
    "offline against mock data" on a server with three working keys.
    """

    name: str = Field(description="The provider id, e.g. `anthropic`.")
    label: str = Field(description="Its display name.")
    configured: bool = Field(description="Whether this server can use it right now.")
    configured_by: str | None = Field(
        default=None,
        description=(
            "Which environment variable actually configured it. Ollama takes "
            "either of two, so naming the first would be wrong for it."
        ),
    )
    env_vars: list[str] = Field(
        default_factory=list,
        description="Every variable that would configure it. Any one is enough.",
    )
    default_model: str = Field(description="The model used when none is named.")
    installed: bool = Field(
        description=(
            "Whether this provider's integration package is importable on this "
            "server — `ProviderEnvironment.is_installed()`, the same check "
            "`openstategraph providers` reports as \"needs its extra\". "
            "Independent of `configured`: a package can be installed with no "
            "credential, or a credential can be set for a package nobody "
            "installed. A missing credential is fixable from the browser's own "
            "credential store; a missing package is not — which is why the "
            "picker treats the two differently (launch-readiness/28)."
        )
    )
    install_hint: str = Field(
        description=(
            "The exact `pip install` line for this provider's integration, "
            "e.g. `pip install 'openstategraph[openai]'` — the same string "
            "`ProviderSpec.install_hint` composes for the CLI, so the picker "
            "never invents its own phrasing."
        )
    )
    extra: str = Field(
        description=(
            "The pip extra's bare name, e.g. `openai` — `ProviderSpec.extra`, "
            "for a picker that wants the short `openstategraph[openai]` form "
            "without parsing `install_hint`."
        )
    )
    key_hint: str | None = Field(
        default=None,
        description=(
            "A glance at what configured this: a secret's first two characters "
            "and a FIXED mask (`sk****`), so the length is not revealed; a "
            "non-secret address such as OLLAMA_HOST in full. `null` when "
            "nothing is set."
        ),
    )


class ProviderStatusListResponse(BaseModel):
    """`GET /api/providers` — every row, plus which environment this server read.

    `providers-and-credentials/13`: the CLI and the running server can read
    two different environments — `openstategraph providers` loads `.env`
    itself; `create_app` never does, deliberately (`dotenv.py`'s own
    docstring). Both answers were honest about the process that produced
    them and neither said which process that was, so a reader with keys in
    `.env` could not tell from either surface whether a server they started
    actually has them. `environment` is that missing sentence, computed the
    same way the CLI's own footer is (`dotenv.environment_source_note`).
    """

    providers: list[ProviderStatusResponse]
    environment: str = Field(
        description=(
            "Which .env is nearest this process, and whether this endpoint "
            "reads it automatically (it does not — see the module docstring)."
        )
    )
    run_readiness: str = Field(
        description=(
            "What a run through the default provider will do right now — "
            "`ProviderCatalogue.elected_default().reason`, the same clause "
            "`openstategraph providers` prints as its header and, on an "
            "install with nothing importable, the exact sentence "
            "`openstategraph serve` prints before it binds a socket. One "
            "function, three surfaces, so a wiring gap cannot describe the "
            "same state two incompatible ways (providers-and-credentials/14)."
        )
    )


class ProviderVerifyResponse(BaseModel):
    """Did a real call to this provider work, just now.

    `configured` answers "is a variable set"; this answers "does it work",
    and they are not the same question. The day this shipped, an Anthropic key
    was set, well-formed, and rejected for want of credit — no inspection of
    the value could have known that.
    """

    name: str
    ok: bool = Field(description="Whether a real call succeeded.")
    detail: str = Field(
        default="",
        description="Why not, in the product's own words. Never a stack trace, never the key.",
    )


class McpAuthPayload(BaseModel):
    """How a server is authenticated — **the variable name, never the value**.

    This model is the reason the panel can be honest. There is no field here
    a credential could travel in, so the question "did the editor just POST a
    token to the server" has one answer and it is no: the browser never has
    one, because the value lives in the server's own environment and is read
    at bind time by name.
    """

    model_config = {"extra": "forbid"}

    kind: str = Field(default="none", description="`none`, `bearer` or `header`.")
    headerName: str = Field(
        default="", description="`header` only — the vendor's own header name."
    )
    tokenEnv: str = Field(
        default="",
        description="The NAME of the environment variable holding the credential.",
    )


class McpServerResponse(BaseModel):
    """One registered server, as the editor may show it."""

    name: str
    url: str
    transport: str
    auth: McpAuthPayload
    origin: str = Field(description="`built-in` for the two defaults, `project` for a config entry.")
    credentialConfigured: bool = Field(
        description=(
            "Whether the named variable is set on this server. Presence, not validity — "
            "only a handshake can tell you the second, which is what /validate is for."
        )
    )


class McpHiddenServersResponse(BaseModel):
    """`GET /api/mcp/servers/hidden` — built-in defaults this project hides.

    Named rather than a bare `list[str]`, and the contract test is right to
    insist: a list of strings publishes no clue what the strings *are*. It also
    leaves room for a hidden default to grow a reason later without every
    client's shape changing under it.
    """

    names: list[str] = Field(
        default_factory=list,
        description=(
            "Names of built-in servers tombstoned with `enabled: false` in the "
            "project's config. Every other MCP route filters these out."
        ),
    )


class McpServerUsageResponse(BaseModel):
    """`GET /api/mcp/servers/{name}/usage` — who would break if it went away."""

    slugs: list[str] = Field(
        default_factory=list,
        description="Saved packages with a `tool.mcp` row naming this server.",
    )


class McpServerWriteRequest(BaseModel):
    """`POST /api/mcp/servers` — register one server in the project's config.

    The same four facts `McpServerResponse` carries back, minus the two the
    server owns: `origin` is decided by which file the entry lives in, and
    `credentialConfigured` is read from this process's environment. An editor
    that could post either would be an editor that could claim a built-in was
    a project entry.

    `auth` is the same `McpAuthPayload` the validate route takes, so the
    "there is no field a credential fits in" property is one schema and not
    two that could diverge.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(
        description="What a `tool.mcp` card names. Replaces an entry of the same name."
    )
    url: str
    transport: str = Field(default="streamable_http", description="`streamable_http` or `sse`.")
    auth: McpAuthPayload = McpAuthPayload()


class McpValidateRequest(BaseModel):
    """`POST /api/mcp/validate` — check one server, configured or inline.

    Either name a registered server, or post a URL. Naming one that is not
    registered is an error rather than a silent fall-through to the URL: the
    two mean different things and answering the wrong one is how a developer
    ends up validating a server they are not about to bind.
    """

    model_config = {"extra": "forbid"}

    server: str = Field(default="", description="A registered server by name.")
    url: str = Field(default="", description="Inline: the server's URL.")
    transport: str = Field(default="streamable_http", description="`streamable_http` or `sse`.")
    auth: McpAuthPayload = McpAuthPayload()


class McpValidateResponse(BaseModel):
    """The handshake's verdict, and the tool names it found.

    `tools` is what a developer actually wants from a validate button: the
    count and the names are the proof the thing has a tool surface, which is
    what a `tool.mcp` node will bind. `initialize` alone would prove only
    that something answered.
    """

    status: str = Field(
        description=(
            "`live`, `unreachable`, `auth_required`, `not_mcp` or `not_installed` — never a "
            "stack trace. The last is the one verdict about this runtime rather than the "
            "server: the `[mcp]` extra is absent, so no socket was opened."
        )
    )
    message: str
    serverName: str = ""
    serverVersion: str = ""
    tools: list[str] = Field(default_factory=list)
    elapsedSeconds: float = 0.0


class ValidateRequest(BaseModel):
    """`POST /api/workflows/validate` — check the posted document.

    The posted document, like `RunRequest`: what the developer can see on the
    canvas is what gets checked, so a verdict cannot be about a saved version
    they are not looking at.
    """

    model_config = {"extra": "forbid"}

    workflow: dict[str, Any] = Field(description="A workflow.json document.")


class ValidateResponse(BaseModel):
    """Can this compile, and if not, what is wrong with it.

    `findings` is a list of single lines rather than one blob because every
    caller renders them — a caller that has to split a string is a caller that
    will split it differently.

    A `valid: false` verdict is **not** a refusal to run. The run endpoints
    report an unknown node type and continue, per `errors.py`'s "degrade loud,
    never silent" rule; the MCP door refuses. See `openstategraph.validation`.
    """

    valid: bool = Field(description="Whether the document compiles.")
    findings: list[str] = Field(
        default_factory=list,
        description="One line per problem. Empty when valid.",
    )


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
    #: Superstep budget, **not** an iteration count. `None` is not "no
    #: budget" — it means *this caller did not name one*, which is what lets
    #: the document's own `settings.recursionLimit` be consulted before the
    #: default of 50 (`step_budget.resolve_step_budget`, workflow-gallery 26).
    #: A non-null default here would have made the two indistinguishable,
    #: which is why the saved setting could never be honoured.
    recursion_limit: int | None = Field(default=None, ge=10, le=1000)
    #: Set by the client on a fresh send; echoed back so a paused run's
    #: eventual resume call can target the same checkpointed thread.
    thread_id: str | None = None
    #: The browser session this run belongs to. Scopes thread listing only —
    #: it never enters a Store namespace, per the memory research (ticket 65).
    #:
    #: **There is deliberately no `user_email` here** (ticket 01). Who a run is
    #: for is decided by the *server* from the request's authenticated context
    #: (`openstategraph/principal.py`), because this value keys a per-person
    #: memory namespace: a client that could name the person could read and
    #: write that person's memories. The same rule `prebuilt_session.py`
    #: already applied to the model — "the transport says who this is" — now
    #: also applies to the transport's own callers.
    session_id: str | None = None
    #: What the posted workflow **asked its caller for** — the other half of
    #: the sentence the field above is one side of. `configurable` is who the
    #: run is *for*, server-determined and unforgeable; `context` is declared
    #: by the document's own `settings.context` and filled by whoever starts
    #: the run, so a client may write it and a document with no declaration
    #: accepts none of it.
    #:
    #: Purely additive: `extra: "forbid"` above is unchanged, and `None` means
    #: *this caller named nothing*, which is what every run before this sent.
    #: Scalars only, and the same three the declaration's type enum names — a
    #: nested value cannot be typed on a CLI flag or rendered into a prompt
    #: honestly, so it is not accepted on any of the three doors
    #: (`organisms-first-class` 70).
    context: dict[str, str | int | float | bool] | None = None
    #: The open workflow's slug, when the client knows it. Tools discovered
    #: in that workflow's own `tools/` folder are layered over the defaults,
    #: so a document can bind the tools that live beside it. Optional —
    #: omitting it runs with the default registry, never a crash.
    #:
    #: **Not additive any more when it is wrong** (ticket 06): a value that is
    #: not a slug is a 422 here, and a slug naming no package on disk is a 404
    #: at the endpoint. Both used to be accepted — the first as an unhandled
    #: `InvalidSlugError` 500, the second as a 200 that silently created
    #: `checkpoints-<whatever-you-sent>.sqlite`.
    workflow_slug: WorkflowSlug | None = None
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
    #:
    #: **And only on a single-user deployment.** A value here goes into
    #: process-global `os.environ`, so on a server with a shared token, a proxy
    #: in front of it, or a caller who is not on the machine, it is dropped
    #: with a log line rather than applied — otherwise the first browser to
    #: send one would configure the server for everybody else's runs
    #: (`auth.shared_deployment_reason`, `the-boundary-nobody-checked/03`).
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

    #: Accepts `threadId` as well, because that is the spelling the **pause
    #: frame publishes** (`every-workflow-green` 24).
    #:
    #: The streaming frames are camelCase throughout — `activeNode`,
    #: `pathSlugs`, `taskId` — and request bodies are snake, so this is a
    #: convention boundary rather than one bad field. The boundary stays; what
    #: changed is that the request *reads* the published spelling too. An
    #: adopter copying `threadId` out of the frame the product just handed them
    #: was met with a 422, on the exact call `/api/runs` tells them to make.
    #:
    #: Tolerant in reading, strict in trusting: both spellings together are
    #: refused unless they agree, because two names for one value that can
    #: differ is worse than one name that is sometimes wrong.
    thread_id: str = Field(min_length=1, validation_alias=AliasChoices("thread_id", "threadId"))

    @model_validator(mode="before")
    @classmethod
    def _one_thread_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            snake, camel = data.get("thread_id"), data.get("threadId")
            if snake is not None and camel is not None:
                if snake != camel:
                    raise ValueError(
                        "thread_id and threadId are two spellings of one value and "
                        f"disagree here: {snake!r} vs {camel!r}"
                    )
                # They agree. Drop the alias so `extra: forbid` — which is what
                # made this a 422 rather than a silent ignore, and stays — does
                # not then reject the very field this accepts.
                data = {k: v for k, v in data.items() if k != "threadId"}
        return data
    #: No `user_email`, for the reason `RunRequest` records: identity is the
    #: server's to determine, never the caller's to assert.
    session_id: str | None = None
    workflow: dict[str, Any]
    decision: Literal["approve", "reject"]
    feedback: str | None = None
    model: str | None = None
    #: Same as `RunRequest.recursion_limit`, `None` and all — a resume that
    #: fell back to a hardcoded 50 would give the second half of a run a
    #: different budget from the first.
    recursion_limit: int | None = Field(default=None, ge=10, le=1000)
    #: Same as `RunRequest.workflow_slug` — and it must exist on BOTH models:
    #: this class forbids extras, so a client that echoes the slug on resume
    #: (as ours does) would otherwise be rejected 422 and every approval
    #: would die at validation. A resumed run must also bind the *same*
    #: tool set as the run it resumes — and, since ticket 06, satisfy the same
    #: grammar: a resume reaches the same per-workflow saver the run did.
    workflow_slug: WorkflowSlug | None = None
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
    #: What each Guardrail node removed, as `{node, entity, strategy, count}`.
    #: Counts and entity types, **never values** — the whole reason this rides
    #: the developer channel rather than the answer (guardrails ticket 03).
    redactions: list[dict[str, Any]] = []
    #: What this run executed, as `{node, tool, statement, result, truncated}`
    #: (`one-chinook-honest/30`). The statements themselves, so a run can be
    #: asked what it did instead of a reader reconstructing it from the model's
    #: prose about what it did.
    #:
    #: Free-form rows for `suggestion`'s reason inverted: the shape is ours and
    #: stable, but *what counts as a statement* is owned by the recognisers in
    #: `executed_statements`, and a second one must be able to join without a
    #: schema change every client has to follow.
    statements: list[dict[str, Any]] = []


class RunResponse(BaseModel):
    answer: str
    #: The thread this run happened in. Send it back as `thread_id` on the
    #: next question and that question is the next *turn* — the same contract
    #: every terminal SSE frame carries. Top level, not in `developer`: a
    #: customer surface needs continuity as much as an editor does, and the
    #: streaming side already discloses it to both.
    thread_id: str = ""
    #: node id -> the **one** branch label the graph dispatched on.
    #:
    #: This line used to end *"so the editor can highlight the path that ran"*,
    #: and no editor has ever read it for that: the canvas lights cards from
    #: per-node run status as the stream reports them (`CanvasStage`), and a
    #: persistent path tint was tried there and removed. `decisions` is the
    #: **record** — the row a reader sees beside the answer and the row an
    #: exported trace carries — which is exactly why one label was not enough
    #: (`launch-readiness/175`).
    decisions: dict[str, str] = {}
    #: router node id -> **every** branch label that router matched.
    #:
    #: A parallel router (`matchMode: "all"`) opens more than one desk in the
    #: same superstep and `decisions` can hold only the label the conditional
    #: edge dispatched on, so a router that matched one branch and a router
    #: that matched three published the identical row. Both desks' answers
    #: were already in `outputs`; nothing said the second branch had run.
    #:
    #: Present for every router that ran, one match or four — an absent row
    #: means no router, never one branch. No audience gate, for `decisions`'
    #: own reason: it is a fact about the run, not guidance for a developer.
    routes: dict[str, list[str]] = {}
    #: node id -> that node's output, for per-node inspection in the sidebar.
    outputs: dict[str, str] = {}
    attempts: int = 0
    mermaid: str = ""
    #: True when a grader ran out of attempts and the answer above is a
    #: candidate it had rejected, published because the loop had to end
    #: somewhere. Visible on **both** audiences on purpose — `launch-readiness`
    #: 25: `attempts` was already enough to prove the loop exhausted itself,
    #: but nothing said whether the last attempt had passed or been forced
    #: through, so a rejected answer reached a customer indistinguishable from
    #: one that passed first try. The grader's *reason* can quote internals
    #: and stays on `developer.warnings`; that the event happened must not.
    published_rejected: bool = False
    #: Present only for `audience: "developer"`. Absent — not empty — for a
    #: customer, so nothing can read "there were no warnings" out of a
    #: response that was never entitled to carry any. `warnings` used to sit
    #: at the top level and reach every caller; see `docs/api.md`.
    developer: DeveloperChannelResponse | None = None


class SaveWorkflowRequest(BaseModel):
    """The whole document plus the display name — never the slug: the slug
    is the URL path parameter, frozen at creation (see `workflow_store.py`).

    This is the **creation** shape. `POST /api/workflows` mints the identity,
    so a body naming one is ticket 20's data loss arriving by a different
    door and is refused by `extra="forbid"`. The save shape is
    :class:`SaveWorkflowAtSlugRequest`, which differs by exactly one
    optional field.
    """

    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1)
    document: dict[str, Any]


class SaveWorkflowAtSlugRequest(SaveWorkflowRequest):
    """What `PUT /api/workflows/{slug}` accepts — workflow-gallery ticket 42.

    Identical to :class:`SaveWorkflowRequest` but for tolerating the `slug`
    that `WorkflowDocumentResponse` hands back, so *fetch, edit, put it
    back* is writable without reshaping the payload. The field is
    **echo-only**: the path is the identity, and a `slug` disagreeing with
    it is refused by the route rather than honoured (a body carrying another
    workflow's slug is a confused client, not an instruction to cross-write).

    `extra="forbid"` is inherited and deliberately not relaxed further —
    it is what makes a typo an error instead of a silent no-op. One field
    was admitted, not the door.

    `must_exist` is the second, and it is a data-loss guard rather than a
    convenience (launch-readiness 147). This endpoint creates a package when
    the slug is free — right for the CLI, a script or a test, and catastrophic
    for an editor tab whose package another tab deleted a moment ago: one
    keystroke re-made the directory with `workflow.json` alone, and the
    `tools/`, `functions/` and `tests/` that made the workflow work were gone
    for good. A client that believes it is *editing* an existing package says
    so, and gets a 404 instead of a resurrection. Default `False`, because the
    create is not the defect — writing to a slug you were told is gone is.
    """

    slug: str | None = None
    must_exist: bool = Field(
        default=False,
        validation_alias=AliasChoices("must_exist", "mustExist"),
        description=(
            "Refuse to create: answer 404 if no package exists at this slug. "
            "For a client that holds a package and is editing it, so a save "
            "cannot re-create one that was deleted underneath it."
        ),
    )


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


class ExampleResponse(BaseModel):
    """One entry of `GET /api/examples` — workflow-gallery ticket 07.

    The editor's Examples shelf and `openstategraph examples list` read the
    **same** catalogue (`openstategraph.examples`); this endpoint is the seam,
    not a second list.

    **No `document`, and that is the difference from `TemplateResponse`.** A
    template is a document, so shipping it inline lets the canvas import a
    starting point in one call. An example is a *package* — tests, knowledge
    store, eval fixture, and in one case a SQLite database — so a client that
    imported the document alone would produce a workflow whose tools resolve to
    nothing, which is precisely the failure `POST /api/workflows/{slug}/
    duplicate` exists to avoid. Taking an example is therefore a copy the
    server performs; `requires` says up front what that will cost.
    """

    slug: str
    name: str
    summary: str
    #: The catalogue's label for the shape it demonstrates ("revision loop").
    pattern: str
    #: This slug first, then every package it mounts, transitively — exactly
    #: the directories a copy will write.
    requires: list[str]


class CopyExampleResponse(BaseModel):
    """What `POST /api/examples/{slug}/copy` wrote.

    `copied` is every slug that landed in the workflows root, the requested one
    first. It is a list rather than a single slug because three examples mount
    others and a copy that left a dependency behind would be broken on arrival.
    """

    slug: str
    copied: list[str]


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


class DuplicateWorkflowRequest(BaseModel):
    """POST /api/workflows/{slug}/duplicate — ticket 01.

    Carries only the new display name, and not the new slug, for the same
    reason `SaveWorkflowRequest` does not: slugs are minted by the backend and
    frozen (`workflow_store.create`). A client that named its own would be
    back to the collision ticket 20 removed, where a second workflow of the
    same name silently overwrote the first.

    The name is optional because the obvious default — "<original> (copy)" —
    depends on the original's name, which only the backend has to hand at that
    moment.
    """

    model_config = {"extra": "forbid"}

    name: str | None = Field(default=None, min_length=1)


class DuplicateWorkflowResponse(BaseModel):
    """The copy's minted slug and name, and the slug it came from.

    The slug is the part the caller cannot predict and the part it needs next
    — to open the copy, or to put it in the address bar.
    """

    slug: str
    name: str
    #: The package this was copied from, unchanged by the operation.
    source: str


class PublishWorkflowResponse(BaseModel):
    slug: str
    published: bool
    #: Build-time-only invariant: publishing never auto-runs the knowledge
    #: model builder — this note reminds the caller it can be rebuilt.
    note: str


class WorkflowDocumentResponse(BaseModel):
    """What the catalogue hands back for one package — and what
    `PUT /api/workflows/{slug}` takes back unchanged (ticket 42).

    `name` is here because the save shape requires it. It used to live only
    inside `document["name"]`, so a scripted edit had to know to lift it out;
    that asymmetry made a published contract whose read and write shapes
    could not be composed.
    """

    slug: str
    #: The display name — the envelope's copy of `document["name"]`, which is
    #: what the store actually keeps and what a rename writes. Required, not
    #: defaulted: a client composing a `PUT` body out of this needs it to be
    #: there on every read, and an optional field is one a reader has to
    #: check for.
    name: str
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


class MountUsageResponse(BaseModel):
    """Who else runs this field before a "push to package" writes it.

    `production-ready` ticket 17. `count` is every mount of this package
    across the workspace, so the confirmation can say how many instances
    change. `shadowed_hosts` names the packages whose own mount already
    overrides this exact `(child_node_id, key)` — those instances will keep
    their own value, and the caller must say so or the push looks like it
    silently failed.
    """

    count: int
    shadowed_hosts: list[str]


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
    #: Tool names **every agent on this server** binds without being wired to
    #: anything — today the prebuilt memory tools, and only when a store is
    #: configured (`every-workflow-green` 05a).
    #:
    #: Published rather than written on the card because it is conditional on
    #: the *environment*, not the document: the same `workflow.json` has
    #: different agents on two installations, so a hardcoded note would be
    #: false on one of them. Empty is a real answer, not a missing one.
    ambient_tools: list[str] = []
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


class ThreadToolCall(BaseModel):
    """One tool this step reached for, and what came back.

    The owner's bar for replay is *"each execution point traced"*, and a tool
    call is the execution point a reader most often came for — a run that
    answered wrongly usually asked for the wrong thing, or was refused.

    All of it was stored and none of it was published: an `AIMessage` carries
    `tool_calls` with their arguments and the `ToolMessage` answering each
    carries the result, and the thread reader flattened both to `role: content`
    (`memory-and-replay` 37).

    **Paired, and reported at the step that asked.** LangGraph writes the
    request in one superstep and the answer in the next, so reporting them
    where each physically landed gives two half-rows that a reader has to
    rejoin by hand.
    """

    name: str
    #: The arguments as JSON text, capped like every other value here. `""`
    #: when the request itself is no longer in the stored history.
    arguments: str = ""
    #: What the tool returned, capped. `""` means no answer was stored — the
    #: run may have ended, or been stopped, before one arrived.
    result: str = ""


class ThreadTokens(BaseModel):
    """What one superstep's model call cost, as the provider reported it.

    Read off `AIMessage.usage_metadata`, which LangChain populates for every
    provider that reports usage — so this needed **no new storage**. Ticket 37
    priced token counts as the half of replay that would require a frame
    table; against the stored file that pricing was wrong, and the ticket
    carries the correction (`memory-and-replay` 37, part 2).

    **This step's call, not the run's total.** The message channel is
    cumulative — every checkpoint holds the whole history — so a reader that
    sums the channel charges the last row for the entire run and produces
    numbers that climb plausibly and are wrong on every row but the last.

    A provider that reports nothing gets no object at all rather than a zeroed
    one: `0` is a claim that a call was free, and silence is not that claim.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


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
    #: Which graph this step belongs to, outermost first; `[]` is the workflow
    #: itself. Each entry is a **graph-node name** — an agent's loop and a
    #: mounted workflow are both checkpointed under a namespace naming the node
    #: that owns them, so this is what tells one graph's supersteps from
    #: another's (`memory-and-replay` 37).
    #:
    #: Same shape and the same reading order as a live frame's `path`: a
    #: consumer walks it outermost-first. `[]` rather than `[""]` — a level
    #: that does not exist is not a blank level.
    #:
    #: **Every entry is a name.** The dispatched-instance id is dropped, and so
    #: is LangGraph's subgraph counter — the `|1`, `|2` it appends when one
    #: task invokes a subgraph more than once. Both discriminate instances
    #: rather than naming graphs, and a counter left in reads on screen as a
    #: nested graph called `1` (`memory-and-replay` 40). Two invocations of one
    #: node arrive here as one namespace, twice, which is what they are.
    namespace: list[str] = Field(default_factory=list)
    #: The innermost entry of `namespace`, or `""` for the workflow itself.
    #: A dispatched worker's instance id is deliberately **not** part of it:
    #: `morning-brief` sends two subtasks to one `worker_web`, and those are
    #: one node that ran twice, not two nodes.
    node: str = ""
    #: The channels this superstep wrote. The other half of what a row is for
    #: — `values` says what the state *was*, this says what *happened*. Same
    #: exclusions as `values`, for the same reason.
    wrote: list[str] = Field(default_factory=list)
    #: Tools **this** superstep asked for, with arguments and results. Not what
    #: the message channel contains: the channel is cumulative and holds the
    #: whole history at every checkpoint, so reporting its contents would print
    #: every call on every row.
    tool_calls: list[ThreadToolCall] = Field(default_factory=list)
    #: How long this superstep took, in milliseconds — the gap between this
    #: checkpoint's `ts` and the previous checkpoint's **in the same
    #: namespace**. A checkpoint is written after its superstep runs, so that
    #: difference is the superstep's own elapsed time; per namespace because a
    #: worker's supersteps are not the workflow's.
    #:
    #: `None`, never `0`, when there is nothing to measure against — the first
    #: step of a graph, an unreadable timestamp, or a clock that went
    #: backwards. Zero is the claim *this took no time*, and a panel has to be
    #: able to tell that from *nobody knows*.
    #:
    #: Note what it includes: a parent superstep that dispatched a worker spans
    #: the worker's whole run, because it did.
    #:
    #: A `source: "input"` step is never timed — it records what was handed in
    #: rather than running anything, so its gap from the previous turn is how
    #: long the *person* took to type.
    duration_ms: int | None = None
    #: What this superstep's model call cost, or `None` if it made none.
    tokens: ThreadTokens | None = None


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
    #: A node wrote the failure sentinel (`[<node> failed after retries: …]`)
    #: into `outputs` — the same signal `node_failure_warnings` reports on a
    #: live run, read back here from the checkpoint.
    #:
    #: Deliberately **not** folded into `status`: `status` answers "is this
    #: waiting on me" (paused vs. finished), a question a failed run answers
    #: no differently than a clean one — a failed run is not paused, and a
    #: third `status` value would force every existing reader of `status ==
    #: "finished"` (the resume gate, the history list) to learn a case that
    #: has nothing to do with what they are asking. `failed` is also
    #: deliberately **not** `not answer`: `silent_node_warnings`'s own
    #: docstring is the reason — "a workflow may legitimately answer with
    #: nothing at all" — so emptiness alone must never read as failure
    #: (production-ready/78).
    failed: bool = False
    #: What a paused thread is waiting to be told — `{"message", "candidate"}`,
    #: the sentence the gate asks and the text a person is being asked to
    #: stand behind — or `None` for a thread that is not paused.
    #:
    #: Read off the pending `__interrupt__` write the checkpoint tuple already
    #: carries (`_is_paused` looks at the same write), not from a compiled
    #: graph: `api/threads.py` deliberately compiles nothing to answer "is this
    #: waiting on me", and reading it back should not cost more than asking
    #: that question does (`workflow-gallery` 76). Before this field, `threads
    #: show` printed every checkpoint value except the one a reviewer came
    #: for, so the pause payload was reachable only from the terminal that
    #: started the run.
    pause: dict[str, str] | None = None


class ThreadListResponse(BaseModel):
    """`GET /api/threads` — past runs, newest first."""

    threads: list[ThreadSummary]


class ThreadTruncation(BaseModel):
    """The part of a run a history did **not** read.

    `GET /api/threads/{id}` has always kept the newest `limit` checkpoints and
    has never said so, which made a whole run and the last fifth of a long one
    the same response (`the-cost-of-one-more/06`). It is not a harmless
    silence: the older end of a thread carries the `AIMessage` requests that
    the newer end's `ToolMessage` answers belong to, so a truncated read
    produces tool calls with no arguments, and `run_findings.py` drops those on
    purpose — a long conversation quietly yielded no findings at all.

    Present only when something was left behind. A truncation of nothing is not
    a truncation, so this field is `null` on a complete read rather than a row
    of zeroes claiming one happened.
    """

    #: How many checkpoints this response holds.
    kept: int
    #: Which end of the run is missing. `"oldest"` — the newest are kept,
    #: because that is the end the store yields first and the end a person
    #: looking at a run came for.
    end: str = "oldest"
    #: The bound that decided it, so a caller knows what to raise.
    limit: int
    #: The same fact as a sentence, for a surface that shows one.
    message: str


class ThreadHistoryResponse(BaseModel):
    """`GET /api/threads/{thread_id}` — one past run, checkpoint by checkpoint."""

    thread: ThreadSummary
    #: Oldest first, so reading top to bottom is watching the run happen.
    steps: list[ThreadStep]
    #: What the read left behind, or `null` when it left nothing behind. Not
    #: audience-filtered: *some of this run is missing* is a fact about the
    #: answer, not machinery that produced it, and a customer reading a
    #: partial history needs it exactly as much as a developer does.
    truncation: ThreadTruncation | None = None
