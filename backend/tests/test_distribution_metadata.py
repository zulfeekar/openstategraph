"""The install footprint, pinned as metadata (framework-packaging §3.1).

The finding this file guards is not a bug in the code — the code was already
lazy. It was a bug in the *promise*: `pip install` of this distribution
resolved 79 distributions, of which 43 were things a `load_workflow` consumer
may never touch, including a web server, an MCP SDK, three provider SDKs and
(via deepagents) the Google GenAI SDK. A sceptical adopter reads
`requires_dist` before the README.

So the lean core is asserted exactly, not approximately: this test fails the
moment someone adds a dependency in the wrong table, which is the only moment
at which the mistake is cheap.

`importlib.metadata` is preferred when the distribution is installed; when it
is not (the repo's own suite runs from `PYTHONPATH=backend`, uninstalled)
`pyproject.toml` is read directly. Both are the same claim — the second is the
source the first is built from.
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

DISTRIBUTION = "openstategraph"

#: The four, and only the four.
LEAN_CORE = {"langgraph", "langchain", "langchain-core", "pydantic"}

#: Every name that must NOT be an unconditional requirement, with the extra
#: that owns it. The mapping is the documentation: a reader of this test learns
#: the install story without opening pyproject.toml.
EXTRACTED = {
    "langchain-anthropic": "anthropic",
    "langchain-openai": "openai",
    "langchain-ollama": "ollama",
    "deepagents": "deep",
    "langgraph-checkpoint-sqlite": "sqlite",
    "fastapi": "server",
    "uvicorn": "server",
    "python-multipart": "server",
    "mcp": "mcp",
}


def normalize(name: str) -> str:
    """PEP 503 name normalization — `langchain_core` and `langchain-core` are one."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def requirement_name(requirement: str) -> str:
    """The distribution a requirement string names, dropping version and extras."""
    return normalize(re.split(r"[\s\[<>=!~;(]", requirement.strip(), maxsplit=1)[0])


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text())


class TestLeanCore:
    def test_the_unconditional_dependencies_are_exactly_the_lean_core(self, pyproject) -> None:
        declared = {requirement_name(r) for r in pyproject["project"]["dependencies"]}

        assert declared == LEAN_CORE

    def test_no_extracted_dependency_is_unconditional(self, pyproject) -> None:
        declared = {requirement_name(r) for r in pyproject["project"]["dependencies"]}

        assert declared & set(EXTRACTED) == set()

    def test_every_extracted_dependency_lives_in_the_extra_that_claims_it(
        self, pyproject
    ) -> None:
        extras = pyproject["project"]["optional-dependencies"]
        placement = {
            requirement_name(r): extra
            for extra, requirements in extras.items()
            if extra != "all"
            for r in requirements
        }

        assert {name: placement.get(name) for name in EXTRACTED} == EXTRACTED

    def test_all_names_every_extra(self, pyproject) -> None:
        """`[all]` is the upgrade path for anyone on today's behaviour — if it
        misses an extra, they lose a capability on upgrade and never see why."""
        extras = pyproject["project"]["optional-dependencies"]
        named = set(re.findall(r"\[([^\]]+)\]", " ".join(extras["all"]))[0].split(","))

        assert named == set(extras) - {"all", "dev"}


