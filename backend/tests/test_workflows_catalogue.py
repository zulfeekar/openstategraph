"""`Workflows` — the catalogue. Scale-and-adopt ticket 02.

Three claims, and each one is a claim about *cost* or about *blast radius*
rather than about a return value:

1. **Listing never compiles.** `load_workflow` imports LangGraph, LangChain and
   a provider SDK, builds a model, executes every `tools/*.py` in the package
   and assembles a graph. Twenty workflows listed that way is twenty compiles
   to draw a picker. So `list()` reads `workflow.json` and nothing else, and
   the test that pins it is not a stopwatch — it asserts the compiler was never
   called, which is the fact a stopwatch is a proxy for.
2. **One broken package does not break the list.** A directory whose
   `workflow.json` is unparseable appears *as a row carrying its error*, not as
   a silent omission and not as an exception. Omission is what the HTTP
   listing already does, deliberately (a customer surface must not show
   rubble); a developer's catalogue is the opposite case — the whole reason you
   ask for a list is to find out what you have.
3. **Four layers of precedence, pinned pairwise.** convention < config file <
   environment < explicit argument. Pairwise rather than one four-way test:
   a single test with all four set passes even if two middle layers are
   inverted with respect to each other.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openstategraph import Workflows, WorkflowInfo
from openstategraph.config_file import CONFIG_ENV_VAR, reset_active_config
from openstategraph.errors import InvalidPackageName, PackageNotFound
from openstategraph.workflows_root import WORKFLOWS_ROOT_ENV
import openstategraph.workflows_root as workflows_root_module


@pytest.fixture(autouse=True)
def _no_ambient_configuration(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Neither the developer's environment nor a memoised config may leak in."""
    monkeypatch.delenv(WORKFLOWS_ROOT_ENV, raising=False)
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    reset_active_config()
    yield
    reset_active_config()


def package(root: Path, slug: str, *, published: bool | None = None, hidden: bool = False) -> Path:
    """One minimal, valid workflow package."""
    directory = root / slug
    directory.mkdir(parents=True)
    envelope: dict[str, object] = {
        "version": 1,
        "name": slug.replace("-", " ").title(),
        "savedAt": f"2026-08-10T00:00:0{len(slug) % 10}Z",
        "document": {"version": 2, "nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"id": "e"}]},
    }
    if published is not None:
        envelope["published"] = published
    if hidden:
        envelope["hidden"] = True
    (directory / "workflow.json").write_text(json.dumps(envelope))
    return directory


def broken(root: Path, slug: str = "half-written") -> Path:
    """A package whose `workflow.json` is not JSON at all — the deliberate
    rubble every list test carries, because "one bad package" is not a
    hypothetical: it is a half-finished edit, a merge conflict marker, or a
    file a generator truncated."""
    directory = root / slug
    directory.mkdir(parents=True)
    (directory / "workflow.json").write_text("{ this is not json")
    return directory


class TestListingIsCheap:
    def test_listing_never_compiles_anything(self, tmp_path, monkeypatch) -> None:
        """The claim in full: not "it is fast" but "the compiler is not
        reached". Twenty packages, and `load_workflow` — the only thing that
        imports the runtime — is replaced by a bomb."""
        for index in range(20):
            package(tmp_path, f"flow-{index:02d}")

        import openstategraph.catalogue as catalogue

        def explode(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("list() compiled a workflow")

        monkeypatch.setattr(catalogue, "load_workflow", explode)

        rows = Workflows(tmp_path).list()

        assert len(rows) == 20
        assert all(isinstance(row, WorkflowInfo) for row in rows)

    def test_listing_does_not_import_the_runtime(self, tmp_path) -> None:
        """Import cost is part of the contract (`loader.py`'s docstring), and
        a catalogue is the thing a service builds at startup. Run in a
        subprocess because this suite has long since imported langgraph."""
        import subprocess
        import sys

        package(tmp_path, "one")
        script = (
            "import sys;"
            "from openstategraph import Workflows;"
            f"rows = Workflows({str(tmp_path)!r}).list();"
            "assert [r.slug for r in rows] == ['one'], rows;"
            "assert 'langgraph' not in sys.modules, 'listing imported langgraph';"
            "assert 'langchain_core' not in sys.modules, 'listing imported langchain_core'"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1]), "PATH": "/usr/bin:/bin"},
        )
        assert result.returncode == 0, result.stderr


