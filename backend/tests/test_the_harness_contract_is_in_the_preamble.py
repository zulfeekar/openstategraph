"""The harness contract belongs in the preamble — `launch-readiness/120`.

`AbstractAgentNode.PROMPT` declared `preamble=""`, defended by a comment
saying an agent "legitimately answers free-form, so the base imposes no
contract". That reasoning was already found half wrong once: `output_contract`
was empty for the same stated reason until `launch-readiness/27`, when a
customer-audience answer opened *"Perfect. I now have the official
documentation."* — the model's monologue about its own tool loop, published
verbatim because nothing told it not to.

This is the other end of the same silence. A deep-tier agent is handed a
virtual filesystem and an offload seam that **replaces a large tool result
with a path**, and nothing ever told it that the path *is* the result. The
pointer text (`abc/deep_tier_offload.py`) says where the data went; no string
anywhere said *re-read it instead of calling the tool again*.

Two halves, and the second is the one that keeps the platform honest:

- present for an agent that can actually dereference a path, and
- **absent** for one that cannot — a preamble claiming a filesystem to an
  agent without one is a lie told by the platform on every turn, and the worst
  kind, because a package author can neither see it nor fix it.

The condition is not a new one: `surface_can_dereference(...)`, the same two
facts (`111`) that gate disclosure and offload themselves. If the middlewares
were not contributed, there is nothing to describe.
"""

from __future__ import annotations

import pytest

pytest.importorskip("deepagents")

from langchain.tools import tool

from openstategraph.abc.agent import BaseAgentNode, DeepAgentNode, ReactAgentNode
from openstategraph.abc.deep_tier_offload import (
    HARNESS_PREAMBLE,
    SKILL_DISCLOSURE_PREAMBLE,
    harness_preamble,
)
from openstategraph.abc.prompt import SystemPrompt


@tool
def query_rows(sql: str) -> str:
    """Run a query."""
    return "rows"


class _Store:
    """Stands in for the run's `FilesystemBackend` — only its presence is read."""


def _deep(**kwargs):
    node = DeepAgentNode(name="a", model=None, tools=[query_rows], **kwargs)
    return node


# --------------------------------------------------------------------------- #
# The text itself.
# --------------------------------------------------------------------------- #


class TestWhatTheContractSays:
    def test_it_names_the_filesystem_and_says_it_is_confined(self) -> None:
        for verb in ("read_file", "grep", "write_file", "ls"):
            assert verb in HARNESS_PREAMBLE
        assert "confined" in HARNESS_PREAMBLE

    def test_it_teaches_the_habit_and_not_only_the_location(self) -> None:
        """The gap `120` was filed for.

        The pointer already says *where* the result went. Nothing said *what
        to do about it*, which is the whole point of a harness that reads and
        writes: re-read the file, never re-call the tool for data already
        fetched.
        """
        assert "offloaded" in HARNESS_PREAMBLE
        assert "never call the tool a second time" in HARNESS_PREAMBLE

    def test_it_points_the_model_back_at_its_real_tools(self) -> None:
        """`launch-readiness/146`'s shape, addressed in words.

        A run answering one question read files a dozen times, seven of them
        *after* the query had already returned its rows. The neighbouring
        system removes the tools; this says plainly what the files are for.
        """
        assert "not a source of facts" in HARNESS_PREAMBLE

    def test_no_domain_word_appears_in_it(self) -> None:
        """CLAUDE.md's load-bearing sentence, in the direction that binds core."""
        text = (HARNESS_PREAMBLE + SKILL_DISCLOSURE_PREAMBLE).lower()
        for word in ("vessel", "cargo", "curve", "warehouse", "sql", "berth", "voyage"):
            assert word not in text


# --------------------------------------------------------------------------- #
# The condition — both halves.
# --------------------------------------------------------------------------- #


