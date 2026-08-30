"""What a `NodeRuntime` collaborates with, and what one package contributes.

Carved out of `compile/node_runtime.py` (`docs-and-gaps/03`), unchanged. Two
frozen dataclasses and the tool-registry alias they are both typed against.

**Why they are a module and not part of the runtime's own file.** These are
the runtime's *collaborators* — the parameter object ticket 72 introduced so
that a new capability lands in one place rather than widening a keyword
constructor at three call sites. A collaborator declared inside the class that
consumes it is a collaborator only one file can name without importing the
engine, and the mount family has to construct a `RuntimeServices` for the child
runtime it builds. Declaring them here is what lets a family module do that
without importing `node_runtime` back.

`NodeCapabilities` in `openstategraph/abc/node_family.py` is the published
façade over `RuntimeServices` and stays where it is: that one is a stability
contract for plugins, and this one is a compiler internal with no such promise.
Moving this file must not be read as widening that seam — it narrows nothing
and publishes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from openstategraph.memory import MemorySettings

if TYPE_CHECKING:
    # Types only, the pattern `loader.py` established: `BaseStore` is the
    # memory store, never the filesystem `WorkflowStore` (ticket 12).
    from langgraph.store.base import BaseStore


ToolRegistry = dict[str, Any]


#: The bundled example package whose tools the built-in layer republishes.
CHINOOK_SLUG = "chinook-assistant"


def chinook_tool_registry() -> ToolRegistry:
    """The Chinook package's tools, keyed by node type, read from disk.

    **This used to be `from tools.chinook import ...`, and that import only
    ever worked under pytest** (`every-workflow-green/43`). `pytest.ini` puts
    `workflows/chinook-assistant` on `pythonpath`, so a bare top-level `tools`
    package exists in the test process and nowhere else; every process that
    actually serves a run — the API server, the CLI, an installed wheel — got
    `ModuleNotFoundError: No module named 'tools'`, which
    `api/registries.py` catches and logs at DEBUG. The three `tool.chinook-*`
    node types were therefore absent from the built-in layer of every real
    process, silently, with a green suite behind them. A live run of
    `chinook-assistant` that carried no `workflow_slug` — the shape `/api/runs`
    explicitly supports, *"omit `workflow_slug` to run the document with the
    default tools"* — reached its grader with all three capabilities missing
    and was refused without a model call.

    A slug-scoped run was never affected: `build_tool_registry` adds the
    package's own `tools/` through `discover_tool_registry`, which loads by
    file location and needs no `sys.path` entry. So the repair is to reach the
    shipped package the same way the slug-scoped layer already does, rather
    than through an import path one test runner happens to provide. The
    built-in layer and the workflow-local layer now resolve the same files by
    the same mechanism, which is why they can no longer disagree.

    Empty is not a possible answer: outside a checkout there is no bundled
    package, and this raises so `api/registries.py`'s existing handler names it
    — a registry that silently publishes nothing is exactly what went wrong.
    """
    from openstategraph.api.capability_discovery import discover_tool_registry
    from openstategraph.workflows_root import workflows_root

    root = workflows_root()
    package = root / CHINOOK_SLUG
    if not (package / "workflow.json").is_file():
        raise FileNotFoundError(
            f"No bundled {CHINOOK_SLUG!r} package under {root} — set "
            "OPENSTATEGRAPH_WORKFLOWS_ROOT to the directory holding your "
            f"{CHINOOK_SLUG}/ package if a document binds its tools."
        )
    return {
        node_type: tool
        for node_type, tool in discover_tool_registry(package, CHINOOK_SLUG).items()
        # `discover_tool_registry` keys every tool twice — by qualified id
        # (`chinook-assistant/tools.ExecuteSqlTool`) and by its declared
        # `node_type`. Only the second belongs in a layer published to
        # documents that are not this package's.
        if node_type.startswith("tool.")
    }


@dataclass(frozen=True)
class PackageAssets:
    """Everything one workflow package contributes to a runtime.

    The child-subgraph contract (ticket 67, completed properly after the
    user found the gap live): a routed child must run with its OWN package's
    assets — tools, functions, skills AND middleware. The first version
    loaded only tools+functions; skills stayed inherited from the parent, so
    the Architect routed through the concierge ran without its interview
    skill or document grammar and composed blind.
    """

    tools: ToolRegistry
    functions: dict[str, Any]
    skills_context: str = ""
    workflow_middleware: dict[str, Any] | None = None
    #: The package directory whose `knowledge/` powers ambient knowledge
    #: seeking (see `NodeRuntime.knowledge_package_dir`). A child gets ITS
    #: OWN package's knowledge, never the parent's — the same isolation as
    #: skills after the ticket-67 lesson.
    knowledge_dir: Any = None
    #: The package directory whose `skills/*.md` a child's agents disclose
    #: progressively. Same isolation, same reason: a routed child discloses
    #: its own package's skills or none at all.
    skills_dir: Any = None


@dataclass(frozen=True)
class RuntimeServices:
    """Everything a `NodeRuntime` collaborates with, as one named object.

    Ticket 72's parameter-object fix: the keyword constructor had grown to
    nine parameters and every new capability (store, skills, workflow
    middleware...) widened it again at two production call sites and the
    child-runtime clone. New capabilities now land HERE once; `NodeRuntime`'s
    keyword form remains as the test-facing compatibility surface.
    """

    model: Any = None
    #: Non-optional, with an empty default. `NodeRuntime` normalises `None`
    #: to `{}` on the way in, so the stored object never holds one — and
    #: while these were declared optional, every read inside the class had to
    #: be written as though it might be (reviews-2026-08-14 ticket 07).
    #: `document_loader`, `package_loader` and `memory_store` stay optional
    #: because for those, absent genuinely means something: no subgraph
    #: resolution, no memory.
    tools: ToolRegistry = field(default_factory=dict)
    functions: dict[str, Any] = field(default_factory=dict)
    document_loader: Callable[[str], dict[str, Any]] | None = None
    package_loader: Callable[[str], 'PackageAssets'] | None = None
    #: Long-term memory — LangGraph's `BaseStore`, what `compile(store=)` is
    #: given and what the prebuilt `save_memory`/`search_memory` tools write
    #: to. **Named `memory_store`, and typed, on purpose** (install-experience
    #: ticket 12): it was `store: Any`, one word from `WorkflowServices.store`
    #: (the filesystem `WorkflowStore`, packages on disk), and the statement
    #: `store = services.store` appeared verbatim in this file and in
    #: `mcp_server.py` meaning opposite objects. `Any` made swapping them a
    #: one-token edit mypy accepted, the downstream guard is a bare
    #: `is not None`, and the two classes share exactly one method name
    #: (`delete`, different arity) — so the failure surfaced at run time,
    #: inside LangGraph, naming no code of ours.
    memory_store: 'BaseStore | None' = None
    #: What the document's `settings.memory` declared (ticket 03). The
    #: default is every scope enabled, so a document with no block behaves
    #: exactly as it did before the block existed.
    memory: MemorySettings = field(default_factory=MemorySettings)
    skills_context: str = ""
    workflow_middleware: dict[str, Any] = field(default_factory=dict)
    #: The open workflow's package directory, for ambient knowledge seeking
    #: (a non-empty `knowledge/` under it auto-binds the lookup tool).
    knowledge_package_dir: Any = None
    #: The open workflow's package directory, for **progressive skill
    #: disclosure** (`launch-readiness/111`). The same value as
    #: `knowledge_package_dir` today and deliberately a separate field: that
    #: one is the second brain and carries an override
    #: (`knowledge_dir_override`) that must never redirect where skills are
    #: read from, and two capabilities sharing one field is how an override
    #: aimed at one silently moves the other.
    skills_package_dir: Any = None
    #: `load_workflow(knowledge_dir=...)`'s explicit override — the directory
    #: of topic files itself, replacing the `<package>/knowledge` convention.
    #: Deliberately NOT inherited by a child subgraph: a routed child seeks
    #: its own second brain (ticket 67's isolation lesson), and an override
    #: aimed at the parent must not silently redirect the child's.
    knowledge_dir_override: Any = None
    max_attempts: int = 3
    #: The editor-advisor tool catalogue, or "" for a normal run. See
    #: `advisor_context` — one field rather than a `bool` + the text it needs,
    #: because a flag and its data can disagree and this pair never should:
    #: an advisor with nothing to suggest is not an advisor.
    advisor_catalog: str = ""



__all__ = ["CHINOOK_SLUG", "PackageAssets", "RuntimeServices", "ToolRegistry", "chinook_tool_registry"]
