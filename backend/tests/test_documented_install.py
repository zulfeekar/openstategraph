"""The line a customer is told to paste — workflow-gallery ticket 37.

Ticket 08 installed the wheel like a customer, followed `docs/adoption.md`
literally (`Needs openstategraph[server]`), copied a shipped example, pressed
Run, and got a refusal: `[server]` is fastapi, uvicorn, python-multipart and
sqlite, and contains no provider integration at all. Every Run button and
every `openstategraph run` failed on an install the documentation prescribed.

The decision taken (see the ticket's resolution) is that **`[server]` keeps
meaning the web layer** — folding one vendor into it would pick that vendor
for everyone and still leave the wall in place for anybody who chose a
different one — and that the *documented line* is the fix surface. Which
makes the documentation load-bearing, and therefore something a test has to
hold: prose drifts, and this particular prose costs an adopter their first
run.

So the rule pinned here is small and mechanical:

> **Any installable reference that includes `server` must also resolve to a
> provider integration.**

"Installable reference" means the thing a reader can paste — `openstategraph[…]`
or `backend[…]` — not a bare `[server]` in a table of extras, which is naming
the extra rather than prescribing an install. `[all]` satisfies the rule by
containing all three providers; `[server,ollama]` by naming one.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from openstategraph.install_hint import install_hint
from openstategraph.providers import builtin_specs, provider_catalogue

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "backend" / "pyproject.toml"
EXAMPLES = ROOT / "backend" / "openstategraph" / "examples"

#: Everywhere a reader is handed an install line. CHANGELOG.md and
#: `docs/decisions/` are deliberately absent: both are records of what was
#: decided *then*, and rewriting history to satisfy a gate is how a changelog
#: stops being one.
DOCUMENTS = (
    "README.md",
    "CONTRIBUTING.md",
    "docs/adoption.md",
    "docs/getting-started.md",
    "docs/what-is-this.md",
    "backend/README.md",
    "site/index.html",
    "backend/openstategraph/api/static/editor_missing.html",
)

#: `openstategraph[server,ollama]` or `backend[all,dev]` — the two spellings,
#: since the checkout installs the directory and an adopter installs the name.
INSTALLABLE = re.compile(r"(?:openstategraph|backend)\[([a-z0-9,\-]+)\]")


@pytest.fixture(scope="module")
def extras() -> dict[str, list[str]]:
    return tomllib.loads(PYPROJECT.read_text())["project"]["optional-dependencies"]


def resolve(names: set[str], extras: dict[str, list[str]]) -> set[str]:
    """Every extra `names` pulls in, following `openstategraph[…]` self-references.

    `[server]` depends on `[sqlite]` and `[all]` on everything, so a reader
    pasting one line gets a set rather than a name — and the rule below is
    about the set.
    """
    seen: set[str] = set()
    pending = list(names)
    while pending:
        extra = pending.pop()
        if extra in seen or extra not in extras:
            continue
        seen.add(extra)
        for requirement in extras[extra]:
            found = INSTALLABLE.search(requirement)
            if found:
                pending.extend(found.group(1).split(","))
    return seen


def installable_references() -> list[tuple[str, int, set[str]]]:
    """Every pasteable extras reference in the documentation, with its home."""
    found: list[tuple[str, int, set[str]]] = []
    for relative in DOCUMENTS:
        path = ROOT / relative
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            for match in INSTALLABLE.finditer(line):
                found.append((relative, number, set(match.group(1).split(","))))
    return found


def example_settings() -> dict[str, dict]:
    """`{slug: settings}` for every shipped example, settings possibly empty."""
    return {
        path.parent.name: (json.loads(path.read_text()).get("document", {}).get("settings") or {})
        for path in sorted(EXAMPLES.glob("*/workflow.json"))
    }


class TestTheDocumentedInstallCanRunSomething:
    def test_no_shipped_example_names_a_provider(self) -> None:
        """Flipped by install-experience T10 (grill item G1(a)).

        This asserted the opposite until 2026-08-15 —
        `example_models() == {"ollama:gpt-oss:120b-cloud"}` — and the reasoning
        was sound for what it guarded: if the gallery mixed providers, the one
        quickstart line could not cover all of them, and this failing was how
        that got decided rather than missed.

        What changed is the premise underneath it. The install line is the
        mental model: `pip install 'openstategraph[anthropic]'` means Anthropic
        is the default, and the instance default is now elected from what is
        *installed* (T2). A gallery where all 22 documents pin Ollama makes
        that false for the twenty-two things a new adopter opens first — they
        copy one, press Run, and are told to install a vendor they did not
        choose. Rewriting the pin at copy time was refused: workflow-gallery 07
        makes a copy **verbatim**, and falsifying a package's own `AGENTS.md`
        on the way out is exactly what 07 chose against.

        So the pin leaves the **source** documents, and this repository pins
        its own runs where a pin belongs — `openstategraph.yaml`, asserted
        below. A copied example then runs on whatever the adopter installed,
        and `settings.model` still wins wherever a document genuinely needs a
        specific model.
        """
        offenders = {slug: s["model"] for slug, s in example_settings().items() if s.get("model")}
        assert offenders == {}, (
            "these shipped examples name a vendor, so an adopter who installed a "
            f"different one cannot run them as copied: {offenders}"
        )

    def test_the_examples_still_declare_what_they_are_for(self) -> None:
        """Unpinned is not unset: `settings` still carries `purpose`.

        Guards the mechanical form of the edit — a bulk removal that took the
        whole `settings` block with it would leave the gallery's own
        descriptions gone and nothing failing.
        """
        without = [slug for slug, s in example_settings().items() if not s.get("purpose")]
        assert without == []

    def test_this_repository_pins_its_own_runs(self) -> None:
        """The other half of G1(a), and the standing Ollama-cloud rule's new home.

        The gallery is developed and smoke-run here, and CLAUDE.md's constraint
        has not moved: these runs go to Ollama **cloud**, never a local model,
        because a weak local model turns a wiring bug and a capability gap into
        the same symptom. That was enforced by 22 document pins; it is enforced
        by one committed config file now, which is the level a repository-wide
        choice belongs at — and is what workflow-gallery ticket 12 was really
        asking for when it worried about a stray `ANTHROPIC_API_KEY` billing
        Claude while the gallery was being built.
        """
        from openstategraph.config_file import load_config

        config = load_config(ROOT / "openstategraph.yaml")
        assert config.default_model is not None
        spec = provider_catalogue().for_model(config.default_model)
        assert spec is not None and spec.name == "ollama"
        assert config.default_model.endswith("-cloud"), (
            "Ollama means Ollama cloud in this project, never a local model"
        )

    def test_the_quickstart_install_still_carries_a_provider(
        self, extras: dict[str, list[str]]
    ) -> None:
        """What replaces the per-vendor check above, and it is the same ticket.

        With the gallery naming no vendor, "the extra the examples need" is
        whichever one the reader installed — so the property left to hold is
        that a documented line which serves the product installs *a* provider
        at all. That is the test below, and this one only guards that such a
        line still exists to check.
        """
        serving = [
            (where, line, names)
            for where, line, names in installable_references()
            if "server" in resolve(names, extras)
        ]
        assert serving, "no documented install line serves the product any more"

    def test_no_documented_install_serves_without_any_provider(
        self, extras: dict[str, list[str]]
    ) -> None:
        """The general form, so a future example on a different vendor is covered.

        Stated separately from the test above because they fail for different
        reasons: that one catches the wrong provider, this one catches none.
        """
        provider_extras = {spec.extra for spec in builtin_specs()}
        offenders = []
        for where, line, names in installable_references():
            resolved = resolve(names, extras)
            if "server" in resolved and not resolved & provider_extras:
                offenders.append(f"{where}:{line}")

        assert offenders == [], (
            "an install line naming [server] and no provider gives a reader the "
            f"editor, the chat surface and no way to run anything: {offenders}"
        )

    def test_the_serving_quickstart_names_the_command_that_makes_a_project(self) -> None:
        """install-experience T6, pinned for the same reason as everything else
        in this module: this prose is load-bearing.

        The pasteable sequence is three lines and each carries a different half
        of the mental model — the extra names the vendor, `init` names the
        directory, and the starter is already in it. A quickstart that installs
        `[server]` and goes straight to `serve` drops the middle one, and the
        reader lands on an empty canvas in a directory nobody chose.
        """
        offenders = []
        for relative in ("README.md", "docs/adoption.md"):
            lines = (ROOT / relative).read_text().splitlines()
            for number, line in enumerate(lines, start=1):
                if "openstategraph serve" not in line or "`" in line:
                    continue
                window = lines[max(0, number - 4) : number]
                if not any("openstategraph init" in near for near in window):
                    offenders.append(f"{relative}:{number}")

        assert offenders == [], (
            "a pasteable `openstategraph serve` with no `openstategraph init` above it "
            f"sends a reader to a directory they never chose: {offenders}"
        )

    def test_the_provider_extras_are_not_in_server(self, extras: dict[str, list[str]]) -> None:
        """The decision, recorded as a test rather than only as prose.

        Folding a provider into `[server]` was the other way to close ticket
        37, and it was rejected: it picks a vendor on everyone's behalf, bills
        an Anthropic adopter for an Ollama SDK, and does not remove the wall —
        it moves it to whoever chose differently. If someone reverses that,
        this is where the argument is waiting.
        """
        provider_extras = {spec.extra for spec in builtin_specs()}

        assert resolve({"server"}, extras) & provider_extras == set()

    def test_the_server_extra_pulls_in_mcp(self, extras: dict[str, list[str]]) -> None:
        """osg-agent-experience/19.

        The local MCP server is part of the developer experience (owner
        decision, `.scratch/osg-agent-experience/OWNER-DECISIONS.md`), so the
        requirement's own install line — `"openstategraph[server,ollama]"`,
        run for real on 2026-09-04 — has to leave a reader able to run
        `openstategraph mcp`. It did not: `[server]` pulled in `[sqlite]` and
        nothing else, so a fresh install hit the missing-extra message the
        moment an agent said "use OpenStateGraph MCP".

        `[mcp]` stays a real, nameable extra (someone who only wants the MCP
        transport, with no web server, still installs `[mcp]` alone) — this
        only asks that `[server]`'s own requirement set be a superset of it,
        the same shape as the `[sqlite]` self-reference already above it.
        """
        assert "mcp" in resolve({"server"}, extras), (
            "'openstategraph[server,ollama]' must yield a working "
            "'openstategraph mcp' — [server] does not resolve to [mcp]"
        )


class TestServeSaysSoBeforeItServes:
    """The other half of ticket 37: the gap must be loud where it is chosen.

    `cmd_serve`'s own docstring has the rule — "a message printed after a
    server is listening is a message someone scrolls past" — so this belongs
    with the two refusals already evaluated before the socket is bound.
    """

    def test_it_warns_when_no_provider_integration_is_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from openstategraph import cli
        from openstategraph.providers import ProviderSpec, reset_provider_catalogue

        reset_provider_catalogue()
        monkeypatch.setattr(
            "openstategraph.providers.builtin_specs",
            lambda: (
                ProviderSpec(
                    name="ghost",
                    default_model="spook-1",
                    extra="ghost",
                    integration_module="langchain_ghost_which_is_not_installed",
                ),
            ),
        )
        reset_provider_catalogue()

        warning = cli.no_provider_warning()

        assert warning is not None
        # `osg-agent-experience/79`: the remedy is composed for the installation
        # it is printed on, so it is asserted through `install_hint` rather than
        # transcribed — a literal here would pin one machine's answer.
        assert install_hint("ghost") in warning
        assert warning.count("\n") == 0
        reset_provider_catalogue()

    def test_it_stays_quiet_when_one_is(self) -> None:
        """This checkout has all three, so silence here is the real path."""
        from openstategraph import cli

        assert cli.no_provider_warning() is None
