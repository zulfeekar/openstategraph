"""Running a workflow: blocking, streamed, and resumed after an approval.

The three endpoints both shipped UIs are built on. They were the largest
closures in `create_app` and captured the most — `services`, `runtime_for`,
`memory_store` and `_principal_id`, of which the middle two were fields
unpacked off the first (reviews-2026-08-14 ticket 15).

`_principal_id` became `deps.PrincipalId`, which is what it always was: a pure
function of the request headers and the deployment's principal resolver. Who a
run executes as is decided here and never sent here — the rule
providers-and-credentials ticket 01 exists for.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from openstategraph.api.audience import (
    DeveloperChannel,
    clean_output,
    redaction_report,
    resolve as resolve_audience,
    capability_gap,
    split_suggestion,
    with_capability_notice,
)
from openstategraph.api.deps import PrincipalId, Services
from openstategraph.api.model_resolution import (
    apply_credentials,
    resolve_model,
    workflow_default_model,
)
from openstategraph.api.registries import runtime_warnings
from openstategraph.api.schemas import (
    DeveloperChannelResponse,
    ResumeRequest,
    RunRequest,
    RunResponse,
)
from openstategraph.api.sse_contract import sse_responses
from openstategraph.api.streaming import (
    RUN_EVENTS,
    _stream_run,
    stop_when_client_leaves,
)
from openstategraph.schema import normalize_document

router = APIRouter()


def _known_slug(services: Any, slug: str | None) -> str | None:
    """The slug this run may use — or a 404 before anything is built from it.

    The second half of install-experience ticket 06. `RunRequest.workflow_slug`
    is a slug by then (the field validates its grammar), but a *well-formed*
    slug naming no package was accepted and used: it scoped tool discovery to
    a directory that did not exist, keyed the memory Store's namespace, and —
    with `settings.checkpointer: "sqlite"` in the caller's own document —
    created `checkpoints-<whatever-you-sent>.sqlite` and left one permanent
    entry, holding one open descriptor, in
    `WorkflowServices._workflow_checkpointers`, whose only eviction is
    `close()`. Fifty requests, fifty files, against a soft `RLIMIT_NOFILE` of
    256 on macOS.

    That is what makes this the *bound* on that cache rather than an eviction
    policy: an entry can only exist for a package that exists on disk, so the
    key domain is the store's own contents. An LRU would have been the other
    option and is the wrong one here — an evicted entry has to be closed to
    release the descriptor, and closing a saver a run is still checkpointing
    against fails that run.

    Existence is asked **here** and not in `checkpointer_for`, because "do I
    know this workflow?" is a question with a status code, and a services
    object that answered it would also be answering it for `load_workflow`
    and for tests that legitimately name a package they never wrote.

    Mirrors `threads.savers_for`, which has always refused to open a saver for
    a slug the store cannot load — except that a *listing* degrades (the
    threads may be in the shared saver) where a *run* refuses, since a run
    under a name the server does not have binds nothing it was drawn with.
    """
    from openstategraph.api.workflow_store import InvalidSlugError

    if not slug:
        return None
    try:
        known = services.store.describe(slug) is not None
    except InvalidSlugError:  # pragma: no cover - the field already refused it
        known = False
    if not known:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No workflow named {slug!r} in this deployment. "
                "Omit `workflow_slug` to run the document with the default tools."
            ),
        )
    return slug


@router.post(
    "/api/runs",
    response_model=RunResponse,
    summary="Run a workflow and wait for the whole answer",
    tags=["Runs"],
)
def run_workflow(
    request: RunRequest,
    http: Request,
    services: Services,
    principal_id: PrincipalId,
) -> RunResponse:
    """Compiles and runs a canvas-authored workflow, blocking until it ends.

    The simple call: one request, one JSON answer, no streaming to parse.
    It cannot show progress and it cannot pause for an approval — a
    `human.approval` node needs `/api/runs/stream`, which is what both
    shipped UIs use.
    """
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    # Ollama cloud is the default (see `resolve_model`), so a model is
    # always resolved here — never `None`. A document with no
    # model-calling node still runs fine; `init_chat_model` builds a
    # client lazily and nothing calls it until an agent/worker node does.
    from openstategraph.abc.router import BaseRouter  # noqa: F401  (import cost only)
    from openstategraph.chat_model import build_chat_model

    document = normalize_document(request.workflow)
    # Before the document is compiled or a model built: a slug this
    # deployment does not have is a 404, not a directory it goes looking for.
    slug = _known_slug(services, request.workflow_slug)
    # Browser-held keys, applied only where the server has none — see
    # `apply_credentials` for why the server's own env always wins.
    apply_credentials(request.credentials)
    # Model precedence: explicit request > the document's own
    # settings.model > environment default. A workflow that names its
    # model runs the same everywhere it is opened.
    model = build_chat_model(
        resolve_model(request.model or workflow_default_model(document))
    )

    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    audience = resolve_audience(request.audience)
    runtime = services.runtime_for(slug, document, model, audience=audience)

    # The same thread this endpoint's request has always declared, and
    # until now dropped on the floor. `RunRequest` carried `thread_id`,
    # `session_id`, `user_email` and `workflow_slug`; the invoke below
    # built no `configurable` at all, so a caller sending the same
    # `thread_id` three times got three unrelated first turns — ticket
    # 11's defect surviving on a second endpoint. A declared field that
    # reaches nothing is worse than an absent one: it looks supported.
    # `os.urandom`, not the streaming side's `id(graph)` prefix: the id is
    # minted *before* the graph exists here, and a CPython object address
    # is reusable after a collection anyway.
    thread_id = request.thread_id or f"run-{os.urandom(8).hex()}"

    try:
        graph = compiler.build(
            document,
            RunState,
            runtime.factory(document),
            # Without a saver the block above would still reach nothing:
            # no persisted `messages`, no antecedent, the same defect with
            # a config attached. The streaming endpoint already compiles
            # this way, from the same per-workflow cache.
            checkpointer=services.checkpointer_for(document.get("settings"), slug),
            store=services.memory_store,
        )
        final = graph.invoke(
            {"question": request.question, "attempts": 0, "decisions": {}, "outputs": {}},
            {
                "recursion_limit": request.recursion_limit,
                "configurable": {
                    "thread_id": thread_id,
                    "session_id": request.session_id or "",
                    "user_email": principal_id,
                    "workflow_slug": slug or "",
                },
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    # A paused run is not a finished one, and this endpoint cannot resume.
    #
    # Before the checkpointer above, an interrupting document returned
    # **200 with an empty answer** — silently, so a caller could not tell
    # "finished with nothing to say" from "stopped halfway waiting for a
    # human". The saver is what makes `__interrupt__` visible, so the
    # honest report became possible in the same change that caused it to
    # be needed. 409: the request is fine, the *state* refuses it.
    if final.get("__interrupt__"):
        raise HTTPException(
            status_code=409,
            detail=(
                "This workflow paused for a human decision, which this endpoint "
                "cannot carry. Run it through POST /api/runs/stream, which reports "
                f"the pause and resumes through POST /api/runs/resume. Thread: {thread_id}"
            ),
        )

    # Same seam as the streaming endpoints, applied in the same order:
    # the fence leaves the answer before anyone asks who is listening, so
    # `/api/runs` cannot become the way around `/api/runs/stream`.
    #
    # `answer` alone was not the whole seam, which ticket 15 found by
    # asking the same question over both doors: the streaming endpoint
    # cleans its `outputs` map as it accumulates it and this one returned
    # the raw values, so a fence a customer talked the model into arrived
    # in `outputs["agent-sql"]` while `answer` was spotless. Every surface
    # renders `outputs` per node, so that is the same leak one field along.
    prose, suggestion = split_suggestion(str(final.get("answer") or ""))
    from openstategraph.compile.workflow_compiler import (
        RUN_FAILED_ANSWER,
        redact_failure_markers,
        run_health,
        suggestion_from_rejection,
    )

    raw_outputs = final.get("outputs") or {}
    # Ticket 51 — the capabilities that never bound, kept apart from the steps
    # that broke while running. See the same split in `streaming.py`: only the
    # first kind produces a run that succeeds and reads confident.
    # Nodes that ran and produced nothing — `every-workflow-green` 01. Beside
    # `failures` rather than inside them: a silent node is a report about how
    # the answer was reached, not a claim the run failed, and only the latter
    # may reach the CLI's exit code.
    # What happened inside a mount. `streaming.py` rebuilds this from the frame
    # stream; this door has no frames, so `_subgraph` records it into state
    # instead (`every-workflow-green` 16). Without it, a node that went silent
    # or failed inside a mounted workflow was reported when you streamed the
    # run and not when you POSTed it.
    # One assembly for both doors — `run_health`. These two endpoints each built
    # their own and drifted twice, so the rule is that neither adds a source
    # locally (`every-workflow-green` 14, 16). This door reads everything
    # straight off the finished state; the streaming one folds the same three
    # out of frames.
    health = run_health(raw_outputs, final.get("nested_outputs"), final.get("forced"))
    # A fallback, never an override (`every-workflow-green` 33): the model's own
    # fence wins when it wrote one, and this fills the silence when it did not —
    # built from a name the runtime itself refused, so it does not depend on the
    # model choosing to mention the gap it had just announced by calling it.
    if suggestion is None:
        suggestion = suggestion_from_rejection(final.get("unmet_tools"))
    degraded = list(plan.warnings) + runtime_warnings(runtime)
    channel = DeveloperChannel(
        warnings=degraded
        # A node that failed after retries writes its failure into
        # `outputs` so downstream nodes still read *something*. Every
        # surface renders that map as the node's output, so without this
        # promotion a credential failure returned 200, a blank answer and
        # an empty developer channel (ticket 04).
        + health.failures
        + health.silent,
        suggestion=suggestion,
        # Only when nothing could be placed: a gap with a tool that fits is a
        # suggestion, not something to build (`every-workflow-green` 34).
        capability_gap=(capability_gap(str(final.get("answer") or "")) if suggestion is None else None),
        redactions=redaction_report(final.get("redactions")),
    )
    developer = channel.payload(audience).get("developer")

    # A step failed and no answer was produced. Someone asked a question
    # and a blank string with a 200 is indistinguishable from a broken
    # client — see `RUN_FAILED_ANSWER` for why the never-blank floor in
    # `node_runtime` cannot reach this case.
    # `health.failures`, not a second call: this floor used to reassemble the
    # question locally and so could not see a failure inside a mount — an empty
    # answer caused by a mounted node dying read as a blank success. One
    # assembly, one verdict.
    if not prose.strip() and health.failures:
        prose = RUN_FAILED_ANSWER

    # …and the same aside the streaming door appends (ticket 51). This door
    # exists precisely so a client can skip SSE, so a customer who takes it
    # must not get the confident answer the other one declines to give.
    prose = with_capability_notice(prose, degraded, audience)

    # Developer guidance stays off a customer surface, in `outputs` as
    # much as in `answer` — the same seam ticket 15 found one field along.
    visible = raw_outputs if developer else redact_failure_markers(raw_outputs)

    return RunResponse(
        answer=prose,
        # The thread this run happened in — minted here when the caller
        # named none, so the next question can continue the conversation.
        # Exactly what ticket 11 added to every terminal SSE frame, for
        # exactly the same reason: the client that most needs continuity
        # is the one that did not name a thread.
        thread_id=thread_id,
        decisions={k: str(v) for k, v in (final.get("decisions") or {}).items()},
        outputs={k: str(clean_output(str(v))) for k, v in visible.items()},
        attempts=int(final.get("attempts") or 0),
        mermaid=graph.get_graph().draw_mermaid(),
        developer=DeveloperChannelResponse(**developer) if developer else None,
    )

@router.post(
    "/api/runs/stream",
    summary="Run a workflow and watch it happen (SSE)",
    response_class=StreamingResponse,
    responses=sse_responses(RUN_EVENTS, "The run, frame by frame."),
    tags=["Runs"],
)
def run_workflow_stream(
    request: RunRequest,
    http: Request,
    services: Services,
    principal_id: PrincipalId,
) -> StreamingResponse:
    """The same run as `/api/runs`, surfaced as it happens.

    The event vocabulary and the terminal-frame guarantee are prose, in
    `docs/api.md` — OpenAPI cannot express either, and they are the part a
    custom client gets wrong.

    Ticket 27's sidebar needs to show **which node is currently in
    charge**, live — not just the final answer — and dynamically
    dispatched worker instances need to appear as they are created. A
    single blocking `/api/runs` response cannot do either: everything
    arrives at once, after the fact.

    `stream_mode=["updates", "messages"]` with `subgraphs=True` is what
    the docs (and ticket 27's own notes) call mandatory for streaming a
    graph containing an *actual* nested subgraph — without it, an inner
    graph's tokens never surface. Verified directly against the installed
    LangGraph before writing this, against **both** shapes: a nested
    subgraph does get its own `namespace_tuple`, but a `Send`-dispatched
    worker does not — every concurrently dispatched instance of the same
    static worker node reports `namespace: ()`, because `Send` fans out
    *tasks* against one node, not separate subgraphs. So `namespace`
    alone cannot tell two dispatched worker instances apart; the task id
    pulled from `worker_results` below is what actually does that.
    `subgraphs=True` is kept anyway, both for correctness if a future
    node type nests a real subgraph and because it costs nothing when
    there is none.

    No second LLM run to compute the final answer: the same reducers
    `RunState` declares (`keep_latest_nonempty`, `merge_decisions`) are
    applied here, by hand, to fold the incremental `updates` payloads into
    the same shape `/api/runs` returns — replicating the *documented*
    reducer, not reimplementing new logic, so the two endpoints cannot
    silently disagree about what "the final answer" means.
    """
    from openstategraph.compile.node_runtime import (
        RunState,
    )
    from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name

    # Ollama cloud is the default (see `resolve_model`) — a model is
    # always resolved, never `None`.
    from openstategraph.abc.router import BaseRouter  # noqa: F401  (import cost only)
    from openstategraph.chat_model import build_chat_model

    document = normalize_document(request.workflow)
    # Same gate as `/api/runs`, and before the same work — see `_known_slug`.
    slug = _known_slug(services, request.workflow_slug)
    # Browser-held keys, fallback-only (see `apply_credentials`).
    apply_credentials(request.credentials)
    model = build_chat_model(
        resolve_model(request.model or workflow_default_model(document))
    )

    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    audience = resolve_audience(request.audience)
    runtime = services.runtime_for(slug, document, model, audience=audience)

    try:
        graph = compiler.build(
            document,
            RunState,
            runtime.factory(document),
            checkpointer=services.checkpointer_for(document.get("settings"), slug),
            store=services.memory_store,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    # LangGraph node names are `safe_name(node_id)` (colons are illegal),
    # so events are translated back to the canvas's own ids — otherwise
    # the sidebar could not tell the frontend which node to highlight.
    node_ids_by_name = {safe_name(n): n for n in plan.nodes}
    thread_id = request.thread_id or f"run-{id(graph)}-{os.urandom(4).hex()}"
    config = {
        "recursion_limit": request.recursion_limit,
        "configurable": {
            "thread_id": thread_id,
            "session_id": request.session_id or "",
            "user_email": principal_id,
            "workflow_slug": slug or "",
        },
    }
    graph_input = {
        "question": request.question,
        "attempts": 0,
        "decisions": {},
        "outputs": {},
    }

    return StreamingResponse(
        # Wrapped, never passed raw: `stop_when_client_leaves` is the
        # only thing that makes a client's Stop end the run rather than
        # merely stop watching it.
        stop_when_client_leaves(
            _stream_run(
                graph,
                graph_input,
                config,
                plan,
                node_ids_by_name,
                runtime,
                thread_id,
                audience,
            ),
            http.receive,
        ),
        media_type="text/event-stream",
    )

@router.post(
    "/api/runs/resume",
    summary="Answer an approval and continue the run (SSE)",
    response_class=StreamingResponse,
    responses=sse_responses(RUN_EVENTS, "The resumed run, frame by frame."),
    tags=["Runs"],
)
def resume_workflow_stream(
    request: ResumeRequest,
    http: Request,
    services: Services,
    principal_id: PrincipalId,
) -> StreamingResponse:
    """Continues a run a `human.approval` node paused (see `NodeRuntime._human_approval`).

    Same event vocabulary as `/api/runs/stream`, documented once in
    `docs/api.md`.

    Same event vocabulary as `/api/runs/stream` (`_stream_run`) — a
    resumed run is not a different kind of thing from the frontend's
    point of view, it is the same stream picking back up, so it reuses
    the identical parsing code on the client rather than needing a
    second one.

    Requires the *same* `thread_id` the original run's `interrupt` event
    carried — this is what tells the shared checkpointer
    (`WorkflowServices.checkpointer`) which paused run to continue. Since
    ticket 05 that saver is durable by default, so the thread survives the
    restart the dev stack performs on every file save; `thread_id` is
    therefore a *persistent* identity, and a client that reuses a fixed
    one across conversations will resume the old one rather than start a
    new one.
    """
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler, safe_name
    from langgraph.types import Command

    from openstategraph.abc.router import BaseRouter  # noqa: F401  (import cost only)
    from openstategraph.chat_model import build_chat_model

    document = normalize_document(request.workflow)
    # A resume binds the same package the run it continues did, so it is
    # gated the same way — see `_known_slug`.
    slug = _known_slug(services, request.workflow_slug)
    # Browser-held keys, fallback-only (see `apply_credentials`).
    apply_credentials(request.credentials)
    model = build_chat_model(
        resolve_model(request.model or workflow_default_model(document))
    )

    compiler = WorkflowCompiler()
    plan = compiler.plan(document)
    audience = resolve_audience(request.audience)
    runtime = services.runtime_for(slug, document, model, audience=audience)

    try:
        graph = compiler.build(
            document,
            RunState,
            runtime.factory(document),
            checkpointer=services.checkpointer_for(document.get("settings"), slug),
            store=services.memory_store,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    node_ids_by_name = {safe_name(n): n for n in plan.nodes}
    config = {
        "recursion_limit": request.recursion_limit,
        "configurable": {
            "thread_id": request.thread_id,
            "session_id": request.session_id or "",
            "user_email": principal_id,
            "workflow_slug": slug or "",
        },
    }
    resume_value: dict[str, Any] = {"decision": request.decision}
    if request.feedback:
        resume_value["feedback"] = request.feedback

    return StreamingResponse(
        stop_when_client_leaves(
            _stream_run(
                graph,
                Command(resume=resume_value),
                config,
                plan,
                node_ids_by_name,
                runtime,
                request.thread_id,
                audience,
            ),
            http.receive,
        ),
        media_type="text/event-stream",
    )
