"""`Workflows` — a directory of workflow packages, set once. Ticket 02.

**Tier 1, semver-public.**

`load_workflow(path)` is the right shape for one package and the wrong shape
for twenty: it takes a path, so a service with a directory of workflows
restates the root at every call site, and there is no way to ask *what is in
there* without compiling. So:

    from openstategraph import Workflows

    catalog = Workflows("./workflows", model="anthropic:claude-sonnet-4-5")

    catalog.list()          # every non-hidden package — cheap, never compiles
    catalog.published()     # what a customer chat shows (mirrors ?surface=chat)
    workflow = catalog.load("billing")     # compiles THIS one

Four public members, and that is the whole class. `Workflows` is a *lookup*,
not a runtime: it holds a root and some defaults, and `load()` returns the same
`CompiledWorkflow` `load_workflow` has always returned. Anything that wants to
grow here — a run method, a cache, a registry — belongs on the object it is
about, not on the catalogue (CLAUDE.md, no god classes).

**Listing never compiles, and that is a design constraint rather than an
optimisation.** `load()` imports LangGraph and LangChain, builds a model,
executes every `tools/*.py` in the package and assembles a graph. Doing that
twenty times to draw a picker is not slow, it is wrong: it needs API keys, it
runs third-party code, and one broken package takes the whole list with it. So
`list()` reads `workflow.json` and stops — the same single traversal the HTTP
listing uses, through `WorkflowStore.list`, with no second implementation.

**One broken package is a row, not an exception and not a silence.** A
directory whose `workflow.json` will not parse comes back with `error` set and
`published` false. The HTTP listing still omits it, deliberately: a customer
surface must not show rubble, and the row would be unopenable. A developer
asking "what have I got" is the opposite case — a silent omission sends them
looking in the wrong place.

**No module-level setter.** There is no `set_workflows_root()`, and there will
not be: process-wide mutable state is how two callers in one process come to
disagree about which directory they read, with nothing in either call to
explain the difference. The root comes from four layers instead — convention <
config file < environment < explicit argument — resolved by
`openstategraph.workflows_root` and frozen onto this object at construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openstategraph.errors import InvalidPackageName
from openstategraph.loader import load_workflow

if TYPE_CHECKING:
    # Same rule as `loader.py`: `import openstategraph` must not drag in the
    # runtime, and listing a directory must not either.
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.store.base import BaseStore

    from openstategraph.api.workflow_store import WorkflowStore
    from openstategraph.loader import CompiledWorkflow


@dataclass(frozen=True)
class WorkflowInfo:
    """One row of a catalogue listing — what `workflow.json` says about itself.

    Everything here is read from the envelope, so producing it costs one file
    read per package and never touches the compiler. That is why there is no
    `warnings` field: unresolved capabilities are a fact about a *compiled*
    workflow, and answering it here would mean compiling.
    """

    slug: str
    name: str
    #: Draft → publish lifecycle. A missing field in the envelope reads as
    #: published (back-compat); a broken package is never published.
    published: bool = True
    node_count: int = 0
    edge_count: int = 0
    #: The envelope's `savedAt`, verbatim. Empty for a package that has no
    #: envelope or could not be read.
    saved_at: str = ""
    #: Why this package could not be read, or empty. `if row.error:` is the
    #: whole check.
    error: str = ""


#: `list` is a *method* on the class below, which shadows the builtin
#: everywhere inside its body. The return type is therefore spelled once here,
#: at module scope, where `list` still means what it says.
_Listing = list[WorkflowInfo]


class Workflows:
    """A directory of workflow packages: list them cheaply, load one properly."""

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        # The same collaborators `load_workflow` takes, with the same meanings
        # and the same `None` defaults — because this IS `load_workflow`, with
        # the root already known. A second spelling of any of these would be a
        # second wiring path, and the two would drift.
        model: Any = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        store: BaseStore | None = None,
        tools: dict[str, Any] | None = None,
        functions: dict[str, Any] | None = None,
        middleware: dict[str, Any] | None = None,
        knowledge_dir: str | Path | None = None,
        trace_file: str | Path | None = None,
    ) -> None:
        """`root` is the directory holding `<slug>/workflow.json`.

        Omit it and it is resolved from the other three layers — the config
        file's `workflows_dir:`, `OPENSTATEGRAPH_WORKFLOWS_ROOT`, then
        `./workflows` (or this checkout's, in-tree). Resolved **once**, here: an
        object that answers `.list()` differently after a `chdir` is a bug, not
        a feature, because the object *is* the answer to "which directory".

        Every other argument is a default for `load()` and means exactly what
        it means on `load_workflow`, which is where they are documented.
        """
        from openstategraph.workflows_root import workflows_root

        self._root = Path(root).expanduser().resolve() if root is not None else workflows_root()
        self._defaults: dict[str, Any] = {
            "model": model,
            "checkpointer": checkpointer,
            "store": store,
            "knowledge_dir": knowledge_dir,
            "trace_file": trace_file,
        }
        # Copied, not aliased: a caller's dict must not become live state that
        # a later mutation of theirs changes mid-run — the same rule
        # `WorkflowServices` already applies to the same three mappings.
        self._mappings: dict[str, dict[str, Any]] = {
            "tools": dict(tools or {}),
            "functions": dict(functions or {}),
            "middleware": dict(middleware or {}),
        }

    @property
    def root(self) -> Path:
        """The directory this catalogue reads. Absolute, and fixed for its life.

        Where this process *writes* is a separate question with a separate
        answer — `openstategraph.state_dir` — so pointing a catalogue at a
        directory never puts anything in it.
        """
        return self._root

    def list(self) -> _Listing:
        """Every non-hidden package under `root`, newest save first.

        Reads one `workflow.json` per package and nothing else. A package that
        will not parse is a row with `error` set rather than an omission or an
        exception. A `root` that does not exist is an empty list, not a
        `FileNotFoundError`: "you have no workflows yet" is a state, not a
        failure.
        """
        return [
            WorkflowInfo(
                slug=summary.slug,
                name=summary.name,
                published=summary.published,
                node_count=summary.node_count,
                edge_count=summary.edge_count,
                saved_at=summary.saved_at,
                error=summary.error,
            )
            for summary in self._store().list(include_broken=True)
        ]

    def published(self) -> _Listing:
        """Only the published, readable ones — what a customer chat shows.

        Mirrors the HTTP listing's `?surface=chat` exactly, and is filtered
        from `list()` rather than re-queried so the two can never disagree
        about what "published" means.
        """
        return [row for row in self.list() if row.published and not row.error]

    def load(
        self,
        slug: str,
        *,
        model: Any = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        store: BaseStore | None = None,
        tools: dict[str, Any] | None = None,
        functions: dict[str, Any] | None = None,
        middleware: dict[str, Any] | None = None,
        knowledge_dir: str | Path | None = None,
        trace_file: str | Path | None = None,
    ) -> CompiledWorkflow:
        """Compile one package and return the usual `CompiledWorkflow`.

        This is `load_workflow(root / slug, **defaults)` — the same function,
        the same `WorkflowServices` assembly, the same value object. There is
        no second wiring path, so a capability that resolves under
        `load_workflow` resolves here and a bug fixed in one is fixed in both.

        Every keyword overrides this catalogue's default for this call.
        `tools`, `functions` and `middleware` **merge** over the catalogue's
        (per-call entries win by key), because the case that decided it is a
        catalogue-wide stub plus one substitution: replacing wholesale would
        silently drop the shared one. Everything else replaces, because a model
        or a checkpointer has no meaningful union.

        A slug that is not a valid package name — or one that tries to leave
        the root — raises `InvalidPackageName`; a slug with no package raises
        `PackageNotFound`. Both are Tier 1 errors, and both are what
        `load_workflow` would have raised for the same input.
        """
        overrides = {
            "model": model,
            "checkpointer": checkpointer,
            "store": store,
            "knowledge_dir": knowledge_dir,
            "trace_file": trace_file,
        }
        arguments = {
            key: value if value is not None else self._defaults[key]
            for key, value in overrides.items()
        }
        for key, per_call in (
            ("tools", tools),
            ("functions", functions),
            ("middleware", middleware),
        ):
            merged = dict(self._mappings[key])
            merged.update(per_call or {})
            arguments[key] = merged or None
        return load_workflow(self._directory_for(slug), **arguments)

    def _directory_for(self, slug: str) -> Path:
        """The package directory, or a **public** error.

        `WorkflowStore.directory_for` is what stands between "load a workflow"
        and "load any directory this process can reach", so it is reused rather
        than re-derived. Its `InvalidSlugError` is Tier 3, though, and a Tier 1
        method must not raise a class an adopter cannot import — so it is
        translated to `InvalidPackageName`, which `load_workflow` already
        raises for the neighbouring case.
        """
        from openstategraph.api.workflow_store import InvalidSlugError

        try:
            return self._store().directory_for(slug)
        except InvalidSlugError as exc:
            raise InvalidPackageName(str(exc)) from exc

    def _store(self) -> WorkflowStore:
        """The file-backed store, built per call and deliberately not cached.

        It holds nothing but a root — the expensive collaborators
        (checkpointer, memory store, registries) live on `WorkflowServices`,
        which `load_workflow` builds and closes per load. Caching a store here
        would buy nothing and would make this object hold a handle on a
        directory it may never be asked about. Imported lazily so that
        listing, like importing, stays free of the `api` package.
        """
        from openstategraph.api.workflow_store import WorkflowStore

        return WorkflowStore(root=self._root)


__all__ = ["WorkflowInfo", "Workflows"]
