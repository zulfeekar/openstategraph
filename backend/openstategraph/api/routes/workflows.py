"""The workflow catalogue: list, read, save, publish, delete, and what is inside.

Nineteen of `api/main.py`'s thirty-two routes were these, which is why "one
module that grew" was never the right description of that file — it was
several modules that had not been separated
(reviews-2026-08-14 ticket 15).

Three helper closures came with them. `announce` and the two loaders below
were pure functions of the workflow store, captured from `create_app`'s
locals; they take `services` now, which is the object those locals were
unpacked from in the first place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException

from openstategraph.api.audience import Audience, resolve as resolve_audience
from openstategraph.api.catalogue_events import CatalogueEvent, ChangeReason
from openstategraph.api.customer_graph import customer_mermaid
from openstategraph.api.deps import Services
from openstategraph.api.model_resolution import workflow_default_model
from openstategraph.api.schemas import (
    CapabilitiesResponse,
    CompiledGraphResponse,
    DuplicateWorkflowRequest,
    DuplicateWorkflowResponse,
    FunctionCapabilityResponse,
    KnowledgeBuildRequest,
    KnowledgeBuildResponse,
    KnowledgeTopicDocResponse,
    KnowledgeTopicSaveRequest,
    KnowledgeTopicStatusResponse,
    MountDocumentResponse,
    PluginExportResponse,
    PluginToolCapabilityResponse,
    PublishWorkflowRequest,
    PublishWorkflowResponse,
    SaveWorkflowAtSlugRequest,
    SaveWorkflowRequest,
    SqlSchemaResponse,
    SqlSourceResponse,
    SqlTableResponse,
    ToolCapabilityResponse,
    ToolFieldResponse,
    ValidateRequest,
    ValidateResponse,
    WorkflowDocumentResponse,
    WorkflowSummaryResponse,
)
from openstategraph.api.services import WorkflowServices
from openstategraph.api.workflow_store import WorkflowSummary, validate_package
from openstategraph.sql_reach import reachable_schema


router = APIRouter()


def announce(services: WorkflowServices, reason: ChangeReason, slug: str) -> None:
    """Say that the catalogue changed. Called **after** a change succeeded.

    One call per real mutation (save, publish/unpublish, delete) and never
    on a read — an event that fires when nothing moved trains every client
    to ignore it. `surface_visible` is recomputed from the store rather
    than inferred from the request, because "is this on `/chat` now?" is
    the conjunction of `published` and `hidden` and only the store knows
    both; a deleted slug simply is not in the list, so it reports False
    without a special case. The extra directory scan is paid at
    human-click frequency.
    """
    visible = any(s.slug == slug for s in services.store.list(published_only=True))
    services.events.publish(
        CatalogueEvent(reason=reason, slug=slug, surface_visible=visible)
    )


@router.get(
    "/api/workflows",
    response_model=list[WorkflowSummaryResponse],
    summary="List workflows — the first call any client makes",
    tags=["Catalogue"],
)
def list_workflows(services: Services, surface: Literal["editor", "chat"] = "editor") -> list[WorkflowSummaryResponse]:
    """Ticket 04 (launch-readiness): the listing is surface-aware.

    - ``surface=editor`` (default): everything the developer owns —
      drafts AND hidden packages included, each row carrying its
      ``published`` and ``hidden`` flags so the editor can mark a hidden
      package rather than pretend it does not exist.
    - ``surface=chat``: the customer surface — published AND not hidden
      only (hidden trumps published, enforced in the store).

    **This answers visibility, never existence** (ticket 21). A slug's
    absence here means "no surface advertises it" — it may be hidden, or
    unreadable, and either way the file is still on disk and still served
    200 by `GET /api/workflows/{slug}`. Ask
    `GET /api/workflows/{slug}/summary` when the question is whether a
    package exists.
    """
    # The editor is the *developer's* surface, so it sees everything it
    # owns — hidden packages included, each row carrying `hidden` so the
    # UI can mark them rather than pretend they are not there. `hidden`
    # remains absolute for `surface="chat"`, which is the customer's.
    return [
        _summary_response(services, s)
        for s in services.store.list(
            published_only=surface == "chat",
            include_hidden=surface == "editor",
        )
    ]

def _summary_response(services: WorkflowServices, s: WorkflowSummary) -> WorkflowSummaryResponse:
    return WorkflowSummaryResponse(
        slug=s.slug, name=s.name, saved_at=s.saved_at,
        node_count=s.node_count, edge_count=s.edge_count,
        findings=validate_package(services.store.directory_for(s.slug)),
        published=s.published, hidden=s.hidden,
    )

@router.get(
    "/api/workflows/{slug}/summary",
    response_model=WorkflowSummaryResponse,
    summary="Does this workflow exist, and when was it last saved?",
    tags=["Catalogue"],
)
def get_workflow_summary(services: Services, slug: str) -> WorkflowSummaryResponse:
    """One package's row — **the existence question** (ticket 21).

    `GET /api/workflows` is a *surface*: it omits unreadable packages on
    either surface and hidden ones on `surface=chat`, so a client that scans
    it for its own slug and concludes "deleted" on a miss is reading a
    visibility answer as an existence answer. That is exactly what the
    editor's file watch did, and why opening `concierge` (`hidden: true`,
    served 200) raised "This workflow was deleted on disk" while the file sat
    right there.

    This reports every package the store can name, hidden included, with
    `hidden` saying which. **404 is the only "it is gone"** — and it is
    real, so a stale open copy still gets its warning.
    """
    from openstategraph.api.workflow_store import InvalidSlugError

    try:
        summary = services.store.describe(slug)
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if summary is None:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}")
    return _summary_response(services, summary)

@router.post(
    "/api/workflows/{slug}/duplicate",
    response_model=DuplicateWorkflowResponse,
    summary="Copy a workflow package to a new slug",
    tags=["Catalogue"],
)
def duplicate_workflow(services: Services, slug: str, request: DuplicateWorkflowRequest) -> DuplicateWorkflowResponse:
    """Copy the whole package — `tools/`, `tests/`, `knowledge/`, all of it.

    **On the backend because the client cannot do it.** A browser can only
    load the document and create a new workflow from it, which copies
    `workflow.json` and leaves the nodes bound to tools that do not exist
    in the copy — a failure that surfaces at run time, long after the copy
    looked successful.

    The copy is a **draft** whatever the original was, and gets a minted
    slug it did not choose; see `WorkflowStore.duplicate` for why each.
    """
    from datetime import datetime, timezone

    from openstategraph.api.workflow_store import (
        InvalidSlugError,
        SlugMintingError,
        WorkflowNotFoundError,
    )

    try:
        existing = services.store.describe(slug)
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}")

    # Defaulted here rather than in the client: the obvious name depends on
    # the original's, and a browser would have to fetch it first to say the
    # same thing.
    name = request.name or f"{existing.name} (copy)"
    try:
        created = services.store.duplicate(slug, name=name, saved_at=datetime.now(timezone.utc).isoformat())
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SlugMintingError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc

    # A new package exists, so the catalogue moved — same reason a create
    # announces. Announced for the *copy*: the original did not change.
    announce(services, "saved", created)
    return DuplicateWorkflowResponse(slug=created, name=name, source=slug)

@router.post(
    "/api/workflows/{slug}/publish",
    response_model=PublishWorkflowResponse,
    summary="Publish or unpublish a workflow",
    tags=["Catalogue"],
)
def publish_workflow(services: Services, slug: str, request: PublishWorkflowRequest) -> PublishWorkflowResponse:
    """Flip the draft→publish flag. One endpoint for both directions —
    the body's ``published`` bool IS the whole lifecycle state.

    Deliberately does NOT auto-run the knowledge model builder (knowledge
    builds are build-time-only, never a side effect); the note reminds
    the caller routing knowledge can be rebuilt.
    """
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

    try:
        services.store.set_published(slug, request.published)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # After the store wrote, so a failed flip announces nothing.
    announce(services, "published" if request.published else "unpublished", slug)
    return PublishWorkflowResponse(
        slug=slug,
        published=request.published,
        note=(
            "Concierge routing knowledge was not rebuilt automatically; "
            "rebuild it via POST /api/workflows/{root}/knowledge/build "
            "when routing should learn about this change."
        ),
    )

@router.get(
    "/api/workflows/{slug}",
    response_model=WorkflowDocumentResponse,
    summary="Fetch one workflow.json document",
    tags=["Catalogue"],
)
def get_workflow(services: Services, slug: str) -> WorkflowDocumentResponse:
    """The vendor-neutral document itself — the thing a run takes as input.

    A client fetches this and posts it back to `/api/runs/stream`: the
    compile seam is one-directional and stateless per call, so the
    workflow that executes is the one the caller can read.

    **This body is accepted by `PUT /api/workflows/{slug}` unchanged**
    (ticket 42), which is why `name` is on the envelope rather than only
    inside the document: fetch, edit, put it back, with no reshaping.
    """
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

    try:
        document = services.store.load(slug)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # The name the *store* holds, not a second reading of the document:
    # `describe` owns the precedence (envelope name, else document name,
    # else the slug) and a copy of it here would be the same knowledge
    # written twice.
    summary = services.store.describe(slug)
    name = summary.name if summary is not None else str(document.get("name") or slug)
    return WorkflowDocumentResponse(slug=slug, name=name, document=document)

@router.get(
    "/api/workflows/{root}/mounts/{path:path}",
    response_model=MountDocumentResponse,
    summary="Fetch the document one mounted instance actually runs",
    tags=["Catalogue"],
)
def get_mount_document(services: Services, root: str, path: str, inherited: bool = False) -> MountDocumentResponse:
    """The effective document for one **instance** of a mounted workflow.

    A package is a class and a mount node is an instance of it, carrying
    its own `data.overrides`. `GET /api/workflows/concierge` returns the
    shared definition; this returns what the mount at `wf-music` runs,
    with that mount's overrides merged in — and `.../mounts/wf-music/wf-inner`
    walks on to a grandchild, applying each level in turn.

    Served rather than merged client-side on purpose: the merge has one
    owner (`apply_mount_overrides`), and a second implementation of it
    would be duplicated knowledge buying only a round trip.

    `?inherited=true` answers the neighbouring question: what this instance
    would run if it overrode nothing. That is what an inspector shows
    beside an overridden field, and what a revert restores — and it cannot
    be computed by the caller, because the override has already replaced
    the inherited value in the document above.

    The package on disk is never written — the merge exists only in the
    copy returned here, so the compile seam stays one-directional.
    """
    from openstategraph.api.mount_resolution import (
        MountResolutionError,
        resolve_mount_document,
    )
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

    segments = path.split("/")
    if any(not segment for segment in segments):
        # **Refuse rather than repair**, because `MountAddress` does.
        # This used to filter empties out, so `parent//wf-music` resolved
        # happily over HTTP while `parseMountAddress` returned null for the
        # same string — one address grammar with two parsers and two
        # answers. The moment a mount id contains a character the two treat
        # differently, a link resolves to different instances by transport.
        #
        # 422 and not 404: this endpoint reserves 404 for an address that
        # is well-formed and names something absent ("this link is stale").
        # An empty segment is not stale, it is not an address.
        raise HTTPException(
            status_code=422,
            detail=f"{root}/{path} is not a mount address — a segment is empty",
        )
    try:
        resolved = resolve_mount_document(
            services.store, root, segments, inherited=inherited
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No workflow named {exc}") from exc
    except MountResolutionError as exc:
        # 404, not 422: the address is well-formed and simply names an
        # instance that is not there — the same answer a deleted workflow
        # gets, because a client renders both as "this link is stale".
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return MountDocumentResponse(
        root=root,
        slug=resolved.slug,
        mount_path=resolved.mount_path,
        document=resolved.document,
        warnings=resolved.warnings,
    )

@router.post(
    "/api/workflows",
    response_model=WorkflowDocumentResponse,
    status_code=201,
    summary="Create a workflow — the backend mints its slug",
    tags=["Catalogue"],
)
def create_workflow(services: Services, request: SaveWorkflowRequest) -> WorkflowDocumentResponse:
    """Bring a new workflow into existence and be **told which slug it got**.

    Ticket 20. A name is not unique, so a client that slugifies one and
    PUTs to the result is guessing: two workflows named "My Workflow" both
    guessed `my-workflow`, and the second overwrote the first with a 200.
    Only the process holding the workflows directory can mint an identity,
    so it does — the first of a name keeps the clean slug, a colliding one
    gets a short random disambiguator (`my-workflow-k7m3qp`), and the
    response's `slug` is the answer, never something to recompute.

    Use `PUT /api/workflows/{slug}` afterwards to save changes: that
    endpoint addresses a slug you already hold, and this one is how you
    come to hold it.
    """
    from datetime import datetime, timezone

    from openstategraph.api.workflow_store import SlugMintingError

    try:
        slug = services.store.create(
            name=request.name,
            document=request.document,
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
    except SlugMintingError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    announce(services, "saved", slug)
    return WorkflowDocumentResponse(slug=slug, name=request.name, document=request.document)

@router.put(
    "/api/workflows/{slug}",
    response_model=WorkflowDocumentResponse,
    summary="Overwrite the workflow document at a slug you already hold",
    tags=["Catalogue"],
)
def save_workflow(
    services: Services, slug: str, request: SaveWorkflowAtSlugRequest
) -> WorkflowDocumentResponse:
    """Writes the package's `workflow.json` and stamps `saved_at`.

    The slug is the path parameter and is frozen at creation; the body
    carries the display name and the document, never the slug. Announces
    the change on `/api/events` **after** the write succeeded.

    **Addresses an existing package.** It still creates one if the slug is
    free — naming a directory explicitly is how the CLI and a test write a
    package they intend to own — but a client that does not yet have a
    slug must `POST /api/workflows` and be given one, because a slug it
    invented from a name may already belong to somebody else's workflow
    (ticket 20).
    """
    from datetime import datetime, timezone

    from openstategraph.api.workflow_store import InvalidSlugError

    if request.slug is not None and request.slug != slug:
        # Tolerant in reading, strict in trusting: the echoed slug is
        # admitted so a fetched body can be put straight back, and a slug
        # naming a *different* package is refused rather than ignored. The
        # path is the identity; honouring the body would cross-write one
        # workflow's document onto another's, silently.
        raise HTTPException(
            status_code=422,
            detail=(
                f"body names workflow {request.slug!r} but the path addresses "
                f"{slug!r} — the path is the identity; omit `slug` or make it match"
            ),
        )
    try:
        services.store.save(
            slug,
            name=request.name,
            document=request.document,
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    announce(services, "saved", slug)
    return WorkflowDocumentResponse(slug=slug, name=request.name, document=request.document)

@router.delete(
    "/api/workflows/{slug}",
    status_code=204,
    summary="Delete a workflow package",
    tags=["Catalogue"],
)
def delete_workflow(services: Services, slug: str) -> None:
    """Removes the package directory and announces it on `/api/events`.

    Returns 204 with no body — there is nothing left to describe. A
    deleted slug simply stops appearing in the listing.
    """
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

    try:
        services.store.delete(slug)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    announce(services, "deleted", slug)

@router.get(
    "/api/workflows/{slug}/capabilities",
    response_model=CapabilitiesResponse,
    summary="Tools and functions this workflow may put on a canvas",
    tags=["Authoring"],
)
def get_capabilities(services: Services, slug: str) -> CapabilitiesResponse:
    """What this editor may put on a canvas, from all three sources.

    Ticket 18 covered the first: a workflow's own `tools/`/`functions/`
    folders, discovered by importing them rather than by registration.
    Register PK-06 adds the second — tools **installed distributions**
    contribute, which the runtime has been able to bind since ticket 05 and
    the editor had no way to show — and the honesty that goes with both:
    `warnings` carries every capability that failed to load, every plugin
    that replaced a built-in, and every Python tool that has no editor card
    at all (the half-authored case, which used to be pure silence).

    Requires the workflow to already be saved (so its directory exists);
    an unsaved, canvas-only workflow has no folder to scan yet.
    """
    from openstategraph.api.ambient_tools import ambient_tool_names
    from openstategraph.api.capability_discovery import discover_functions, discover_tools
    from openstategraph.api.plugin_capabilities import (
        bindable_tool_types,
        editor_renderable_types,
        plugin_tool_capabilities,
        unrenderable_tool_warning,
    )
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError
    from openstategraph.workflows_root import checkout_root

    try:
        workflow_dir = services.store.directory_for(slug)
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not workflow_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from WorkflowNotFoundError(slug)

    warnings: list[str] = []
    tools = discover_tools(workflow_dir, slug=slug, warnings=warnings)
    functions = discover_functions(workflow_dir, slug=slug)
    plugin_tools, plugin_warnings = plugin_tool_capabilities()
    warnings.extend(plugin_warnings)

    # A type is renderable if the editor ships a card for it (the generated
    # catalogue) or if this very payload describes it — a plugin's declared
    # fields and a workflow-local discovery both produce a card with no
    # TypeScript at all. Anything left is authored on one side only.
    declared = {t.node_type for t in tools if t.node_type} | {p.node_type for p in plugin_tools}
    half_authored = unrenderable_tool_warning(
        bindable=bindable_tool_types(),
        renderable=editor_renderable_types(),
        declared=declared,
        # `checkout_root()` answers None on an installed wheel, which is
        # precisely the reader who cannot act on "edit src/nodes/tools/".
        in_checkout=checkout_root() is not None,
    )
    if half_authored:
        warnings.append(half_authored)

    return CapabilitiesResponse(
        # What every agent gets without being wired to it — the answer a
        # developer could not get from the canvas at all until now, and could
        # only see when a model hallucinated a tool name and the runtime
        # listed the real ones (`every-workflow-green` 05a).
        # `memory_settings` is left to its default: `WorkflowServices` carries
        # the store (the switch) and not the settings (the shape) — those live
        # on the runtime's own services, which this credential-free endpoint
        # does not build. Recorded rather than hidden: a server running
        # non-default memory scopes would publish the default set here, which
        # is a narrower claim than the runtime's and never a wider one.
        ambient_tools=ambient_tool_names(memory_store=services.memory_store),
        tools=[
            ToolCapabilityResponse(id=t.id, name=t.name, description=t.description, args_schema=t.args_schema, node_type=t.node_type)
            for t in tools
        ],
        functions=[
            FunctionCapabilityResponse(id=f.id, name=f.name, docstring=f.docstring, signature=f.signature)
            for f in functions
        ],
        plugin_tools=[
            PluginToolCapabilityResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                args_schema=p.args_schema,
                node_type=p.node_type,
                distribution=p.distribution,
                fields=[ToolFieldResponse(**f) for f in p.fields],
                replaces_builtin=p.replaces_builtin,
            )
            for p in plugin_tools
        ],
        warnings=warnings,
    )

@router.get(
    "/api/workflows/{slug}/plugin-export",
    response_model=PluginExportResponse,
    summary="Preview this package as an Agent Plugins v1 plugin",
    tags=["Authoring"],
)
def export_workflow_as_plugin(services: Services, slug: str) -> PluginExportResponse:
    """Preview this workflow package as an Agent Plugins v1 plugin.

    A GET writes nothing: it returns the manifest, the layout a caller
    would materialize, and the honest list of what does not survive the
    crossing. The verdict and the full mapping are in
    `docs/decisions/agent-plugins.md` — adopt-as-interop, never as our
    format, with all of their vocabulary confined to `plugin_interop.py`.
    """
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError
    from openstategraph.plugin_interop import InvalidPluginError, export_plugin

    try:
        workflow_dir = services.store.directory_for(slug)
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not workflow_dir.is_dir():
        raise HTTPException(
            status_code=404, detail=f"No workflow named {slug!r}"
        ) from WorkflowNotFoundError(slug)
    try:
        export = export_plugin(workflow_dir)
    except InvalidPluginError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PluginExportResponse(
        manifest=export.manifest, paths=sorted(export.files), notes=export.notes
    )

@router.post(
    "/api/workflows/{slug}/knowledge/build",
    response_model=KnowledgeBuildResponse,
    summary="Generate this workflow's knowledge docs",
    tags=["Knowledge"],
)
def build_knowledge(services: Services, slug: str, request: KnowledgeBuildRequest) -> KnowledgeBuildResponse:
    """'Build second brain' (knowledge layer): one doc per topic, written
    to `workflows/<slug>/knowledge/` by every registered builder whose
    source material exists in this workflow — SQL tables today, codebase
    and OpenAPI sources by registration (`knowledge_builders.BUILDERS`).

    Synchronous on purpose: topics are few (tables of a workflow's own
    databases), and the report is the button's feedback. Regeneration is
    safe — a doc without the generated marker is hand-authored and is
    skipped, never overwritten (see `knowledge_builders`' policy).
    """
    from openstategraph.api import knowledge_build
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

    try:
        document = services.store.load(slug)
        workflow_dir = services.store.directory_for(slug)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Model precedence mirrors the run endpoints: explicit request >
    # document settings.model > environment default.
    model = knowledge_build.resolve_build_model(
        request.model or workflow_default_model(document), request.credentials
    )
    try:
        report = knowledge_build.run_build(
            workflow_dir,
            document,
            model,
            services.store.root,
            source=request.source,
            instruction=request.instruction,
        )
    except knowledge_build.UnknownSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not any(report[key] for key in ("written", "skipped", "collisions", "warnings")):
        raise HTTPException(
            status_code=422,
            detail=(
                "No knowledge source found in this workflow — no SQL tool "
                "node names a database, it mounts no child workflows, and "
                "it wires no platform tool that can see the project."
            ),
        )
    return KnowledgeBuildResponse(**report)

def _knowledge_context(services: WorkflowServices, slug: str) -> tuple[Path, dict[str, Any]]:
    """Shared loader for the curation endpoints: the package dir and the
    document (the document is what staleness recomputes briefs from)."""
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

    try:
        document = services.store.load(slug)
        workflow_dir = services.store.directory_for(slug)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No workflow named {slug!r}") from exc
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workflow_dir, document

@router.get(
    "/api/workflows/{slug}/knowledge",
    response_model=list[KnowledgeTopicStatusResponse],
    summary="List this workflow's knowledge topics",
    tags=["Knowledge"],
)
def list_knowledge(services: Services, slug: str) -> list[KnowledgeTopicStatusResponse]:
    """The curation list: every topic with its hint, ownership state
    (generated vs claimed) and stale badge — the Knowledge card's data."""
    from openstategraph.api import knowledge_curation

    workflow_dir, document = _knowledge_context(services, slug)
    return [
        KnowledgeTopicStatusResponse(
            name=s.name, hint=s.hint, generated=s.generated, source=s.source, stale=s.stale
        )
        for s in knowledge_curation.list_topics(workflow_dir, document, services.store.root)
    ]

@router.get(
    "/api/workflows/{slug}/knowledge/{topic}",
    response_model=KnowledgeTopicDocResponse,
    summary="Read one knowledge topic",
    tags=["Knowledge"],
)
def read_knowledge_topic(services: Services, slug: str, topic: str) -> KnowledgeTopicDocResponse:
    """The raw Markdown of one topic, with its ownership and stale flags.

    `generated` says the builder still owns it; the first saved edit
    strips that marker forever (the auto-claim), and `stale` says the
    source it describes has changed since.
    """
    from openstategraph.api import knowledge_curation

    workflow_dir, document = _knowledge_context(services, slug)
    try:
        body = knowledge_curation.read_topic(workflow_dir, topic)
    except knowledge_curation.UnknownTopicPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"No knowledge topic {topic!r}") from exc
    status = next(
        (
            s
            for s in knowledge_curation.list_topics(workflow_dir, document, services.store.root)
            if s.name == topic
        ),
        None,
    )
    return KnowledgeTopicDocResponse(
        name=topic,
        body=body,
        generated=status.generated if status else False,
        source=status.source if status else "",
        stale=status.stale if status else False,
    )

