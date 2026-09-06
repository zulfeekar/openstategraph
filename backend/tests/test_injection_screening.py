"""Prompt-injection screening is a dependency decision, not a default.

Guardrails ticket 04. The Guardrail node handles **shapes** — email,
credit_card, ip, mac_address, url — and nothing about it looks at intent.
Screening for an injected instruction is a different kind of thing and must
not ship as the same switch.

The facts these tests are written against were read off the published wheel
(`bastion_prompt_protection-1.3.5-py3-none-any.whl`), not from memory:

- the distribution is `bastion-prompt-protection`, the module is
  `bastion_prompt_protection`, and the middleware is
  `bastion_prompt_protection.integrations.langchain.BastionGuardrailMiddleware`;
- it is **AGPL-3.0-or-later**, and its commercial weights are gated on the
  Hugging Face Hub;
- it pulls `onnxruntime`, `huggingface-hub`, `numpy` and `tokenizers`, i.e. a
  local ONNX model on the deployer's own hardware;
- it screens in `before_model`, which runs for the user's turn *and* after
  tools return — so it covers indirect injection through retrieved content,
  and it lives inside the agent where no node at the edges could reach.

Any one of those is enough to make it opt-in. Together they make it a
recorded decision, which is `docs/decisions/injection-screening.md`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from openstategraph import injection

REPO = Path(__file__).resolve().parents[2]
PYPROJECT = REPO / "backend" / "pyproject.toml"


@pytest.fixture(scope="module")
def extras() -> dict[str, list[str]]:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return data["project"]["optional-dependencies"]


class TestItIsAnExtraAndOnlyAnExtra:
    def test_the_extra_exists_and_names_the_distribution(
        self, extras: dict[str, list[str]]
    ) -> None:
        assert any(
            requirement.startswith(injection.DISTRIBUTION) for requirement in extras["bastion"]
        )

    def test_no_default_extra_reaches_it(self, extras: dict[str, list[str]]) -> None:
        """The rule, and the reason the rule is a test.

        `[all]` is the trap: it is the extra that *sounds* like it should
        include everything, and folding an AGPL dependency into it would
        change the licence position of anyone who typed the convenient
        install line. `[server]` is the other one — it is what
        `docs/adoption.md` prescribes, so anything inside it is effectively
        a default.
        """
        for name, requirements in extras.items():
            if name == "bastion":
                continue
            resolved = _resolve(name, extras)
            assert "bastion" not in resolved, f"[{name}] pulls in [bastion]"
            assert not any(
                requirement.startswith(injection.DISTRIBUTION) for requirement in requirements
            ), f"[{name}] names {injection.DISTRIBUTION} directly"

    def test_it_is_not_installed_in_this_checkout(self) -> None:
        # The proof that the four-package floor still holds: this repository's
        # own test run does not have it, so nothing below can be passing
        # because the dependency happens to be lying around.
        assert not injection.is_installed()


class TestTheGapIsOneLine:
    def test_an_absent_package_is_a_readiness_gap_not_a_traceback(self) -> None:
        gap = injection.readiness()
        assert gap is not None
        assert str(gap.message).count("\n") == 0

    def test_it_names_the_exact_command(self) -> None:
        """`osg-agent-experience/82`: composed by `install_hint`, not hand-written —
        a literal here would pin one machine's answer rather than this one's."""
        from openstategraph.install_hint import install_hint

        gap = injection.readiness()
        assert gap is not None
        assert install_hint("bastion") in gap.message

    def test_it_says_what_is_not_happening_rather_than_what_failed(self) -> None:
        gap = injection.readiness()
        assert gap is not None
        # A developer who asked for screening and did not get it must learn
        # that the run went ahead unscreened, which is the fact they can act
        # on — not that an import failed.
        assert "injection" in gap.message.lower()

    def test_it_never_mentions_the_import_machinery(self) -> None:
        gap = injection.readiness()
        assert gap is not None
        for noise in ("ModuleNotFoundError", "Traceback", "find_spec"):
            assert noise not in gap.message


class TestAskingForItIsExplicit:
    def test_a_document_that_says_nothing_is_not_asking(self) -> None:
        assert injection.requested({}) is False
        assert injection.requested(None) is False

    def test_a_document_asks_through_its_settings(self) -> None:
        assert injection.requested({"injectionScreening": True}) is True

    def test_it_is_a_workflow_setting_not_a_node_field(self) -> None:
        """Where it lives, and why it is not on the Guardrail card.

        The dangerous injection arrives mid-loop, in a tool result, inside an
        agent's own compiled graph. No node at the edges of the canvas can
        reach it however visible we make it — so this is the cross-family
        case CLAUDE.md's boundary rule names, and it compiles to graph
        assembly exactly as `retry_policy` does. Putting a checkbox on every
        agent would be the per-agent duplication the Guardrail node exists to
        abolish; putting it on the Guardrail card would claim the node does
        something it cannot.
        """
        from openstategraph.compile.node_catalogue import CATALOGUE

        for keys in CATALOGUE.field_keys.values():
            assert "injectionScreening" not in keys


class TestTheContributionIsASlot:
    def test_it_names_a_slot_rather_than_a_position(self) -> None:
        # CLAUDE.md: any scheme expressing middleware position as one number
        # is expressing something that does not exist.
        assert isinstance(injection.SLOT, str)

    def test_the_slot_runs_before_everything_the_base_owns(self) -> None:
        from openstategraph.abc.agent import AbstractAgentNode

        # `before_*` hooks run first to last, and screening that ran after
        # another middleware had already acted on the injected text would be
        # screening after the fact.
        assert AbstractAgentNode.SLOT_ORDER[0] == injection.SLOT

    def test_asking_without_the_package_contributes_nothing_and_says_so(self) -> None:
        contribution, gap = injection.contribution(requested=True)
        assert contribution == {}
        assert gap is not None

    def test_not_asking_reports_no_gap_at_all(self) -> None:
        # Silence for the overwhelmingly common case. A warning on every run
        # of every workflow is one nobody reads.
        contribution, gap = injection.contribution(requested=False)
        assert (contribution, gap) == ({}, None)


class TestTheDecisionIsRecorded:
    def test_the_record_exists(self) -> None:
        assert (REPO / "docs" / "decisions" / "injection-screening.md").is_file()

    def test_it_states_the_licence_and_the_local_model_cost(self) -> None:
        text = (REPO / "docs" / "decisions" / "injection-screening.md").read_text(encoding="utf-8")
        assert "AGPL" in text
        assert "onnxruntime" in text

    def test_the_guardrail_docs_do_not_claim_to_cover_injection(self) -> None:
        """Ticket 04's second half: the docs stop implying the atom covers it.

        Asserted against the node's own copy, which is what a user actually
        reads, rather than against a prose file somebody may rename.
        """
        from openstategraph.compile.node_catalogue import CATALOGUE

        guardrail = next(n for n in CATALOGUE.nodes if n["type"] == "guard.policy")
        copy = f"{guardrail['label']} {guardrail['description']}".lower()
        assert "injection" not in copy
        assert "jailbreak" not in copy


def _resolve(name: str, extras: dict[str, list[str]]) -> set[str]:
    """Every extra `name` transitively pulls in, via `openstategraph[...]`."""
    import re

    seen: set[str] = set()
    stack = [name]
    pattern = re.compile(r"openstategraph\[([a-z0-9,\-]+)\]")
    while stack:
        current = stack.pop()
        if current in seen or current not in extras:
            continue
        seen.add(current)
        for requirement in extras[current]:
            for match in pattern.finditer(requirement):
                stack.extend(match.group(1).split(","))
    return seen