class TestDistributionIdentity:
    def test_the_distribution_is_named_for_the_framework_not_for_a_backend(
        self, pyproject
    ) -> None:
        assert pyproject["project"]["name"] == DISTRIBUTION

    def test_a_build_backend_is_declared(self, pyproject) -> None:
        """Without `[build-system]`, the wheel is whatever setuptools' legacy
        fallback happens to produce today — not reproducible."""
        assert pyproject["build-system"]["build-backend"] == "hatchling.build"

    def test_the_wheel_carries_a_license_readme_and_type_marker(self, pyproject) -> None:
        backend = PYPROJECT.parent
        project = pyproject["project"]

        assert project["license"] == "MIT"
        assert project["license-files"] == ["LICENSE"]
        assert (backend / "LICENSE").is_file()
        assert (backend / project["readme"]).is_file()
        # PEP 561: without this file, a thoroughly annotated package is `Any`
        # to every adopter on mypy or pyright.
        assert (backend / "openstategraph" / "py.typed").is_file()

    def test_the_console_script_is_declared_and_resolvable(self, pyproject) -> None:
        """`openstategraph` on the PATH is what ticket 08 exists to add, and a
        typo in this one line is invisible until someone installs the wheel."""
        scripts = pyproject["project"]["scripts"]

        assert scripts == {"openstategraph": "openstategraph.cli:main"}
        module, _, attribute = scripts["openstategraph"].partition(":")
        assert callable(getattr(__import__(module, fromlist=[attribute]), attribute))

    def test_the_cli_costs_no_dependency(self, pyproject) -> None:
        """argparse, deliberately. A project arguing for a four-package floor
        cannot then spend two of them on `click` and `rich`."""
        source = (PYPROJECT.parent / "openstategraph" / "cli.py").read_text()
        imported = {
            line.split()[1].split(".")[0]
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
            for line in [line.strip()]
        }

        assert "argparse" in imported
        assert imported & {"click", "typer", "rich"} == set()

    def test_classifiers_and_urls_are_present(self, pyproject) -> None:
        project = pyproject["project"]

        assert "Development Status :: 4 - Beta" in project["classifiers"]
        assert "Typing :: Typed" in project["classifiers"]
        assert set(project["urls"]) >= {"Homepage", "Repository", "Changelog"}
        assert project["requires-python"] == ">=3.11"


class TestInstalledMetadataAgrees:
    """When the distribution *is* installed, its metadata must say the same.

    Skipped rather than failed when it is not: the repo's own suite runs
    uninstalled from `PYTHONPATH=backend`, and CI's clean-venv job (ticket 06)
    is where this assertion becomes unconditional.
    """

    def test_requires_dist_matches_the_declaration(self) -> None:
        try:
            requires = metadata.requires(DISTRIBUTION) or []
        except metadata.PackageNotFoundError:
            pytest.skip(f"{DISTRIBUTION} is not installed in this environment")

        unconditional = {
            requirement_name(r) for r in requires if "extra ==" not in r
        }

        assert unconditional == LEAN_CORE


class TestAMissingExtraSaysWhichOne:
    """The other half of the bargain: extraction is only honest if the code
    names the extra when it is absent. `ModuleNotFoundError: No module named
    'deepagents'` leaves an adopter to guess which of seven extras owns it."""

    def test_require_extra_names_the_install_line(self) -> None:
        from openstategraph._extras import require_extra

        with pytest.raises(ImportError) as excinfo:
            require_extra("no_such_module_at_all", "deep", "tier='deep' agent nodes")

        message = str(excinfo.value)
        assert "tier='deep' agent nodes" in message
        assert "pip install 'openstategraph[deep]'" in message

    def test_require_extra_returns_the_module_when_it_is_installed(self) -> None:
        from openstategraph._extras import require_extra

        assert require_extra("json", "deep", "nothing").loads("[]") == []

    @pytest.mark.parametrize(
        ("model", "extra"),
        [
            ("anthropic:claude-haiku-4-5", "anthropic"),
            ("openai:gpt-4.1-mini", "openai"),
            ("ollama:gpt-oss:120b-cloud", "ollama"),
        ],
    )
    def test_a_model_string_maps_to_its_provider_extra(self, model: str, extra: str) -> None:
        from openstategraph._extras import provider_extra_hint

        assert provider_extra_hint(model) == f"pip install 'openstategraph[{extra}]'"

    def test_an_unknown_provider_gets_no_guess(self) -> None:
        """A wrong install line is worse than none."""
        from openstategraph._extras import provider_extra_hint

        assert provider_extra_hint("mystery:model") is None