class TestOneBrokenPackage:
    def test_it_appears_as_a_row_carrying_its_error(self, tmp_path) -> None:
        package(tmp_path, "healthy")
        broken(tmp_path)

        rows = {row.slug: row for row in Workflows(tmp_path).list()}

        assert set(rows) == {"healthy", "half-written"}
        assert rows["healthy"].error == ""
        assert rows["half-written"].error, "a broken package must say why"
        assert "json" in rows["half-written"].error.lower()

    def test_it_never_reaches_the_published_surface(self, tmp_path) -> None:
        """`published()` mirrors `?surface=chat`. Rubble is not a product."""
        package(tmp_path, "healthy", published=True)
        broken(tmp_path)

        assert [row.slug for row in Workflows(tmp_path).published()] == ["healthy"]

    def test_loading_the_broken_one_still_raises(self, tmp_path) -> None:
        """Listing degrades; loading does not. A caller who asked for THIS
        package must not get a half-graph."""
        broken(tmp_path)

        with pytest.raises(Exception):
            Workflows(tmp_path).load("half-written")


class TestWhatTheListSays:
    def test_counts_and_lifecycle_come_from_the_envelope(self, tmp_path) -> None:
        package(tmp_path, "drafted", published=False)

        row = Workflows(tmp_path).list()[0]

        assert (row.slug, row.name, row.published) == ("drafted", "Drafted", False)
        assert (row.node_count, row.edge_count) == (2, 1)

    def test_a_missing_published_field_reads_as_published(self, tmp_path) -> None:
        """Back-compat with every workflow that predates the lifecycle."""
        package(tmp_path, "ancient")

        assert [row.slug for row in Workflows(tmp_path).published()] == ["ancient"]

    def test_hidden_workflows_are_in_neither_list(self, tmp_path) -> None:
        package(tmp_path, "concierge", published=True, hidden=True)
        package(tmp_path, "visible", published=True)

        catalog = Workflows(tmp_path)

        assert [row.slug for row in catalog.list()] == ["visible"]
        assert [row.slug for row in catalog.published()] == ["visible"]

    def test_a_missing_root_lists_nothing_rather_than_raising(self, tmp_path) -> None:
        assert Workflows(tmp_path / "nope").list() == []


class TestLoadingOne:
    def test_it_returns_the_existing_compiled_workflow(self, tmp_path, monkeypatch) -> None:
        """`load()` is `load_workflow` with the root already known — one
        implementation, not a second wiring path."""
        directory = package(tmp_path, "billing")
        seen: dict[str, object] = {}

        import openstategraph.catalogue as catalogue

        def fake(package_dir, **kwargs):  # noqa: ANN001, ANN003
            seen["package_dir"] = package_dir
            seen.update(kwargs)
            return "compiled"

        monkeypatch.setattr(catalogue, "load_workflow", fake)

        assert Workflows(tmp_path).load("billing") == "compiled"
        assert seen["package_dir"] == directory

    def test_catalogue_defaults_apply_to_every_load(self, tmp_path, monkeypatch) -> None:
        package(tmp_path, "billing")
        seen: dict[str, object] = {}

        import openstategraph.catalogue as catalogue

        monkeypatch.setattr(
            catalogue, "load_workflow", lambda package_dir, **kw: seen.update(kw) or "ok"
        )

        Workflows(tmp_path, model="anthropic:claude-x", trace_file="/tmp/t.jsonl").load("billing")

        assert seen["model"] == "anthropic:claude-x"
        assert seen["trace_file"] == "/tmp/t.jsonl"

    def test_a_per_call_argument_overrides_the_default(self, tmp_path, monkeypatch) -> None:
        package(tmp_path, "billing")
        seen: dict[str, object] = {}

        import openstategraph.catalogue as catalogue

        monkeypatch.setattr(
            catalogue, "load_workflow", lambda package_dir, **kw: seen.update(kw) or "ok"
        )

        Workflows(tmp_path, model="anthropic:claude-x").load("billing", model="ollama:local")

        assert seen["model"] == "ollama:local"

    def test_capability_mappings_merge_rather_than_replace(self, tmp_path, monkeypatch) -> None:
        """A catalogue-wide stub plus one per-call substitution is the case
        that made merging right: replacing would silently drop the shared one."""
        package(tmp_path, "billing")
        seen: dict[str, object] = {}

        import openstategraph.catalogue as catalogue

        monkeypatch.setattr(
            catalogue, "load_workflow", lambda package_dir, **kw: seen.update(kw) or "ok"
        )

        Workflows(tmp_path, tools={"tool.a": 1, "tool.b": 2}).load(
            "billing", tools={"tool.b": 99}
        )

        assert seen["tools"] == {"tool.a": 1, "tool.b": 99}

    def test_an_unknown_slug_raises_the_public_error(self, tmp_path) -> None:
        with pytest.raises(PackageNotFound):
            Workflows(tmp_path).load("missing")

    def test_a_slug_that_escapes_the_root_is_refused(self, tmp_path) -> None:
        """The one thing standing between "load a workflow" and "load anything
        this process can reach" — and it must raise a *public* error, not the
        Tier 3 one the store uses internally."""
        with pytest.raises(InvalidPackageName):
            Workflows(tmp_path).load("../secrets")


