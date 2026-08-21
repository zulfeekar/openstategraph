"""The MCP layer — OpenStateGraph's capabilities, exposed to somebody else's LLM.

The deployment this exists for: the platform runs on a server, **only MCP is
exposed**, and a company's own MCP clients (Claude, Cursor, …) connect and use
it to *generate* StateGraphs. The customer's model does the composing; we are
the **ground truth and the artifact factory**, not the author.

That inverts what a "workflow server" usually means, and the inversion is the
design:

- **The core loop is stateless and model-free.** `get_node_vocabulary` tells a
  client what can be composed; `compile_workflow` takes a composed document and
  returns a verdict plus artifacts, writing nothing and calling no model. A
  deployment can serve that loop with **no provider key at all**. The verdict →
  revise → verdict loop is the product: the client's model iterates against
  deterministic compiler evidence rather than its own confidence.
- **The artifact's home is the customer's repository.** `compile_workflow`
  hands back a normalized `workflow.json` envelope, the compiled Mermaid
  topology, a run snippet and the package skeleton. They commit it. Nothing
  here needs to host it.
- **Hosting is optional and drafts-only.** `save_workflow_draft` exists for
  deployments that do host workflows. It always writes a draft; **publishing is
  not exposed over MCP** and neither is deletion. A human clicks publish in the
  editor. That is the trust boundary, and `EXPOSED_TOOLS` is where it is
  enforced — see `docs/decisions/mcp-layer.md`.

Structure follows the repo's own rule against god classes: four small
collaborators (vocabulary, artifacts, library, runs), each with one reason to
change, and `build_mcp_server` registers thin wrappers over them. Every tool is
a wrapper over an existing seam — `ValidateWorkflowTool`, `WorkflowCompiler`,
`WorkflowStore`, `PackageKnowledge`, `plugin_interop` — so there is no second
implementation of anything to drift.

Run it with ``python -m openstategraph.mcp_server`` (stdio). For a real server
deployment set ``OPENSTATEGRAPH_MCP_TRANSPORT=streamable-http``.

**Not part of the public API. Stability is not guaranteed** — Tier 3, see
``docs/stability.md``. The MCP *protocol* surface is the contract here (and
``EXPOSED_TOOLS`` is where it is enforced); the Python names in this module
are not. Requires the ``[mcp]`` extra.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from openstategraph.api.services import WorkflowServices
from openstategraph.errors import DocumentError as _DocumentError
from openstategraph.schema import normalize_document as _normalize_document
from openstategraph.step_budget import resolve_step_budget

logger = logging.getLogger(__name__)

#: The complete, reviewed surface. A tool absent from this tuple does not
#: exist over MCP — publishing, deleting and anything credential-shaped are
#: absent deliberately, and a test asserts it.
EXPOSED_TOOLS: tuple[str, ...] = (
    "get_node_vocabulary",
    "compile_workflow",
    "validate_workflow",
    "list_workflows",
    "describe_workflow",
    "get_knowledge",
    "export_plugin",
    "save_workflow_draft",
    "run_workflow",
)


#: The one spelling, now that there is a public home for it
#: (`openstategraph.errors`). Re-exported rather than redefined so
#: `from openstategraph.mcp_server import DocumentError` keeps working and
#: `except DocumentError` catches the same object either way — two classes with
#: one name is how a caller ends up with a handler that never fires.
DocumentError = _DocumentError


#: The same object as `openstategraph.schema.normalize_document`, not a second
#: spelling of it. This module used to carry its own copy that also accepted a
#: JSON *string* (MCP clients serialize inconsistently); that behaviour moved
#: into the one seam, so the envelope-peeling rule and the version guard cannot
#: drift between the loader and the MCP layer.
normalize_document = _normalize_document


#: The compile-check, shared with the HTTP door.
#:
#: It lived here, under a comment reading "No second validator lives here" —
#: a rule about one transport that became a rule about two the moment the
#: editor needed the same check. See `openstategraph.validation` for why the
#: two doors then *diverge* on what a finding means: MCP refuses to run an
#: invalid document, the run endpoints report and continue.
from openstategraph.validation import validate_document as _validate


class NodeVocabulary:
    """What can be composed, and how the pieces legally connect.

    The mandatory first call. A client's model cannot invent our node types or
    port ids, and guessing them produces documents that fail validation for
    reasons the verdict can only describe after the fact.

    Assembled from the existing sources of truth — the **generated** node
    catalogue (`compile/port_specs.json`, emitted from the authoritative
    TypeScript definitions), the Architect's known-types set, and the Python
    ladder classes' locked prompt sections (the same ones `/api/node-contracts`
    serves). It declares nothing of its own.

    Before RC-01 the port table it served was hand-copied, so a node type added
    in the editor was invisible to every connected client — an LLM composing
    against it could not use the node and got no error saying why. It is now
    generated, and CI fails on drift.
    """

    def describe(self) -> dict[str, Any]:
        from openstategraph.abc.agent import BaseAgentNode
        from openstategraph.abc.grader import BaseGrader
        from openstategraph.abc.orchestrator import BaseOrchestrator
        from openstategraph.abc.router import BaseRouter
        from openstategraph.compile.node_catalogue import CATALOGUE
        from openstategraph.compile.workflow_compiler import (
            BINDING_PORT_TYPES,
            CONTROL_PORT_TYPES,
            DEFAULT_PORT_SPECS,
            WORKER_PORT_TYPE,
        )
        from openstategraph.prebuilt_architect import KNOWN_NODE_TYPES, KNOWN_PREFIXES

        # Spelled as a union rather than left to inference: the only supertype
        # mypy can find for four unrelated ABCs is `ABCMeta`, on which
        # `.PROMPT` below is an untyped guess.
        contracts: dict[
            str,
            type[BaseAgentNode] | type[BaseRouter] | type[BaseGrader] | type[BaseOrchestrator],
        ] = {
            "agent.llm": BaseAgentNode,
            "route.classifier": BaseRouter,
            "route.grader": BaseGrader,
            "orchestrate.supervisor": BaseOrchestrator,
        }
        records = {node["type"]: node for node in CATALOGUE.nodes}

        node_types = []
        for node_type in sorted(set(KNOWN_NODE_TYPES) | set(DEFAULT_PORT_SPECS)):
            ladder = contracts.get(node_type)
            record = records.get(node_type, {})
            node_types.append(
                {
                    "type": node_type,
                    "label": record.get("label", ""),
                    "description": record.get("description", ""),
                    # `annotate.*` node types are real and are allowed in a
                    # document, but the compiler never schedules them. Said out
                    # loud rather than dropped, so a client is not left to infer
                    # from an empty port list that the node is broken.
                    "executes": record.get("kind", "standard") == "standard",
                    # `workflow` means the type travels with one workflow's own
                    # package and is not available everywhere.
                    "scope": record.get("scope", "app"),
                    "ports": [
                        {
                            "id": port_id,
                            "type": spec.type,
                            "direction": spec.direction,
                            "label": spec.label,
                            "required": spec.required,
                            # `null` is unlimited — an agent's tool bus.
                            "max_connections": spec.max_connections,
                            "accepts": list(spec.accepts),
                        }
                        for port_id, spec in sorted(
                            DEFAULT_PORT_SPECS.get(node_type, {}).items()
                        )
                    ],
                    "generated_ports": [
                        {
                            "prefix": group.prefix,
                            "type": group.type,
                            "direction": group.direction,
                        }
                        for group in CATALOGUE.dynamic_ports.get(node_type, ())
                    ],
                    "prompt_contract": (
                        {
                            "preamble": ladder.PROMPT.preamble,
                            "contract": ladder.PROMPT.output_contract,
                            # The third layer, published for the reason ticket 39
                            # gives: `agent.llm` locks no preamble and no contract,
                            # so a two-field payload told a composing client that
                            # the most-placed node in the product prepends nothing
                            # — while it prepends 289 characters of honesty and
                            # tool-discipline rules to every prompt.
                            "default_rules": ladder.PROMPT.default_rules,
                            "editable": (
                                "Only your own rules are editable. The preamble and "
                                "the output contract are supplied by the runtime and "
                                "must NOT be restated in the node's config — the "
                                "contract is appended last and later instructions win. "
                                "An empty preamble/contract does NOT mean the prompt is "
                                "entirely yours: default_rules is prepended by the base "
                                "and your rules extend it unless you replace them."
                            ),
                        }
                        if ladder is not None
                        else None
                    ),
                }
            )

        return {
            "node_types": node_types,
            "dynamic_type_prefixes": {
                prefix: hint
                for prefix, hint in zip(
                    KNOWN_PREFIXES,
                    (
                        "a tool node; the suffix names a tool discovered in the "
                        "workflow package's tools/ folder",
                        "a function node; the suffix names a callable in the "
                        "workflow package's functions/ folder",
                    ),
                )
            },
            "port_semantics": {
                "control": sorted(CONTROL_PORT_TYPES),
                "binding": sorted(BINDING_PORT_TYPES),
                "worker": WORKER_PORT_TYPE,
                "feedback": "feedback",
                # Generated alongside the ports themselves: which source types
                # each port type accepts, so a client can check a connection
                # before composing rather than after the verdict.
                "types": [
                    {
                        "id": port_type["id"],
                        "label": port_type.get("label", ""),
                        "accepts": list(port_type.get("accepts") or ()),
                    }
                    for port_type in CATALOGUE.port_types
                ],
                "explanation": (
                    "NOT every edge is a graph edge. An edge landing on a "
                    "`tool` or `skill` port is a BINDING (the capability becomes "
                    "available to that node) and produces no control flow. An "
                    "edge landing on a `text` or `result` port is control flow. "
                    "An edge landing on a `feedback` port is half of a "
                    "conditional loop. An edge on a `worker` port declares "
                    "fan-out. Wiring a tool as control flow makes the tool run "
                    "once on its own before the agent ever calls it."
                ),
            },
            "router_ports": (
                "A route.classifier's outputs are generated from its config: one "
                "`branch:<slug>` output port per configured branch, plus the "
                "`question` text input."
            ),
            "cycles": (
                "A loop is only drawable into a typed feedback input "
                "(route.grader `revise` -> agent.llm `feedback`, or -> "
                "orchestrate.supervisor `feedback`). Every cycle must contain a "
                "conditional edge; an all-static cycle can never terminate."
            ),
            "document_shape": {
                "version": 2,
                "name": "Human readable name",
                "settings": {"model": "optional; omit to use the server default"},
                "nodes": [
                    {
                        "id": "in1",
                        "type": "input.text",
                        "title": "optional",
                        "data": {},
                        "position": {"x": 0, "y": 0},
                    }
                ],
                "edges": [
                    {
                        "source": {"nodeId": "in1", "portId": "text"},
                        "target": {"nodeId": "out1", "portId": "result"},
                    }
                ],
            },
            "rules": [
                "Exactly one node should have no incoming control edge — that is "
                "the entry point.",
                "Some node must flow toward the end, or the graph has no exit.",
                "Call compile_workflow after every revision. A document you have "
                "not compiled is a guess.",
                "Do not put Infinity or NaN anywhere: this document is JSON.",
            ],
        }


class WorkflowArtifacts:
    """The stateless centerpiece: verdict in, committable artifacts out.

    Writes nothing, reads no workflow package, contacts no model. The graph is
    genuinely compiled (so the Mermaid is what the compiler produced, never a
    hand-drawn approximation) and then discarded.
    """

    #: What a full workflow package contains, for a client laying one out in
    #: its own repository. Mirrors `workflow_store.validate_package`'s contract
    #: and the layout `_agents_md` describes.
    PACKAGE_SKELETON: tuple[str, ...] = (
        "workflow.json",
        "AGENTS.md",
        "tools/",
        "functions/",
        "middlewares/",
        "skills/",
        "knowledge/",
        "tests/",
        "data/",
    )

    def compile(self, document: Any, name: str | None = None) -> dict[str, Any]:
        try:
            resolved = normalize_document(document)
        except DocumentError as exc:
            return self._refusal([str(exc)])

        valid, findings = _validate(resolved)
        if not valid:
            return self._refusal(findings)

        try:
            mermaid, warnings = self._compile_topology(resolved)
        except Exception as exc:  # noqa: BLE001 — the message IS the feedback
            return self._refusal([f"Compile failed: {type(exc).__name__}: {exc}"])

        workflow_name = name or str(resolved.get("name") or "Untitled workflow")
        # One name, not two: an envelope naming the workflow one thing while
        # the document inside names it another is a diff waiting to confuse.
        resolved = {**resolved, "name": workflow_name}
        return {
            "validated": True,
            "findings": [],
            "document": {
                "version": 1,
                "name": workflow_name,
                "savedAt": datetime.now(timezone.utc).isoformat(),
                # A machine never publishes. What a client commits is a draft;
                # a human flips the flag in the editor.
                "published": False,
                "document": resolved,
            },
            "mermaid": mermaid,
            # Distinct from findings: the document IS valid, but a capability
            # it names could not be resolved here. Never silent — a subgraph
            # that produced nothing would otherwise look like a working graph.
            "warnings": warnings,
            "run_snippet": self._run_snippet(),
            "package_skeleton": list(self.PACKAGE_SKELETON),
        }

    def validate(self, document: Any) -> dict[str, Any]:
        """The verdict alone, for a client mid-iteration that does not yet
        want the artifacts."""
        try:
            resolved = normalize_document(document)
        except DocumentError as exc:
            return {"validated": False, "findings": [str(exc)]}
        valid, findings = _validate(resolved)
        return {"validated": valid, "findings": findings}

    @staticmethod
    def _refusal(findings: list[str]) -> dict[str, Any]:
        """Findings instead of artifacts. The client iterates against these."""
        return {
            "validated": False,
            "findings": findings,
            "document": None,
            "mermaid": "",
            "warnings": [],
            "run_snippet": "",
            "package_skeleton": [],
        }

    @staticmethod
    def _compile_topology(document: dict[str, Any]) -> tuple[str, list[str]]:
        """The COMPILED topology, plus every capability the compile could
        not resolve.

        `xray=True` is asked for and expands nothing here, and **that is the
        honest answer on this path rather than a gap left open**. A mount
        compiles to a closure, not a LangGraph subgraph, so LangGraph cannot
        see through it; `CompiledWorkflow.mermaid()` and the editor's own
        preview splice the composition from what the compiler recorded while
        it built each child. This path is **stateless** — it holds no workflow
        library — so a `workflow.subgraph` resolves to nothing, there *is* no
        child graph to splice, and one flat box is the true picture of what
        would compile here. The `warnings` below say so in words; the diagram
        says so in shape (`workflow-gallery` 56).

        `model=None` on purpose: the compiler owns topology and knows nothing
        about models, so the whole structure compiles without a key. Text, never
        a PNG — `draw_mermaid_png()` posts the graph to a third-party API.

        The warnings matter more here than anywhere else in the codebase. This
        path is stateless, so it holds no workflow library and no package: a
        `workflow.subgraph` naming a hosted child, or an agent bound to a tool
        that lives in a package folder, resolves to nothing. The runtime already
        records exactly that (`unresolved_subgraphs`/`unresolved_tools`), and
        `runtime_warnings` already spells it out — surfacing it is the whole
        difference between "your graph is fine" and "your graph is fine here,
        and will be missing three capabilities when you run it for real".
        """
        from openstategraph.api.registries import runtime_warnings
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        runtime = NodeRuntime(model=None)
        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        graph = compiler.build(document, RunState, runtime.factory(document))
        mermaid = graph.get_graph(xray=True).draw_mermaid()
        return mermaid, list(plan.warnings) + runtime_warnings(runtime)

    @staticmethod
    def _run_snippet() -> str:
        """How to run the artifact without this editor — the point of being a
        compiler rather than a runtime. Honest about both paths.

        This snippet used to hand-roll `NodeRuntime` + `WorkflowCompiler`,
        which compiles and runs and *silently drops the package's own tools*:
        verified live, the agent answered "we need to call
        chinook_list_tables" while `unresolved_tools` held all three. The
        capability wiring is exactly what `load_workflow` exists to own, so
        the snippet a client commits is the one function call.
        """
        return (
            "# The compiled output is a plain LangGraph StateGraph: it runs\n"
            "# anywhere Python runs, with or without the OpenStateGraph editor.\n"
            "#\n"
            "# In-process — point it at the package FOLDER (the one holding\n"
            "# workflow.json), so its tools/, functions/ and skills/ are wired\n"
            "# too. Compiling the document by hand skips exactly that, and an\n"
            "# agent that lost its tools answers from memory instead of failing.\n"
            "from openstategraph import load_workflow\n"
            "\n"
            'workflow = load_workflow("workflows/my-workflow")\n'
            "if workflow.warnings:\n"
            '    print("degraded:", workflow.warnings)\n'
            'print(workflow.ask("..."))\n'
            "\n"
            "# workflow.graph is the compiled LangGraph object — stream it,\n"
            "# checkpoint it, mount it in your own service.\n"
            "\n"
            "# Or against a running OpenStateGraph server:\n"
            '#   POST /api/runs  {"workflow": <the document>, "question": "..."}\n'
        )


class WorkflowLibrary:
    """Reads over a hosted workflow library, plus the one guarded write.

    Only meaningful for deployments that host workflows. The stateless flow
    never touches it.
    """

    def __init__(self, services: WorkflowServices) -> None:
        self._services = services

    def list_workflows(self, surface: str = "editor") -> list[dict[str, Any]]:
        summaries = self._services.store.list(published_only=surface == "chat")
        return [
            {
                "slug": s.slug,
                "name": s.name,
                "saved_at": s.saved_at,
                "node_count": s.node_count,
                "edge_count": s.edge_count,
                "published": s.published,
            }
            for s in summaries
        ]

    def describe(self, slug: str) -> dict[str, Any]:
        from openstategraph.api.workflow_store import validate_package

        loaded = self._load(slug)
        if "error" in loaded:
            return loaded
        document = loaded["document"]
        valid, findings = _validate(document)
        return {
            "slug": slug,
            "document": document,
            "validated": valid,
            "findings": findings,
            "package_findings": validate_package(self._services.store.directory_for(slug)),
        }

    def knowledge(self, slug: str, topic: str | None = None) -> dict[str, Any]:
        """The workflow's second brain — index tier free, doc tier on demand.

        Mirrors the runtime's own `knowledge_lookup` behaviour deliberately: a
        miss answers with the *menu*, so a caller that guessed a topic name
        gets the right ones to try next.
        """
        from openstategraph.knowledge import PackageKnowledge, UnknownTopicError

        try:
            directory = self._services.store.directory_for(slug)
        except Exception as exc:  # noqa: BLE001 — InvalidSlugError, as data
            return {"error": str(exc), "topics": [], "body": None}
        if not directory.is_dir():
            return {"error": f"No workflow named {slug!r}", "topics": [], "body": None}

        store = PackageKnowledge(directory)
        index = [{"name": e.name, "hint": e.hint} for e in store.topics()]
        if topic is None:
            return {"slug": slug, "topics": index, "body": None, "error": None}
        try:
            return {"slug": slug, "topics": index, "body": store.lookup(topic), "error": None}
        except UnknownTopicError:
            return {
                "slug": slug,
                "topics": index,
                "body": None,
                "error": f"No knowledge topic {topic!r} — the available topics are listed.",
            }

    def plugin_export(self, slug: str) -> dict[str, Any]:
        """Preview this package as an Agent Plugins v1 plugin. A report only —
        nothing is written, and the lossy edges come back as `notes`."""
        from openstategraph.plugin_interop import InvalidPluginError, export_plugin

        try:
            directory = self._services.store.directory_for(slug)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}
        if not directory.is_dir():
            return {"error": f"No workflow named {slug!r}"}
        try:
            export = export_plugin(directory)
        except InvalidPluginError as exc:
            return {"error": str(exc)}
        return {
            "manifest": export.manifest,
            "paths": sorted(export.files),
            "notes": export.notes,
            "error": None,
        }

    def save_draft(self, slug: str | None, name: str, document: Any) -> dict[str, Any]:
        """Write a DRAFT. Never publishes, never overwrites a published one.

        Validate-before-save is enforced here, server-side, rather than trusted
        to the client: an invalid document comes back as findings and is not
        written at all, so the library can never accumulate documents that do
        not compile. The client iterates and calls again.

        **`slug` is optional, and omitting it is the safe call** (ticket 20).
        A slug is an identity, not a transform of a name, so an agent asked to
        "save this as My Workflow" that invents `my-workflow` is guessing — and
        a guess that lands on somebody's existing draft replaces it. Passing
        `None` asks the store to mint a free slug and reports which one it got.
        Naming a slug still means "this exact package", which is what a client
        updating a draft it created earlier wants.
        """
        store = self._services.store
        try:
            resolved = normalize_document(document)
        except DocumentError as exc:
            return {"saved": False, "findings": [str(exc)], "slug": slug, "published": False}

        if slug is not None:
            try:
                directory = store.directory_for(slug)
            except Exception as exc:  # noqa: BLE001 — InvalidSlugError, as data
                return {"saved": False, "findings": [str(exc)], "slug": slug, "published": False}

        valid, findings = _validate(resolved)
        if not valid:
            return {"saved": False, "findings": findings, "slug": slug, "published": False}

        if slug is None:
            minted = store.create(
                name=name,
                document=resolved,
                saved_at=datetime.now(timezone.utc).isoformat(),
            )
            return {
                "saved": True,
                "slug": minted,
                "published": False,
                "findings": [],
                "note": (
                    f"Saved as a DRAFT at {minted!r} — the slug was minted here, so it "
                    "replaced nothing. Publishing is a human action in the editor and "
                    "is not exposed over MCP."
                ),
            }

        existing = directory / "workflow.json"
        if existing.is_file():
            try:
                previous = json.loads(existing.read_text())
            except (json.JSONDecodeError, OSError):
                previous = {}
            if previous.get("published") is not False:
                # Including the back-compat default (a missing flag means
                # published): MCP does not get to change what customers are
                # already talking to.
                return {
                    "saved": False,
                    "slug": slug,
                    "published": True,
                    "findings": [
                        f"{slug!r} is published. MCP writes drafts only — a human "
                        "unpublishes in the editor before it can be replaced."
                    ],
                }

        store.save(
            slug,
            name=name,
            document=resolved,
            saved_at=datetime.now(timezone.utc).isoformat(),
        )
        return {
            "saved": True,
            "slug": slug,
            "published": False,
            "findings": [],
            "note": (
                "Saved as a DRAFT. Publishing is a human action in the editor and "
                "is not exposed over MCP."
            ),
        }

    def _load(self, slug: str) -> dict[str, Any]:
        from openstategraph.api.workflow_store import InvalidSlugError, WorkflowNotFoundError

        try:
            return {"document": self._services.store.load(slug)}
        except WorkflowNotFoundError:
            return {"error": f"No workflow named {slug!r}"}
        except (InvalidSlugError, json.JSONDecodeError, OSError) as exc:
            return {"error": str(exc)}


class WorkflowRuns:
    """The only tool that can reach a model. A deployment may disable it."""

    #: `recursion_limit` counts **supersteps, not iterations** — with fan-out
    #: one lap of a loop costs several. Bounded server-side because an
    #: unbounded value from an untrusted client is a denial-of-service knob.
    MAX_RECURSION_LIMIT = 200
    DEFAULT_RECURSION_LIMIT = 50

    def __init__(self, services: WorkflowServices) -> None:
        self._services = services

    def run(
        self,
        question: str,
        slug: str | None = None,
        document: Any = None,
        recursion_limit: int | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Compile and run, synchronously — the `/api/runs` path, no streaming.

        Credentials are never accepted over MCP: the model resolves from the
        server's own environment, exactly as `apply_credentials` guarantees the
        server's env always wins.
        """
        from openstategraph.api.model_resolution import resolve_model, workflow_default_model
        from openstategraph.chat_model import build_chat_model
        from openstategraph.compile.node_runtime import RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        if slug is None and document is None:
            return {"error": "Pass either a saved `slug` or an inline `document`."}

        if document is not None and slug is not None:
            # An inline document *and* a slug: the slug still binds that
            # package's tools, memory namespace and per-workflow saver, so it
            # is gated exactly as `routes/runs._known_slug` gates the HTTP
            # body (install-experience ticket 06). Only this combination was
            # ungated — a bare `slug` goes through `_load`, which has always
            # refused an unknown one.
            from openstategraph.api.workflow_store import InvalidSlugError

            try:
                if self._services.store.describe(str(slug)) is None:
                    return {"error": f"No workflow named {slug!r}"}
            except InvalidSlugError as exc:
                return {"error": str(exc)}

        if document is not None:
            try:
                resolved = normalize_document(document)
            except DocumentError as exc:
                return {"error": str(exc), "findings": [str(exc)]}
        else:
            loaded = WorkflowLibrary(self._services)._load(str(slug))
            if "error" in loaded:
                return {"error": loaded["error"]}
            resolved = loaded["document"]

        valid, findings = _validate(resolved)
        if not valid:
            # Refuse before reaching a model: an invalid graph cannot produce a
            # meaningful answer, and the findings are the useful reply.
            return {"error": "The document does not compile.", "findings": findings}

        # The document's own `settings.recursionLimit` when the caller named
        # nothing — the same precedence `workflow_default_model` gets on the
        # next line (workflow-gallery 26). `MAX_RECURSION_LIMIT` still caps it:
        # a *client's* number is untrusted, and so is a client-supplied
        # `document`, so the server's ceiling stays below the API's 1000.
        limit = min(resolve_step_budget(recursion_limit, resolved), self.MAX_RECURSION_LIMIT)
        chat_model = build_chat_model(resolve_model(model or workflow_default_model(resolved)))
        compiler = WorkflowCompiler()
        plan = compiler.plan(resolved)
        runtime = self._services.runtime_for(slug, resolved, chat_model)

        # Same checkpointer as HTTP and `load_workflow`, from the same
        # assembly point (ticket 05). Before it, this call site built with
        # none, so a document containing `human.approval` raised at compile
        # time and the client got a stack-trace-shaped error. It now pauses
        # properly and is reported as paused — the resume *tool* is still not
        # built (register PF-04), so the honest answer is to say the run is
        # waiting and name the thread, not to pretend it finished.
        thread_id = f"mcp-{uuid.uuid4().hex}"
        try:
            graph = compiler.build(
                resolved,
                RunState,
                runtime.factory(resolved),
                checkpointer=self._services.checkpointer_for(
                    resolved.get("settings"), slug
                ),
                store=self._services.memory_store,
            )
            final = graph.invoke(
                {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
                {"recursion_limit": limit, "configurable": {"thread_id": thread_id}},
            )
        except Exception as exc:  # noqa: BLE001 — errors are data to the client
            return {"error": f"{type(exc).__name__}: {exc}", "findings": []}

        if "__interrupt__" in final:
            return {
                "error": (
                    "The run paused at a human-in-the-loop node and this server has no "
                    f"resume tool. The pause is durable on thread {thread_id!r} — resume "
                    "it through the HTTP API's /api/runs/resume, or run the workflow "
                    "without an approval node."
                ),
                "findings": [
                    str(getattr(i, "value", i)) for i in (final.get("__interrupt__") or [])
                ],
            }

        from openstategraph.api.registries import runtime_warnings

        return {
            "answer": str(final.get("answer") or ""),
            "decisions": {k: str(v) for k, v in (final.get("decisions") or {}).items()},
            "outputs": {k: str(v) for k, v in (final.get("outputs") or {}).items()},
            "attempts": int(final.get("attempts") or 0),
            "mermaid": graph.get_graph().draw_mermaid(),
            "warnings": list(plan.warnings) + runtime_warnings(runtime),
            "recursion_limit": limit,
            "error": None,
        }


SERVER_INSTRUCTIONS = """\
OpenStateGraph compiles a vendor-neutral workflow document into a LangGraph
StateGraph. You compose the document; this server is the ground truth.

The loop, in order:

1. `get_node_vocabulary()` FIRST, always. It lists every node type, its exact
   port ids and directions, which port types are control flow and which are
   capability bindings, and the locked prompt sections you must not restate.
   Composing without it is guessing.
2. Compose a document.
3. `compile_workflow(document)`. It is deterministic and calls no model. An
   invalid document returns `findings` and no artifacts — fix and call again.
   A valid one returns the `workflow.json` envelope to commit to YOUR
   repository, the compiled Mermaid topology, a run snippet and the package
   layout.
4. Optionally `save_workflow_draft(...)` if this deployment hosts workflows.
   It always writes a DRAFT; publishing is a human action in the editor and is
   not available here. Deletion and credentials are not exposed at all.
"""


def build_mcp_server(
    services: WorkflowServices | None = None, *, allow_runs: bool = True
) -> Any:
    """Assemble the MCP server over the shared runtime services.

    `services` is injected rather than constructed here so a test operates on a
    throwaway workflows root — the same rule `WorkflowStore` and `NodeRuntime`
    already follow.

    `allow_runs=False` closes `run_workflow`, which is the only tool that can
    reach a model. The rest of the surface stays fully functional, which is the
    whole point of keeping validate/compile deterministic: a deployment with no
    provider key is a complete product, not a broken one.
    """
    from openstategraph._extras import require_extra

    FastMCP = require_extra("mcp.server.fastmcp", "mcp", "the MCP transport").FastMCP

    services = services or WorkflowServices()
    vocabulary = NodeVocabulary()
    artifacts = WorkflowArtifacts()
    library = WorkflowLibrary(services)
    runs = WorkflowRuns(services)

    server = FastMCP("openstategraph", instructions=SERVER_INSTRUCTIONS)

    @server.tool(name="get_node_vocabulary")
    def get_node_vocabulary() -> dict[str, Any]:
        """CALL THIS BEFORE COMPOSING ANYTHING.

        The complete node-type and port contract: every node type the runtime
        implements, each port's id, type and direction, which port types are
        control flow versus capability bindings, the locked prompt sections you
        must not restate, the document shape, and the rules a valid graph obeys.
        You cannot compose a workflow correctly without this.
        """
        return vocabulary.describe()

    @server.tool(name="compile_workflow")
    def compile_workflow(document: Any, name: str | None = None) -> dict[str, Any]:
        """Compile-check a composed document and return committable artifacts.

        Stateless: saves nothing, calls no model, deterministic. An INVALID
        document returns `validated: false` with `findings` and no artifacts —
        read them, revise, call again. That loop is how you converge.

        A VALID document returns: `document` (the normalized workflow.json
        envelope, ready to commit to your own repository), `mermaid` (the
        topology the compiler actually produced — a mounted child is **one
        box**, because this path holds no workflow library and so has no
        child to draw; see `warnings`),
        `run_snippet` (how to run it without this editor) and
        `package_skeleton` (the full package layout).

        READ `warnings` even when validated is true. They name capabilities
        the document refers to that could not be resolved here — a mounted
        child workflow, a tool that lives in a package folder. "Compiles" is
        not "will be fully capable when run".
        """
        return artifacts.compile(document, name)

    @server.tool(name="validate_workflow")
    def validate_workflow(document: Any) -> dict[str, Any]:
        """The verdict alone: `validated` plus `findings`.

        Cheaper than `compile_workflow` when you are mid-iteration and do not
        yet want the artifacts.
        """
        return artifacts.validate(document)

    @server.tool(name="list_workflows")
    def list_workflows(surface: str = "editor") -> list[dict[str, Any]]:
        """Workflows this deployment hosts, if it hosts any.

        `surface="editor"` lists everything including drafts, each with its
        `published` flag; `surface="chat"` lists only what a human published.
        """
        return library.list_workflows(surface)

    @server.tool(name="describe_workflow")
    def describe_workflow(slug: str) -> dict[str, Any]:
        """One hosted workflow: its document, its compile verdict and its
        package findings. Use it to read an existing graph before editing it."""
        return library.describe(slug)

    @server.tool(name="get_knowledge")
    def get_knowledge(slug: str, topic: str | None = None) -> dict[str, Any]:
        """A workflow's second brain, progressively.

        Without `topic`: the index — one name and one-sentence hint per topic,
        cheap enough to always afford. With `topic`: that topic's full document.
        An unknown topic answers with the available menu, not a bare miss.
        """
        return library.knowledge(slug, topic)

    @server.tool(name="export_plugin")
    def export_plugin(slug: str) -> dict[str, Any]:
        """Preview a hosted workflow as an Agent Plugins v1 plugin.

        A report: the manifest, the file layout, and honest `notes` naming
        everything that does not survive the crossing. Writes nothing.
        """
        return library.plugin_export(slug)

    @server.tool(name="save_workflow_draft")
    def save_workflow_draft(slug: str | None, name: str, document: Any) -> dict[str, Any]:
        """Save a workflow into this deployment's library AS A DRAFT.

        Optional — the primary flow keeps the artifact in your own repository
        (see `compile_workflow`). Guardrails, enforced server-side: the
        document is validated first and an invalid one is REFUSED with
        findings rather than written; the write is always a draft; a published
        workflow is never overwritten. Publishing is a human action in the
        editor and is not exposed here.

        **Pass `slug=None` for a new workflow.** The server mints a free slug
        from `name` and the response says which — the first "My Workflow" gets
        `my-workflow`, a second gets its own. Naming a slug means "update this
        exact package"; do that only for one you saved earlier, because a slug
        you derived from a name yourself may belong to somebody else's draft.
        """
        return library.save_draft(slug, name, document)

    if allow_runs:

        @server.tool(name="run_workflow")
        def run_workflow(
            question: str,
            slug: str | None = None,
            document: Any = None,
            recursion_limit: int | None = None,
            model: str | None = None,
        ) -> dict[str, Any]:
            """Run a workflow once, synchronously, and return its answer.

            Pass either a hosted `slug` or an inline `document`. This is the
            only tool that reaches a model; it uses the SERVER's credentials —
            never send keys over MCP. `recursion_limit` counts supersteps, not
            iterations, and is bounded server-side.
            """
            return runs.run(question, slug, document, recursion_limit, model)

    return server


def main() -> None:
    """`python -m openstategraph.mcp_server`.

    stdio by default — the transport an MCP client spawns locally.
    ``OPENSTATEGRAPH_MCP_ALLOW_RUNS=0`` closes the one tool that needs a model.

    **Authentication (scale-and-adopt ticket 06).** ``streamable-http`` opens a
    TCP port, and a port with no credential lets any client on the network run
    `run_workflow` on the deployer's model budget. Setting
    ``OPENSTATEGRAPH_API_TOKEN`` — the same variable the HTTP API uses, because
    it is the same deployment and two secrets would mean one of them unset —
    puts a bearer-token gate in front of the transport. It is machine-only
    here: no login form, because an MCP client cannot fill one in.

    stdio is deliberately **not** gated. The client is the parent process that
    spawned this one; it already has whatever access the operating system gives
    it, and a token on a pipe would be theatre. A reverse proxy
    (`deploy/Caddyfile`) remains the supported answer for anything public — the
    token is the floor, not the ceiling.
    """
    transport = os.getenv("OPENSTATEGRAPH_MCP_TRANSPORT", "stdio")
    allow_runs = os.getenv("OPENSTATEGRAPH_MCP_ALLOW_RUNS", "1") != "0"
    server = build_mcp_server(allow_runs=allow_runs)
    if transport == "streamable-http":
        _run_gated_http(server)
        return
    server.run(transport=transport)  # type: ignore[arg-type]


def _run_gated_http(server: Any) -> None:
    """Serve the streamable-HTTP app, behind the token gate when one is set.

    `FastMCP.run(transport="streamable-http")` would serve
    `server.streamable_http_app()` itself; we ask for the Starlette app and run
    uvicorn over it so the same `TokenGate` that guards the HTTP API guards
    this too. One implementation of "is this caller allowed in", not two.
    """
    import uvicorn

    from openstategraph.api.auth import API_TOKEN_ENV, TokenGate, configured_token

    app: Any = server.streamable_http_app()
    token = configured_token()
    if token is None:
        logger.warning(
            "MCP streamable-http is listening with NO authentication: any client "
            "that can reach this port can compile workflows, read hosted ones, "
            "write drafts and spend this deployment's model budget. Set %s, or "
            "put it behind the reverse proxy in deploy/Caddyfile. "
            "See docs/deploying.md.",
            API_TOKEN_ENV,
        )
    else:
        app = TokenGate(app, token, open_paths=(), login_path=None)
        logger.info("MCP streamable-http requires a bearer token (%s)", API_TOKEN_ENV)
    uvicorn.run(app, host=server.settings.host, port=server.settings.port)


if __name__ == "__main__":
    main()
