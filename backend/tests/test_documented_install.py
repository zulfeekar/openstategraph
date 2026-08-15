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


def example_models() -> set[str]:
    return {
        (json.loads(path.read_text()).get("document", {}).get("settings") or {}).get("model", "")
        for path in sorted(EXAMPLES.glob("*/workflow.json"))
    }


class TestTheDocumentedInstallCanRunSomething:
    def test_every_shipped_example_names_one_provider(self) -> None:
        """The premise the rest of this file rests on, asserted rather than assumed.

        If the gallery ever mixes providers, the quickstart line has to cover
        all of them or say which example it covers — and this failing is how
        that decision gets made instead of missed.
        """
        assert example_models() == {"ollama:gpt-oss:120b-cloud"}

    def test_the_quickstart_install_covers_the_examples_provider(
        self, extras: dict[str, list[str]]
    ) -> None:
        """`examples copy … && run …` after the pasted line, as a resolution.

        The whole of ticket 37 in one assertion: what the reader installs must
        contain the integration for what the reader then runs.
        """
        model = example_models().pop()
        spec = provider_catalogue().for_model(model)
        assert spec is not None, f"no registered provider owns {model!r}"

        serving = [
            (where, line, names)
            for where, line, names in installable_references()
            if "server" in resolve(names, extras)
        ]
        assert serving, "no documented install line serves the product any more"

        offenders = [
            f"{where}:{line}" for where, line, names in serving
            if spec.extra not in resolve(names, extras)
        ]
        assert offenders == [], (
            f"these install the product but not the [{spec.extra}] integration the "
            f"shipped examples need for {model!r}: {offenders} — a reader pasting one "
            "of them cannot run the example they are told to copy next"
        )

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
        assert "pip install 'openstategraph[ghost]'" in warning
        assert warning.count("\n") == 0
        reset_provider_catalogue()

    def test_it_stays_quiet_when_one_is(self) -> None:
        """This checkout has all three, so silence here is the real path."""
        from openstategraph import cli

        assert cli.no_provider_warning() is None
