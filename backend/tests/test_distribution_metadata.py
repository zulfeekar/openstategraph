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

# `osg-agent-experience/79`: the remedy is composed for the installation it is
# printed on — `uv tool install --force` repairs a tool install, and a
# pre-release carries index flags — so every assertion below reaches it through
# `install_hint` rather than transcribing it. A literal here would pin one
# machine's answer and be wrong on every other; the command itself is asserted
# where it is composed, `test_the_install_hint_can_be_carried_out.py`.
from openstategraph.install_hint import install_hint

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
        # `all` and `dev` are both excluded, for the same reason and the same
        # reason `test_all_names_every_extra` excludes them: neither is a
        # *capability*. `all` is a fan-out over the others, and `dev` is the
        # contributor environment — it is not in `[all]`, so no adopter ever
        # resolves it and it is not part of the install story this mapping
        # documents. `[dev]` therefore may legitimately name a distribution a
        # capability extra also names, at a different constraint: it pins
        # `fastapi` exactly so `docs/openapi.json` is reproducible, while
        # `[server]` keeps a range for adopters (ship-it ticket 50, and
        # `test_openapi_toolchain.py` is what holds those two together).
        capability_extras = {
            extra: requirements
            for extra, requirements in pyproject["project"]["optional-dependencies"].items()
            if extra not in {"all", "dev"}
        }

        # Built explicitly rather than by comprehension: a dict comprehension
        # lets a second claim overwrite the first silently, so one distribution
        # in two capability extras would read as a wrong answer here instead of
        # as the ambiguity it is.
        placement: dict[str, str] = {}
        for extra, requirements in capability_extras.items():
            for requirement in requirements:
                name = requirement_name(requirement)
                # `openstategraph[mcp]` inside `[server]` (osg-agent-experience/19,
                # the same shape `[sqlite]` already used) is composition, not an
                # extracted *distribution* — self-references name no package this
                # mapping tracks, and two of them in one extra are not a
                # collision.
                if name == DISTRIBUTION:
                    continue
                assert name not in placement, (
                    f"{name} is claimed by both [{placement[name]}] and [{extra}] — "
                    "an extracted dependency has exactly one owning capability"
                )
                placement[name] = extra

        assert {name: placement.get(name) for name in EXTRACTED} == EXTRACTED

    def test_all_names_every_extra_it_may_decide_for_you(self, pyproject) -> None:
        """`[all]` is the upgrade path for anyone on today's behaviour — if it
        misses an extra, they lose a capability on upgrade and never see why.

        `[bastion]` is the one exclusion, and it is named here rather than
        allowed to slip out silently, because that is the whole value of this
        test. `bastion-prompt-protection` is **AGPL-3.0-or-later**: including
        it would mean an adopter who typed the convenient install line took a
        licence position they never chose, which is a worse surprise than a
        capability they have to ask for. It also brings a local ONNX model.

        So `[all]` means "everything this project can decide for you", not
        "everything that exists" — and a second extra wanting out of `[all]`
        has to argue its way into this set (guardrails ticket 04,
        `docs/decisions/injection-screening.md`).
        """
        extras = pyproject["project"]["optional-dependencies"]
        named = set(re.findall(r"\[([^\]]+)\]", " ".join(extras["all"]))[0].split(","))

        assert named == set(extras) - {"all", "dev", "bastion"}


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

    def test_the_wheel_is_built_with_the_hook_that_puts_the_editor_in_it(
        self, pyproject
    ) -> None:
        """Scale-and-adopt ticket 01: we call this a *visual* workflow builder
        and shipped 215 KB of Python with no UI. The build hook is what makes
        `pip install` deliver the canvas, and losing this one line of config
        would silently take it back out — the wheel would still build, still
        install, still import, and `/` would be a 404."""
        hooks = pyproject["tool"]["hatch"]["build"]["hooks"]

        assert hooks["custom"]["path"] == "hatch_build.py"
        assert (PYPROJECT.parent / "hatch_build.py").is_file()

    def test_a_build_with_no_editor_fails_instead_of_shipping_without_one(
        self, tmp_path
    ) -> None:
        """The failure mode this replaces is the silent one: a release job with
        no `npm run build` produced a perfectly valid, perfectly useless wheel."""
        import sys

        sys.path.insert(0, str(PYPROJECT.parent))
        try:
            from hatch_build import editor_force_include
        finally:
            sys.path.pop(0)

        backend = tmp_path / "backend"
        backend.mkdir()

        with pytest.raises(RuntimeError) as excinfo:
            editor_force_include(backend, "standard")
        assert "npm run build" in str(excinfo.value)

        # …and the contributor path stays open: an editable install must not
        # need Node.js, which is exactly how CI installs the backend.
        assert editor_force_include(backend, "editable") == {}

    def test_the_editor_is_shipped_without_its_sourcemaps(self, tmp_path) -> None:
        """18 MB of the 23 MB `dist/` weighs is a debugging aid for people
        working on THIS repository, not for anyone installing it."""
        import sys

        sys.path.insert(0, str(PYPROJECT.parent))
        try:
            from hatch_build import editor_force_include
        finally:
            sys.path.pop(0)

        (tmp_path / "dist" / "assets").mkdir(parents=True)
        (tmp_path / "dist" / "index.html").write_text("<div id='root'></div>")
        (tmp_path / "dist" / "assets" / "app.js").write_text("//")
        (tmp_path / "dist" / "assets" / "app.js.map").write_text("{}")
        (tmp_path / "backend").mkdir()

        shipped = set(editor_force_include(tmp_path / "backend", "standard").values())

        assert "openstategraph/api/static/editor/index.html" in shipped
        assert "openstategraph/api/static/editor/assets/app.js" in shipped
        assert not [name for name in shipped if name.endswith(".map")]

    def test_the_console_script_is_declared_and_resolvable(self, pyproject) -> None:
        """`openstategraph` on the PATH is what ticket 08 exists to add, and a
        typo in this one line is invisible until someone installs the wheel."""
        scripts = pyproject["project"]["scripts"]

        # `console_main`, not `main`, and the difference is deliberate: the
        # console script is a **process** entry point and reads `.env` before
        # anything asks for a credential. `main()` stays a plain function this
        # project's own tests call in-process — a function that rewrites
        # `os.environ` from a file poisons every test after it, which is
        # exactly what happened when the load lived there.
        assert scripts == {"openstategraph": "openstategraph.cli:console_main"}
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
    uninstalled from `PYTHONPATH=backend`, and CI's `clean-install` job
    (`.github/workflows/ci.yml`, ticket 06) is where this assertion becomes
    unconditional.

    **The skip is a decision, not an omission** (ticket 47). It is the one skip
    in the suite, so on a developer machine this reports nothing rather than
    red and a metadata regression is CI-only by construction. That is accepted:
    the check genuinely needs an installed distribution, and manufacturing one
    inside the unit suite would be building a venv to test a packaging claim
    that `clean-install` already tests properly. What was wrong was that the
    skip said none of this — the reason string named no home, so a reader could
    not tell a deliberate skip from a forgotten one. It names the job now.

    (Until 2026-08-16 the docstring called that job `clean-venv`. No such job
    has ever existed; it is `clean-install`. A pointer to a job nobody can find
    is how a recorded decision quietly becomes folklore.)
    """

    def test_requires_dist_matches_the_declaration(self) -> None:
        try:
            requires = metadata.requires(DISTRIBUTION) or []
        except metadata.PackageNotFoundError:
            pytest.skip(
                f"{DISTRIBUTION} is not installed here — this assertion's home is "
                "the `clean-install` job in .github/workflows/ci.yml, which "
                "installs the wheel into a clean venv and runs it unconditionally. "
                "Deliberate skip, not a gap: see this class's docstring."
            )

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
        assert install_hint("deep") in message

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

        assert provider_extra_hint(model) == install_hint(extra)

    def test_an_unknown_provider_gets_no_guess(self) -> None:
        """A wrong install line is worse than none."""
        from openstategraph._extras import provider_extra_hint

        assert provider_extra_hint("mystery:model") is None