@router.put(
    "/api/workflows/{slug}/knowledge/{topic}",
    response_model=KnowledgeTopicDocResponse,
    summary="Save one knowledge topic, claiming it from the builder",
    tags=["Knowledge"],
)
def save_knowledge_topic(services: Services, 
    slug: str, topic: str, request: KnowledgeTopicSaveRequest
) -> KnowledgeTopicDocResponse:
    """Explicit save with the auto-claim: saving strips the generated
    marker (human touch = human ownership) and records the claim-time
    source hash, so the stale badge outlives the claim. No autosave —
    the file lands in git, diffable."""
    from openstategraph.api import knowledge_curation

    workflow_dir, document = _knowledge_context(services, slug)
    try:
        status = knowledge_curation.save_topic(
            workflow_dir, topic, request.body, document, services.store.root
        )
    except knowledge_curation.UnknownTopicPathError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeTopicDocResponse(
        name=status.name,
        body=knowledge_curation.read_topic(workflow_dir, status.name),
        generated=status.generated,
        source=status.source,
        stale=status.stale,
    )

@router.get(
    "/api/workflows/{slug}/sql-schema",
    response_model=SqlSchemaResponse,
    summary="The tables this workflow's SQL tools can actually reach",
    tags=["Workflows"],
)
def sql_schema(services: Services, slug: str) -> SqlSchemaResponse:
    """The agent's field of view over the wired databases.

    The schema tools take their table as a *model* argument — the agent
    sees every table and picks one — so the editor shows the whole set,
    read from the same file the tool opens, instead of a per-node table
    control that never reached the runtime.

    A read, and a total one: a database that is missing, unreadable or
    whose driver is absent comes back as a warning on its source (or, for
    a path that does not resolve inside `workflows/`, as no source at
    all). Never a 500 — a card must not break because a file moved.
    """
    _, document = _knowledge_context(services, slug)
    return SqlSchemaResponse(
        sources=[
            SqlSourceResponse(
                database=source.database,
                engine=source.engine,
                tables=[
                    SqlTableResponse(name=t.name, detail=t.detail) for t in source.tables
                ],
                warning=source.warning,
            )
            for source in reachable_schema(document, services.store.root)
        ]
    )