class TestItFollowsTheToolSurface:
    def test_a_surface_that_cannot_dereference_is_told_nothing(self) -> None:
        assert harness_preamble(("query_rows",), shares_backend=True) == ""

    def test_a_file_reader_over_a_different_store_is_told_nothing(self) -> None:
        assert harness_preamble(("read_file", "grep"), shares_backend=False) == ""

    def test_a_dereferenceable_surface_is_told(self) -> None:
        assert HARNESS_PREAMBLE in harness_preamble(("read_file",), shares_backend=True)

    def test_the_skills_line_is_only_there_when_skills_were_disclosed(self) -> None:
        without = harness_preamble(("read_file",), shares_backend=True)
        with_skills = harness_preamble(("read_file",), shares_backend=True, skills_disclosed=True)
        assert SKILL_DISCLOSURE_PREAMBLE not in without
        assert SKILL_DISCLOSURE_PREAMBLE in with_skills


class TestTheTiersThatGetIt:
    def test_the_react_tier_is_silent(self) -> None:
        """No filesystem, so nothing to describe. The base ClassVar stays empty."""
        node = ReactAgentNode(name="a", model=None, tools=[query_rows])
        assert BaseAgentNode.PROMPT.preamble == ""
        assert node.prompt.preamble == ""
        rendered = node.resolve_prompt() or ""
        assert "offloaded" not in rendered
        assert "read_file" not in rendered

    def test_a_deep_tier_with_no_shared_store_is_silent(self) -> None:
        """It holds file tools; they read a store this seam never wrote to, so
        an offload pointer is a reference it cannot follow — and there is no
        offload middleware either (`plan_disclosure` refused for the same
        reason). Describing it would be describing nothing."""
        node = _deep(backend=None)
        assert node.prompt.preamble == ""
        assert "offloaded" not in (node.resolve_prompt() or "")

    def test_a_deep_tier_sharing_the_store_carries_the_contract(self) -> None:
        node = _deep(backend=_Store())
        assert HARNESS_PREAMBLE in node.prompt.preamble
        assert HARNESS_PREAMBLE in (node.resolve_prompt() or "")

    def test_a_disclosed_skill_adds_its_line_and_nothing_else_does(self) -> None:
        plain = _deep(backend=_Store())
        disclosed = DeepAgentNode(
            name="a",
            model=None,
            tools=[query_rows],
            backend=_Store(),
            middleware={"skills": object()},
        )
        assert SKILL_DISCLOSURE_PREAMBLE not in plain.prompt.preamble
        assert SKILL_DISCLOSURE_PREAMBLE in disclosed.prompt.preamble


# --------------------------------------------------------------------------- #
# Order is the substance.
# --------------------------------------------------------------------------- #


class TestOrderAndLock:
    def test_the_contract_renders_first_and_the_output_contract_last(self) -> None:
        node = _deep(backend=_Store(), rules="Answer in Norwegian.")
        rendered = node.resolve_prompt() or ""
        assert rendered.index(HARNESS_PREAMBLE) < rendered.index("Answer in Norwegian.")
        assert rendered.index("Answer in Norwegian.") < rendered.index(
            BaseAgentNode.PROMPT.output_contract[:40]
        )
        assert rendered.startswith("<role>")

    def test_replacing_the_rules_cannot_delete_it(self) -> None:
        """`replace_defaults` reaches the rules layers and nothing above them —
        the original `RouterNode` defect, not to be paid for a third time."""
        node = _deep(backend=_Store(), rules="Only this.", replace_rules=True)
        rendered = node.resolve_prompt() or ""
        assert HARNESS_PREAMBLE in rendered
        assert "Answer the question that was asked" not in rendered

    def test_it_is_not_an_editable_section(self) -> None:
        node = _deep(backend=_Store())
        assert "preamble" not in node.prompt.describe()["editable"]

    def test_a_node_that_declares_its_own_preamble_keeps_it(self) -> None:
        """A tier that owns machinery overrides the ClassVar; the harness
        contract is prepended to it rather than replacing it."""

        class Owned(DeepAgentNode):
            PROMPT = SystemPrompt(preamble="You are a specialist.", output_contract="Answer.")

        node = Owned(name="a", model=None, tools=[query_rows], backend=_Store())
        assert HARNESS_PREAMBLE in node.prompt.preamble
        assert "You are a specialist." in node.prompt.preamble