class TestTheRootIsResolvedInFourLayers:
    """convention < config file < environment < explicit argument, pinned by
    adjacent pairs. `checkout_root` is forced to None so these tests describe
    an *installed* process rather than this repository."""

    @pytest.fixture(autouse=True)
    def _installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(workflows_root_module, "checkout_root", lambda: None)

    def write_config(self, directory: Path, workflows_dir: str) -> Path:
        path = directory / "openstategraph.yaml"
        path.write_text(f"version: 1\nworkflows_dir: {workflows_dir}\n")
        return path

    def test_convention_is_workflows_under_the_cwd(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)

        assert Workflows().root == (tmp_path / "workflows").resolve()

    def test_the_config_file_beats_the_convention(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        self.write_config(tmp_path, "flows")

        assert Workflows().root == (tmp_path / "flows").resolve()

    def test_a_relative_config_value_is_relative_to_the_config_file(
        self, tmp_path, monkeypatch
    ) -> None:
        """The file is committed and read from wherever the process happens to
        stand; resolving against the cwd would make one committed line mean a
        different directory per developer."""
        project = tmp_path / "project"
        elsewhere = tmp_path / "elsewhere"
        project.mkdir()
        elsewhere.mkdir()
        monkeypatch.setenv(CONFIG_ENV_VAR, str(self.write_config(project, "flows")))
        monkeypatch.chdir(elsewhere)

        assert Workflows().root == (project / "flows").resolve()

    def test_the_environment_beats_the_config_file(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        self.write_config(tmp_path, "flows")
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "from-env"))

        assert Workflows().root == (tmp_path / "from-env").resolve()

    def test_the_explicit_argument_beats_the_environment(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv(WORKFLOWS_ROOT_ENV, str(tmp_path / "from-env"))

        assert Workflows(tmp_path / "explicit").root == (tmp_path / "explicit").resolve()

    def test_the_root_is_frozen_at_construction(self, tmp_path, monkeypatch) -> None:
        """A catalogue that answers `.list()` differently after a `chdir` is a
        bug, not a feature: the object IS the answer to "which directory"."""
        monkeypatch.chdir(tmp_path)
        catalog = Workflows()
        (tmp_path / "workflows").mkdir()
        monkeypatch.chdir(tmp_path.parent)

        assert catalog.root == (tmp_path / "workflows").resolve()


class TestTheSurfaceStaysSmall:
    def test_four_public_members_and_no_module_level_setter(self) -> None:
        """The no-god-class ceiling, and the reason there is no
        `set_workflows_root()`: process-wide mutable state is how two callers
        in one process end up disagreeing about which directory they read."""
        import openstategraph.catalogue as catalogue

        public = {name for name in vars(Workflows) if not name.startswith("_")}

        assert public == {"root", "list", "published", "load"}
        assert not [name for name in dir(catalogue) if name.startswith("set_")]


class TestLoadWorkflowIsUnchanged:
    def test_the_single_package_case_still_takes_a_path(self, tmp_path, monkeypatch) -> None:
        """The catalogue is additive. `load_workflow(path)` is what every
        existing adopter calls, and it keeps taking a package directory."""
        import inspect

        from openstategraph import load_workflow

        signature = inspect.signature(load_workflow)

        assert list(signature.parameters)[0] == "package_dir"
        assert signature.parameters["package_dir"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
