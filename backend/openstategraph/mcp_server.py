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
- **`run_workflow` is a run door, and it is the one part of this module that
  is not authoring.** Everything above composes; that tool *runs*, on the
  deployer's model budget, and this module's own run-journal note calls it
  "the one a customer's own model calls". So it answers to an audience like
  `/api/runs`, `/api/runs/stream` and the CLI do, and the audience is the
  **deployment's** — `OPENSTATEGRAPH_AUDIENCE`, through
  `audience.deployment_audience()` — never an argument on the tool, because
  the client filling in a tool's arguments here is a model
  (`the-boundary-nobody-checked/08`). Unset means customer: no fence in the
  answer or in `outputs`, and no `warnings` key at all.
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
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from openstategraph.api.audience import deployment_audience
from openstategraph.api.diagram import workflow_mermaid
from openstategraph.api.services import WorkflowServices
from openstategraph.errors import DocumentError as _DocumentError
from openstategraph.kanban_store import STALE_THRESHOLD_SECONDS as _STALE_THRESHOLD_SECONDS
from openstategraph.principal import IPrincipals
from openstategraph.run_doors import invoke_run
from openstategraph.schema import normalize_document as _normalize_document
from openstategraph.step_budget import (
    STEP_BUDGET_KEYS,
    resolve_step_budget,
    step_budget_document_hint,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context as _MCPContext

    from openstategraph.abc.kanban_store import IKanbanStore
    from openstategraph.kanban_store import Card
else:  # the `[mcp]` extra. An installation without it never builds a server,
    # but must still be able to import this module.
    try:
        from mcp.server.fastmcp import Context as _MCPContext
    except ModuleNotFoundError:  # pragma: no cover - the extra-less install
        _MCPContext = None

#: The `ctx` parameters below are annotated with the **bare** generic on
#: purpose: FastMCP finds the parameter to inject the request context into
#: with `inspect.isclass` over the resolved type hints, and a subscripted
#: `Context[Any, Any, Any]` is an alias rather than a class, so subscripting
#: to satisfy mypy's `type-arg` would silently stop the injection and take
#: `kanban-patrol/29` with it. Hence the two `type: ignore[type-arg]`s.

logger = logging.getLogger(__name__)

#: The complete, reviewed surface. A tool absent from this tuple does not
#: exist over MCP — publishing, deleting and anything credential-shaped are
#: absent deliberately, and a test asserts it.
EXPOSED_TOOLS: tuple[str, ...] = (
    "get_node_vocabulary",
    "get_engineering_rules",
    "compile_workflow",
    "validate_workflow",
    "list_workflows",
    "describe_workflow",
    "get_knowledge",
    "export_plugin",
    "save_workflow_draft",
    "run_workflow",
    "kanban_attend_card",
    "kanban_set_stage",
    "kanban_list_cards",
    "kanban_show_card",
    "kanban_release_card",
    "kanban_answer_card",
    "kanban_file_card",
    "kanban_triage",
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
                    # True when the **editor** executes this type and this
                    # runtime has no implementation for it. A composing client
                    # that places one gets a document that validates, runs, and
                    # reports the tool as missing after the model has been paid
                    # (`osg-agent-experience/72`), so the mark is published
                    # here rather than discovered there. `validate_workflow`
                    # names it too, as a `no-backend` finding.
                    "editor_only": node_type in CATALOGUE.editor_only,
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
                    # The config schema, launch-readiness/18: what a client must
                    # set in `data` to use this node, derived from the same
                    # field declaration the editor's card and inspector render
                    # from (`src/nodes/portSpecs.ts`), never a second copy.
                    "fields": [
                        {
                            "key": field["key"],
                            "kind": field["kind"],
                            "label": field.get("label", ""),
                            "hint": field.get("hint", ""),
                            "required": bool(field.get("required", False)),
                            "default": field.get("defaultValue"),
                            # The half a `kind` alone does not give you
                            # (`osg-agent-experience/33`): `select` says a
                            # string goes here, and the options say *which*
                            # strings. Without them a client that reads the
                            # vocabulary still has to guess `matchMode`, and a
                            # guessed value is a finding rather than a run.
                            "options": [
                                {"value": option.get("value"), "label": option.get("label", "")}
                                for option in field.get("options") or ()
                            ],
                        }
                        for field in record.get("fields") or ()
                    ],
                    "generated_ports": [
                        {
                            "prefix": group.prefix,
                            "type": group.type,
                            "direction": group.direction,
                            # How many edges *one* generated port takes — not
                            # how many ports there are. A branch takes one
                            # (`osg-agent-experience/38`); publishing it is
                            # what lets a renderer stop guessing
                            # (`osg-agent-experience/53`). `null` is a bus,
                            # exactly as on a static port.
                            "max_connections": group.max_connections,
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
            # A namespace whose members are minted per workflow package, and —
            # since `osg-agent-experience/46` — the ports every member of it
            # has. The sentence alone was what a composing client got, so the
            # ids had to be found by reading `default_port_resolver`, whose
            # fallback accepts any in-port id and treats `result` alone as the
            # way out: a document naming a port the editor cannot draw
            # compiled clean. Generated, never typed here — the factory that
            # mints these nodes is the declaration, exactly as it is for a
            # router's branches.
            "dynamic_type_prefixes": {
                str(entry["prefix"]): {
                    "hint": str(entry.get("hint") or ""),
                    "probe_type": str(entry.get("probe_type") or ""),
                    "ports": [
                        {
                            "id": port["id"],
                            "type": port["type"],
                            "direction": port["direction"],
                            "label": port.get("label", ""),
                            "required": bool(port.get("required")),
                            "max_connections": port.get("max_connections"),
                            "accepts": list(port.get("accepts") or ()),
                        }
                        for port in entry.get("ports") or ()
                    ],
                }
                for entry in CATALOGUE.type_prefixes
                if str(entry["prefix"]) in KNOWN_PREFIXES
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
                # `osg-agent-experience/29`: the step budget is the setting
                # that ends a revision loop, and this shape — the
                # authoritative example a composing client reads — did not
                # name it. `workflow_step_budget` is tolerant, so a guess was
                # silently ignored and the document inherited the default with
                # nothing reported. Derived from `step_budget.py`, key and
                # sentence both, so the published shape and the reader cannot
                # drift.
                "settings": {
                    "model": "optional; omit to use the server default",
                    STEP_BUDGET_KEYS[0]: step_budget_document_hint(),
                },
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
                "A node's `data` keys are exactly its `fields` list above — "
                "check that list before setting any key. compile_workflow "
                "does not currently reject an unrecognised or missing "
                "required key by itself; guessing produces a document that "
                "may still validate while the node silently lacks what it "
                "needs to run.",
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
        that lives in a package's own `tools/` folder, resolves to nothing.
        The runtime already records exactly that
        (`unresolved_subgraphs`/`unresolved_tools`), and `runtime_warnings`
        already spells it out — surfacing it is the whole difference between
        "your graph is fine" and "your graph is fine here, and will be
        missing capabilities when you run it for real".

        **Built-in tools are not in that position, and must not be reported
        as though they were** (`launch-readiness` 17). `build_tool_registry`
        layers built-ins and installed plugins under a workflow's own
        `tools/` — and the first two layers need no slug and no package root
        at all, exactly like `get_node_vocabulary`'s catalogue. Passing no
        tools here bound *nothing*, so the shipped `sql-qa` example — three
        `SQL_EXPLORER_TOOLS` nodes, no package-local tool in sight — came back
        accused of missing an implementation for all three, forever
        unsatisfiable by any revision because the document was never wrong.
        The same `(builtin, discovered)` layer the CLI and the HTTP API bind
        from is bound here too; only the third, slug-scoped layer is out of
        reach, because this call carries no slug to scope it to.
        """
        from openstategraph.api.registries import build_tool_registry, runtime_warnings
        from openstategraph.compile.node_runtime import NodeRuntime, RunState
        from openstategraph.compile.workflow_compiler import WorkflowCompiler

        # No slug: `build_tool_registry` skips the workflow-local layer
        # entirely and never touches `workflow_store`, so `None` is safe —
        # this door still has no package root to scope a slug to.
        tools = build_tool_registry(None, None)
        runtime = NodeRuntime(model=None, tools=tools)
        compiler = WorkflowCompiler()
        plan = compiler.plan(document)
        graph = compiler.build(
            document,
            RunState,
            runtime.factory(document),
            # `runtime_warnings(runtime)` is this door's return value, so a
            # compile-time finding has to be recorded where that reads it
            # (`langchain-drift-watch` 01).
            diagnostics=runtime.diagnostics,
        )
        # Through the one seam, with no store and no audience: this path
        # holds no workflow library, so `mounted_documents` finds nothing to
        # load and the diagram is flat — which is the true picture of what
        # would compile here, and is the shape the paragraph above promises.
        mermaid = workflow_mermaid(graph, document, runtime=runtime)
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

    def save_draft(
        self, slug: str | None, name: str | None, document: Any
    ) -> dict[str, Any]:
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

        **`name` is optional too, and reading it tolerates the shape
        `compile_workflow` hands back** (launch-readiness 22). Its envelope is
        `{version, name, savedAt, published, document}` — the same envelope
        `normalize_document` already unwraps for `document` itself, so a
        client that passes that envelope straight through as `document` is
        composing the two tools exactly as their outputs invite. Deriving
        `name` from that same payload, rather than demanding it a second time
        as a sibling argument, is what makes the pair actually compose. The
        precedence — explicit argument, then the envelope's own `name`, then
        the inner document's `name`, then the slug, then a last-resort default
        — mirrors `workflow_store._summarize`'s `payload.get("name") or
        document.get("name") or slug`, the same fallback this codebase already
        uses when reading a saved `workflow.json` back. This is reading
        tolerantly, not trusting loosely: what gets written is still whatever
        `normalize_document` + `_validate` resolve and accept below, exactly
        as before.
        """
        store = self._services.store
        envelope = document if isinstance(document, dict) else {}
        inner = envelope.get("document")
        inner = inner if isinstance(inner, dict) else {}
        resolved_name = (
            name
            or envelope.get("name")
            or inner.get("name")
            or slug
            or "Untitled workflow"
        )
        name = str(resolved_name)
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
        session_id: str | None = None,
        *,
        audience: Any,
    ) -> dict[str, Any]:
        """Compile and run, synchronously — the `/api/runs` path, no streaming.

        Credentials are never accepted over MCP: the model resolves from the
        server's own environment, which is the strongest form of the rule
        `apply_credentials` applies to the HTTP doors — there, a request
        credential is taken only on a machine whose caller is the operator, and
        here there is no channel to take one through at all
        (`the-boundary-nobody-checked/03`, which corrected the older claim that
        a client's key "can only ever lose to the server's own": true only
        where the server has one).

        **This is a run door, and it answers to an audience like the other
        three** (`the-boundary-nobody-checked/08`). It used to answer to none:
        the fence stayed welded into `answer` and into every value of
        `outputs`, and `warnings` — plan findings, `runtime_warnings`, run
        failures and silent nodes, sentences naming node ids and unbound tool
        types — rode the payload unconditionally, on the door this module's own
        run-journal note calls *"the one a customer's own model calls"*.

        `audience` is a **required keyword with no default**, which is
        `run_sinks.read_run_bursts`' shape and it is required for that ticket's
        reason: the audience *removes* content every caller here used to get,
        and a default would remove it from somebody who never knew they were
        being asked. It is still capped by `resolve()`, so a deployment that
        set `OPENSTATEGRAPH_AUDIENCE=customer` caps this door too.

        Where the MCP *tool* gets its value from is the decision that ticket
        turned on, and it is not an argument on the tool — see
        `audience.deployment_audience`.
        """
        from openstategraph.api.audience import (
            DeveloperChannel,
            clean_output,
            resolve as resolve_audience,
            split_suggestion,
            with_capability_notice,
        )
        from openstategraph.api.model_resolution import resolve_model, workflow_default_model
        from openstategraph.chat_model import build_chat_model
        from openstategraph.compile.node_runtime import RunState, drives_a_model
        from openstategraph.compile.workflow_compiler import WorkflowCompiler
        from openstategraph.model_readiness import unmet_model_requirement, would_reach_no_model

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
        audience = resolve_audience(audience)
        # The *generation* half, which this door had left at its default.
        # `runtime_for` already names MCP among the transports that get the
        # customer half — passing it explicitly is what makes the two halves
        # one decision rather than two conventions that happen to agree.
        runtime = self._services.runtime_for(slug, resolved, chat_model, audience=audience)

        # Same checkpointer as HTTP and `load_workflow`, from the same
        # assembly point (ticket 05). Before it, this call site built with
        # none, so a document containing `human.approval` raised at compile
        # time and the client got a stack-trace-shaped error. It now pauses
        # properly and is reported as paused — the resume *tool* is still not
        # built (register PF-04), so the honest answer is to say the run is
        # waiting and name the thread, not to pretend it finished.
        # **Who this run is for, in the vocabulary every other door uses**
        # (ship-it 54). Ticket 47 taught `ask()` these four keys and taught
        # `routes/runs.py` the same four; this door kept building `thread_id`
        # alone, so `workflow_scope_slug()` answered `None` for a *saved*
        # package and its ledger merged into the `"unsaved"` bucket shared by
        # every workflow ever run over this transport.
        #
        # Two of the four have an honest source here and two do not, and the
        # difference is the point rather than an omission:
        #
        # - `workflow_slug` is a value this call site already **holds** — it
        #   is handed to `checkpointer_for` on the line below. Dropping it was
        #   the defect.
        # - `thread_id` is minted here, as it always was.
        # - `user_email` is **left unbound on purpose**. An MCP client is a
        #   model, not a person; the HTTP door refuses a client-supplied
        #   `user_email` with a 422 precisely because the server determines it,
        #   and this transport has no principal resolver. `_user_namespace()`
        #   answers `None` for an empty value and logs it, which is the
        #   correct, loud degradation memory ticket 01 installed. Binding a
        #   name nobody authenticated would be worse than not binding one.
        # - `session_id` scopes thread *listing*, which is a browser-tab
        #   concept. There is no session here to name. `memory-and-replay/45`
        #   gave that field a writer — the editor mints one per tab — and
        #   decided this door **never mints one**: a per-call mint would be a
        #   synonym for `thread_id`, which is minted per call two lines below,
        #   and a session grouping exactly one thread groups nothing. Pinned,
        #   so the absence reads as a decision rather than an oversight, by
        #   `tests/test_a_sitting_is_named_by_the_browser.py`.
        #
        #   **A caller may still declare one** (`kanban-patrol/08`), and that
        #   is a different act from minting. An agent working board card `X`
        #   over this transport passes `card:X`, which groups every thread it
        #   opens while working that card — several threads, which is the axis
        #   the field was settled on — so a later patrol can tell the board's
        #   own shadow from ordinary traffic. Unset stays `""`, which is every
        #   caller that is not working the board.
        #
        # They are still written, as empty strings, rather than omitted: the
        # key set is what a reader compares across doors, and an absent key is
        # indistinguishable from a forgotten one. That comparison is a test —
        # `tests/test_every_run_door_carries_identity.py`.
        thread_id = f"mcp-{uuid.uuid4().hex}"
        from openstategraph.api.registries import runtime_warnings
        from openstategraph.run_journal import run_turn

        # **The third door that wrote nothing down** (`memory-and-replay` 44).
        # It is the one a customer's own model calls, so a deployment whose
        # traffic arrives over MCP left no history at all. Identity comes from
        # the same four keys the config below carries — including the two this
        # transport honestly has no source for, which stay empty rather than
        # invented (see the note above).
        with run_turn(
            workflow_slug=str(slug or ""),
            thread_id=thread_id,
            question=question,
            session_id=str(session_id or ""),
        ) as turn:
            try:
                graph = compiler.build(
                    resolved,
                    RunState,
                    runtime.factory(resolved),
                    checkpointer=self._services.checkpointer_for(
                        resolved.get("settings"), slug
                    ),
                    store=self._services.memory_store,
                    # The runtime's own sink, so this door reports what the
                    # compiler noticed while building, like the other two
                    # (`langchain-drift-watch` 01).
                    diagnostics=runtime.diagnostics,
                )
                # Built, therefore knowable (`osg-agent-experience/48`). This
                # door had the same defect as the other two: half a graph would
                # run and a worker would die naming a credential. Returned
                # rather than raised — errors are data to this client — and in
                # the same `error`/`findings` shape an uncompilable document
                # already gets, with the readiness sentence every other surface
                # prints. See `model_readiness`.
                no_model = would_reach_no_model(
                    drives_model=drives_a_model(runtime), model=chat_model
                )
                unmet = unmet_model_requirement(no_model=no_model)
                if unmet is not None:
                    return {"error": unmet, "findings": [unmet]}
                final = invoke_run(
                    graph,
                    {"question": question, "attempts": 0, "decisions": {}, "outputs": {}},
                    {
                        "recursion_limit": limit,
                        "configurable": {
                            "thread_id": thread_id,
                            "session_id": str(session_id or ""),
                            "user_email": "",
                            "workflow_slug": str(slug or ""),
                        },
                    },
                )
            except Exception as exc:  # noqa: BLE001 — errors are data to the client
                return {"error": f"{type(exc).__name__}: {exc}", "findings": []}

            # Above the pause branch, like the HTTP door: a run that stopped at
            # a gate is a turn that happened.
            # Read after the run: `runtime_warnings` collects what the runtime
            # could not resolve while it ran.
            degraded = list(plan.warnings) + runtime_warnings(runtime)
            turn.record(final, warnings=degraded)

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

        from openstategraph.compile.state import published_answer, published_routes
        from openstategraph.compile.workflow_compiler import (
            RUN_FAILED_ANSWER,
            redact_failure_markers,
            run_health_from_state,
            suggestion_from_rejection,
        )

        # `run_health_from_state` is the library door's own machinery
        # (`workflow-gallery` 49): it reads every run-health source off
        # finished state by name, so a source added there is never missed
        # here. Until `workflow-gallery` 31's second half, this tool built
        # `warnings` from `plan.warnings + runtime_warnings(runtime)` alone —
        # the two *compile-time* channels — and never looked at `final` at
        # all. A grader whose `revise` verdict reached no wired edge (an
        # `unrouted` entry, same as a forced pass or a silent node) was
        # therefore reported on `/api/runs`, `/api/runs/stream` and
        # `load_workflow`, and shipped silently on the one door a customer's
        # own LLM actually calls to run a workflow.
        health = run_health_from_state(final)

        # The same seam as `/api/runs`, applied in the same order, because
        # this is the same kind of door (`the-boundary-nobody-checked/08`).
        # The fence leaves the answer **before** anyone asks who is listening,
        # so a developer audience is not the way to get one back — it arrives
        # on `suggestion`, as a field, the way `done` carries it.
        whole_answer = published_answer(final)
        prose, suggestion = split_suggestion(whole_answer)
        if suggestion is None:
            # A fallback, never an override (`every-workflow-green` 33).
            suggestion = suggestion_from_rejection(final.get("unmet_tools"))
        developer = (
            DeveloperChannel(
                warnings=degraded + health.failures + health.silent,
                suggestion=suggestion,
            )
            .payload(audience)
            .get("developer")
        )

        # A step failed and no answer was produced. `/api/runs`' floor, owed
        # here for the same reason and newly owed at all: withholding the
        # warnings from a customer would otherwise turn a dead run into a
        # blank string with `error: null`.
        if not prose.strip() and health.failures:
            prose = RUN_FAILED_ANSWER
        # Ticket 51 — the sentences stay developer-only, *the fact* cannot.
        # A customer who no longer reads the warnings must still be told the
        # run was degraded, or a lost capability reads as a confident answer.
        # It is handed the **runtime**, not `degraded`: that list is the whole
        # developer channel, and a report on it is a static property of the
        # document, which made the notice permanently on
        # (`every-workflow-green` 47). `capability_loss_warnings` owns which
        # warnings the sentence is about.
        prose = with_capability_notice(prose, runtime, audience)
        raw_outputs = final.get("outputs") or {}
        visible = raw_outputs if developer else redact_failure_markers(raw_outputs)

        payload: dict[str, Any] = {
            # The whole answer, every exit included (`launch-readiness/174`).
            "answer": prose,
            "decisions": {k: str(v) for k, v in (final.get("decisions") or {}).items()},
            # Every branch a parallel router matched, not only the one
            # dispatched on (`launch-readiness/175`). Through the seam, like
            # every other door: a client that asked for `matchMode: "all"` is
            # exactly the reader who needs to know it opened two desks.
            "routes": published_routes(final),
            # Cleaned per value, not only in `answer`: ticket 15 found the
            # same fence one field along on the door that cleaned only the one.
            "outputs": {k: str(clean_output(str(v))) for k, v in visible.items()},
            "attempts": int(final.get("attempts") or 0),
            # Both audiences, on purpose (`launch-readiness` 25): the grader's
            # reason is guidance and stays on `warnings`, but that a rejected
            # candidate was published anyway is a fact about this run.
            "published_rejected": health.published_rejected,
            # Unlike `compile_workflow` above, this path *has* a library:
            # it just ran the children, so it can draw them. Until
            # `workflow-gallery` 62 it published `get_graph().draw_mermaid()`
            # and a mount was one box here too. In the caller's own
            # vocabulary now, like every other run door.
            "mermaid": workflow_mermaid(
                graph,
                resolved,
                runtime=runtime,
                audience=audience,
                store=self._services.store,
            ),
            "recursion_limit": limit,
            "error": None,
        }
        if developer:
            # Absent, not empty, for a customer — `DeveloperChannel.payload`
            # decides, so the fact "warnings are authoring diagnostics" is
            # still written down in exactly one place.
            payload["warnings"] = developer["warnings"]
            payload["suggestion"] = developer["suggestion"]
        return payload


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


def _card_payload(store: "IKanbanStore", card: "Card") -> dict[str, Any]:
    """One card, as both kanban read tools answer with it — `kanban-patrol/16`.

    `card_row` is the same function `GET /api/kanban/cards` builds its rows
    from, so an agent reading the board over MCP and a person reading it in a
    browser are reading one shape. The one field added here is `column`,
    which the browser derives for itself in TypeScript and a client of this
    server cannot.
    """
    from openstategraph.kanban_store import card_row, column_for, flagged_stale

    stale = card.task_id in set(
        flagged_stale(store, threshold_seconds=_STALE_THRESHOLD_SECONDS)
    )
    return {**card_row(card, stale=stale), "column": column_for(card)}


def _actor_on_the_card(principals: IPrincipals, ctx: Any, claimed: str) -> str:
    """Who a kanban write is recorded as — `kanban-patrol/29`.

    `principal.py`'s standing rule is that identity is the server's to
    determine, never the caller's to assert, and over MCP the caller filling
    in `actor` is a *model*. So when this deployment can identify the person
    behind the request, that principal **is** the actor and a differing
    `actor` argument is dropped, never merged — the same `IPrincipals` the
    HTTP door resolves through (`api/deps.py`), not a second identity scheme.

    When nothing resolves, the caller's `actor` stands, exactly as before.
    That is `kanban-patrol/20`'s own argument carried over: the transport's
    token gate is the trust bar, and refusing here would make the kanban
    tools unusable on every `streamable-http` deployment with no proxy in
    front — which is the documented default. Nothing resolves in three
    distinct cases and all three are this one: stdio, which has no HTTP
    request at all; a request with no identity header; and a request
    carrying one with no proxy signature beside it, which `principal.py`
    treats as carrying nothing because a header a client can also set is not
    identity.
    """
    headers = _request_headers(ctx)
    who = principals.resolve(headers) if headers is not None else None
    if who is None:
        return claimed
    name = who.label or who.id
    if claimed.strip() and claimed.strip() != name:
        # Info, not a warning: a client model naming itself is the ordinary
        # case, not an attack, and this line exists so a reader of the logs
        # can see why the card says a name the client did not send.
        logger.info(
            "kanban: recording %r as the actor, not the %r the caller passed "
            "— this deployment identifies its callers.",
            name,
            claimed,
        )
    return name


def _request_headers(ctx: Any) -> Mapping[str, str] | None:
    """The HTTP headers this tool call arrived on, or `None` when it did not
    arrive on one.

    `kanban-patrol/28` found the seam: the streamable-HTTP transport puts the
    Starlette request on the `RequestContext` it dispatches under, so a tool
    declaring a `Context` parameter can read it. Under stdio there is no
    request and `Context.request_context` itself raises outside one, so every
    way of having no headers is folded into `None` here rather than at three
    call sites.
    """
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request
    except (ValueError, LookupError, AttributeError):  # pragma: no cover - defensive
        return None
    headers = getattr(request, "headers", None)
    return headers if isinstance(headers, Mapping) else None


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

    @server.tool(name="get_engineering_rules")
    def get_engineering_rules() -> dict[str, Any]:
        """CALL THIS BEFORE COMPOSING ANYTHING, beside `get_node_vocabulary`.

        The vocabulary says what exists; this says what may be built out of
        it — the interface/abstract/base/concrete ladder, extension by
        registration, port cardinality, one field schema, tests first, and
        the rule that decides most arguments: never invent a node type the
        registry does not know (making a new one is fine, through the
        family's base, registered first).

        Deterministic: no model, no store, no credentials. `version` is the
        installed package's, because these are the rules of the release the
        caller actually has.
        """
        from openstategraph import __version__
        from openstategraph.engineering_rules import read_engineering_rules

        return {"version": __version__, "rules": read_engineering_rules()}

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
    def save_workflow_draft(
        slug: str | None, document: Any, name: str | None = None
    ) -> dict[str, Any]:
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

        **`document` accepts `compile_workflow`'s own return value.** Pass its
        `document` field straight through — the envelope
        `{version, name, savedAt, published, document}` — and this tool reads
        the name out of it. `name` is only needed here if you want to save
        under a different title than the one you compiled with, or if you are
        handing in a bare document that never went through `compile_workflow`.
        """
        return library.save_draft(slug, name, document)

    @server.tool(name="kanban_attend_card")
    def kanban_attend_card(
        task_id: str,
        actor: str,
        ctx: _MCPContext | None = None,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Claim a patrol-board card, exclusively — `kanban-patrol/16`/`19`.

        First caller wins. A second call on an already-attended card returns
        `{"ok": false, "reason": "..."}` naming who has it — never an
        exception, and never a silent overwrite. Same guarantee, same
        function, as the `openstategraph kanban attend` CLI door.
        """
        from openstategraph.kanban_store import Stage, open_kanban_store

        result = open_kanban_store(services.store.root).set_stage(
            task_id,
            Stage.ATTENDED,
            actor=_actor_on_the_card(services.principals, ctx, actor),
        )
        return {"ok": result.ok, "reason": result.reason}

    @server.tool(name="kanban_set_stage")
    def kanban_set_stage(
        task_id: str,
        stage: str,
        actor: str,
        test_id: str = "",
        reason: str = "",
        commit: str = "",
        ctx: _MCPContext | None = None,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Advance a claimed card one stage: `red`, `green`, or `finished`.

        Stage only ever advances one step at a time. Skipping a stage or
        moving backward is reported as `{"ok": false, "reason": "..."}`
        rather than raised over the transport — a client's model reads a
        structured refusal far more reliably than a stack trace.

        `kanban-patrol/17`+`21`: the same evidence gate the CLI enforces.
        `red` needs `test_id` and `reason`; `green` needs the matching
        `test_id`; `finished` needs both already recorded plus `commit` — a
        missing or mismatched piece of evidence is refused the same structured
        way as a skipped stage, never a fresh assertion accepted at the end.

        `osg-agent-experience/85`: **`reason` is read at exactly two stages.**
        At `red` it is why the test fails, and it is required. At `finished`
        it is what your closing checks said, and it is kept on the card. At
        `attended` and `green` it is **refused by name** rather than accepted
        and dropped — pass it at one of the two stages that keep it.
        """
        from openstategraph.kanban_store import (
            MissingEvidenceError,
            Stage,
            StageOrderError,
            open_kanban_store,
        )

        store = open_kanban_store(services.store.root)
        try:
            target = Stage(stage)
        except ValueError:
            return {"ok": False, "reason": f"stage must be one of {', '.join(s.value for s in Stage)}"}
        try:
            result = store.set_stage(
                task_id,
                target,
                actor=_actor_on_the_card(services.principals, ctx, actor),
                test_id=test_id,
                reason=reason,
                commit=commit,
            )
        except (StageOrderError, MissingEvidenceError) as exc:
            return {"ok": False, "reason": str(exc)}
        return {"ok": result.ok, "reason": result.reason}

    @server.tool(name="kanban_show_card")
    def kanban_show_card(task_id: str) -> dict[str, Any]:
        """The card's self-contained instruction — the same text the board's
        own "Copy instruction" button copies, for a client with no clipboard
        of its own to read from."""
        from openstategraph.kanban_store import open_kanban_store

        store = open_kanban_store(services.store.root)
        try:
            card = store.read_card(task_id)
        except KeyError:
            return {"ok": False, "reason": f"no card {task_id!r}"}
        return _card_payload(store, card)

    @server.tool(name="kanban_list_cards")
    def kanban_list_cards(
        board: str = "",
        column: str = "",
        area: str = "",
        priority: str = "",
    ) -> dict[str, Any]:
        """Every card on this project's board, newest filing included — the
        one tool here that does not need a `task_id` you already know.

        Each row is the board's own row plus `column`, the board's four
        columns being `detected`, `needsYou`, `inProgress` and `resolved`.
        The column is **derived** from stage and kind rather than stored, so
        it cannot disagree with the card: a claimed card is `inProgress`
        whatever its kind, a card carrying evidence of red-then-green is
        `resolved`, and only an unattended one is placed by its kind. Take
        work from `detected`; `needsYou` is a judgement that is the owner's
        to make, not an agent's.

        Every filter is an exact, case-insensitive match, and they combine.
        A value outside the accepted set answers `ok: false` with an empty
        `cards` and a `reason` naming what is accepted — never an exception
        over the transport, and never a bare empty list, which would read as
        "the board is empty" and be a different, wrong fact.

        A board nothing has ever been filed to is `ok: true` and no cards.
        A patrol that ran and found nothing, and a patrol that never ran,
        look the same from here — ask `kanban_show_card` about a specific
        card if you need to tell them apart.
        """
        from openstategraph.kanban_store import (
            BOARD_AREAS,
            BOARD_COLUMNS,
            BOARD_PRIORITIES,
            column_for,
            open_kanban_store,
        )

        wanted: dict[str, tuple[str, tuple[str, ...] | None]] = {
            "column": (column, BOARD_COLUMNS),
            "area": (area, BOARD_AREAS),
            "priority": (priority, BOARD_PRIORITIES),
            # A board name is whatever a project called one, so there is no
            # accepted set to check against — an unmatched one is genuinely
            # "no cards there", not a typo this door can recognise.
            "board": (board, None),
        }
        resolved: dict[str, str] = {}
        for field, (value, accepted) in wanted.items():
            if not value.strip():
                continue
            folded = value.strip().casefold()
            if accepted is None:
                resolved[field] = folded
                continue
            match = [name for name in accepted if name.casefold() == folded]
            if not match:
                return {
                    "ok": False,
                    "cards": [],
                    "reason": (
                        f"no {field} {value!r} — accepted values are "
                        + ", ".join(accepted)
                    ),
                }
            resolved[field] = match[0].casefold()

        store = open_kanban_store(services.store.root)
        cards = []
        for card in store.list_cards():
            against = {
                "column": column_for(card),
                "area": card.area,
                "priority": card.priority,
                "board": card.board,
            }
            if any(against[field].casefold() != value for field, value in resolved.items()):
                continue
            cards.append(_card_payload(store, card))
        return {"ok": True, "cards": cards}

    @server.tool(name="kanban_triage")
    def kanban_triage(board: str = "workflows") -> dict[str, Any]:
        """Which card to pick up next, and why — `osg-agent-experience/25`.

        Read-only, and needs no principal: it answers from what is already
        on the board rather than writing anything. `kanban_list_cards`
        answers "what is here"; this answers "what first" — an unblocked
        card that other cards are waiting on outranks an unblocked card
        nobody is waiting on, which outranks anything still blocked. A
        `finished` card, and any `blocked_by` naming one, is spent and does
        not appear or does not block.

        Each row is `kanban_list_cards`' own row (`card_row` plus `column`)
        with two fields added: `rank` (1-indexed, this call's order) and
        `why_here`, the one sentence naming which rule placed it — "unblocks
        N cards" (or "unblocks N cards directly, M in all", when the chain
        below it runs deeper than one hop — `osg-agent-experience/66`),
        "<priority> priority, nothing waits on it", or "blocked by <ids>".
        Nothing is stored; call again after the board changes.
        """
        from openstategraph.kanban_store import open_kanban_store, triage

        store = open_kanban_store(services.store.root)
        folded = board.strip().casefold()
        cards = [
            card
            for card in store.list_cards()
            if not folded or card.board.casefold() == folded
        ]
        rows = [
            {**_card_payload(store, row.card), "rank": row.rank, "why_here": row.why_here}
            for row in triage(cards)
        ]
        return {"ok": True, "cards": rows}

    @server.tool(name="kanban_answer_card")
    def kanban_answer_card(
        task_id: str,
        answer: str,
        actor: str,
        ctx: _MCPContext | None = None,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """Record the decision on a Needs You card — `kanban-patrol/15`, and
        the last of `16`'s four tools.

        A Needs You card carries a **question** the patrol could not answer,
        and only a person may answer it. An agent that pulled the card and
        grilled the person calls this with what they said; it must never
        choose for them, which is the whole reason the card was in Needs You.

        The card then **returns to Detected**, carrying the decision — so the
        next `kanban_attend_card` picks it up with the judgement already
        made. It never reaches Resolved this way: `kanban-patrol/17`'s
        evidence gate is still the only road there.

        Written once. A blank answer, a card that was never in question, and
        a decision somebody already made are all `{"ok": false, "reason":
        ...}` — the same structured refusal every tool at this door uses.
        """
        from openstategraph.kanban_store import (
            MissingEvidenceError,
            StageOrderError,
            open_kanban_store,
        )

        store = open_kanban_store(services.store.root)
        who = _actor_on_the_card(services.principals, ctx, actor)
        try:
            result = store.answer_card(task_id, actor=who, answer=answer)
        except KeyError:
            return {"ok": False, "reason": f"no card {task_id!r}"}
        except (StageOrderError, MissingEvidenceError) as exc:
            return {"ok": False, "reason": str(exc)}
        return {"ok": result.ok, "reason": result.reason}

    @server.tool(name="kanban_file_card")
    def kanban_file_card(
        kind: str,
        title: str,
        story: str,
        done_when: str,
        priority: str,
        priority_reason: str,
        area: str = "backend",
        blocked_by: list[str] | None = None,
        agent_model: str = "",
        agent_effort: str = "",
        actor: str = "",
        ctx: _MCPContext | None = None,  # type: ignore[type-arg]
    ) -> dict[str, Any]:
        """File a card from a conversation — `osg-agent-experience/25`. The
        one kanban tool that *creates* a card; the others move one already on
        the board.

        The patrol files what it found in the run store, and a reader can go
        and look at the thread behind it. A card filed from a conversation has
        no such thread — the chat it came from is not something the next
        reader can open. So the brief is required, not defaulted: `story` (the
        plain-English want), `done_when` (the check that settles it) and
        `priority_reason` (why it is that urgent) are refused blank, because
        an empty string is exactly the shape the lost conversation would take.

        `kind` is `task`, `bug` or `grilling`. A `grilling` ends in a
        judgement, so it lands in **Needs You** and no agent may settle it;
        the other two land in **Detected**, which is where an agent pulls
        work from. `blocked_by` names other cards' ids: a bare name is
        resolved against the board and normalised to the full
        `<project_id>:<name>` id, one naming another project is refused, and
        one no card carries yet comes back in `unresolved_blockers` rather
        than being refused, because blocking on a card not yet filed is a real
        ordering (`osg-agent-experience/30`). `agent_model` /
        `agent_effort` are advisory — what to give a subagent that takes this
        card — and are left empty when nobody had an opinion, never filled
        with a default that would read as somebody's decision.

        The id is derived from the title (`<project_id>:idea-<slug>`), so two
        ideas given one title are a **refusal**, not a silent merge: rename
        one. Every refusal is `{"ok": false, "reason": ...}`, the same
        structured shape every tool at this door uses.
        """
        from openstategraph.kanban_store import (
            column_for,
            open_kanban_store,
            unresolved_blockers,
        )
        from openstategraph.project_identity import (
            ProjectIdentityError,
            project_id_for_board,
        )

        try:
            project_id = project_id_for_board()
        except (ProjectIdentityError, OSError) as exc:
            return {"ok": False, "reason": str(exc)}

        store = open_kanban_store(services.store.root)
        try:
            task_id = store.file_idea_card(
                project_id=project_id,
                kind=kind,
                title=title,
                story=story,
                done_when=done_when,
                priority=priority,
                priority_reason=priority_reason,
                area=area,
                actor=_actor_on_the_card(services.principals, ctx, actor),
                blocked_by=tuple(blocked_by or ()),
                agent_model=agent_model,
                agent_effort=agent_effort,
            )
        except ValueError as exc:
            return {"ok": False, "reason": str(exc)}
        card = store.read_card(task_id)
        return {
            "ok": True,
            "task_id": task_id,
            "column": column_for(card),
            # `osg-agent-experience/30`: the ids this card waits on that no
            # card carries. Not a refusal — blocking on a card not yet filed
            # is a real ordering — but never silent either, because that is
            # also the shape of a typo, and a stranded card never clears.
            "unresolved_blockers": list(unresolved_blockers(store, card)),
        }

    @server.tool(name="kanban_release_card")
    def kanban_release_card(
        task_id: str, threshold_seconds: int = _STALE_THRESHOLD_SECONDS
    ) -> dict[str, Any]:
        """Press the explicit Release on a card the system has already
        flagged stale — `kanban-patrol/19`'s "flag, never auto-release",
        made concrete: a human (or the agent acting on their word) can only
        release a card `flagged_stale` already named, never an arbitrary
        active one. Refused (`ok: false`) the same structured way a lost
        attend or a skipped stage already is — never a stack trace.

        A successful release resets the row to a fresh, unattended state —
        stage, actor, heartbeat, and every evidence field — so the next
        attend starts clean, with nothing left over from the abandoned one.
        """
        from openstategraph.kanban_store import open_kanban_store

        result = open_kanban_store(services.store.root).release_card(
            task_id, threshold_seconds=threshold_seconds
        )
        return {"ok": result.ok, "reason": result.reason}

    if allow_runs:

        @server.tool(name="run_workflow")
        def run_workflow(
            question: str,
            slug: str | None = None,
            document: Any = None,
            recursion_limit: int | None = None,
            model: str | None = None,
            session_id: str | None = None,
        ) -> dict[str, Any]:
            """Run a workflow once, synchronously, and return its answer.

            Pass either a hosted `slug` or an inline `document`. This is the
            only tool that reaches a model; it uses the SERVER's credentials —
            never send keys over MCP. `recursion_limit` counts supersteps, not
            iterations, and is bounded server-side.

            **This door answers to an audience, and the audience is the
            deployment's, not yours.** By default you get a customer's payload:
            the answer, `decisions`, `routes`, `outputs`, `attempts` and the
            diagram — and no `warnings` key at all, because authoring
            diagnostics name node ids and unbound tool types. A server run with
            `OPENSTATEGRAPH_AUDIENCE=developer` adds `warnings` and
            `suggestion`. There is deliberately no `audience` argument here:
            the client filling these fields is a model, and a boundary a model
            can name is not a boundary (`the-boundary-nobody-checked/08`).

            **`session_id` names the sitting this run belongs to**, and is for
            one job: if you are working a card on this project's patrol board,
            pass `card:<task_id>`. A run marked that way is skipped by the
            next patrol, so the board never files a card about the work you
            did on the last one (`kanban-patrol/08`). Leave it unset
            otherwise — it is not an identity and nothing authenticates it.
            """
            return runs.run(
                question,
                slug,
                document,
                recursion_limit,
                model,
                session_id,
                audience=deployment_audience(),
            )

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