@router.post(
    "/api/workflows/validate",
    response_model=ValidateResponse,
    summary="Can this document compile, and if not, why",
    tags=["Authoring"],
)
def validate_workflow(services: Services, request: ValidateRequest) -> ValidateResponse:
    """The compile-check, without running anything.

    Validation existed only as an MCP tool, so the two clients were not
    equal: an LLM client had its document checked before every run and the
    editor could not check one at all. That asymmetry is what let a
    document containing an unregistered node type reach a run and answer
    with the user's own question — the skipped node forwards its input, so
    the run looks like it worked.

    Cheap and credential-free on purpose: `ValidateWorkflowTool` plans the
    graph in memory and throws it away, so this reaches no provider and a
    developer can call it long before they have a key configured.

    **A `valid: false` verdict is not a refusal.** The run endpoints report
    an unknown node type on the developer channel and continue, per
    `errors.py`'s "degrade loud, never silent" rule; the MCP door refuses.
    One validator, two policies — see `openstategraph.validation`.
    """
    from openstategraph.validation import validate_document

    valid, findings = validate_document(request.workflow)
    return ValidateResponse(valid=valid, findings=findings)

@router.get(
    "/api/workflows/{slug}/graph",
    response_model=CompiledGraphResponse,
    summary="The compiled topology, as Mermaid text",
    tags=["Runs"],
)
def compiled_graph(
    services: Services,
    slug: str, audience: Literal["developer", "customer"] = "developer"
) -> CompiledGraphResponse:
    """The COMPILED topology as Mermaid text (ticket 54) — what the
    compiler actually produced, not a hand-drawn approximation.

    `xray=True` is asked for, and expands nothing today — a concierge's
    routed children and a Team's members are closures, not LangGraph
    subgraphs, so each renders as one flat box (see
    `CompiledWorkflow.mermaid`). Text, never a PNG —
    `draw_mermaid_png()` posts the graph to a third-party API.

    `audience=customer` hides the compiler's own vocabulary — `__start__`,
    `__default_error_handler__`, `safe_name`d ids, branch ids — and labels
    each node with the name its author gave it. The default is
    **developer**, deliberately: an existing caller keeps the ids, which
    are what a mount bug gets reported under, and only the customer page
    opts out (reviews-2026-08-14 ticket 04).
    """
    from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError
    from openstategraph.compile.node_runtime import RunState
    from openstategraph.compile.workflow_compiler import WorkflowCompiler

    try:
        document = services.store.load(slug)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail=f"No workflow '{slug}'")
    except InvalidSlugError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    runtime = services.runtime_for(slug, document, None)
    compiler = WorkflowCompiler()
    try:
        graph = compiler.build(
            document, RunState, runtime.factory(document), store=services.memory_store
        )
        mermaid_text = graph.get_graph(xray=True).draw_mermaid()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")
    if resolve_audience(audience) is Audience.CUSTOMER:
        mermaid_text = customer_mermaid(mermaid_text, document)
    return CompiledGraphResponse(mermaid=mermaid_text)
