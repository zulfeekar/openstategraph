"""What this repository says about `langgraph` and `langchain`, checked.

`docs-and-gaps/17`. Three assertions about installed packages were found wrong
against them on the same morning, and the sting was the third: `CLAUDE.md`'s
step-budget paragraph carried a dated self-correction calling its *previous*
version "wrong by twentyfold", and the correction was itself wrong by an order
of magnitude. **A paragraph that has been wrong twice in two directions is the
argument for this file.**

Two halves, and the second is the one the ticket asked for.

**The record.** The sweep that filed 17 verified other library claims as true
and wrote the list nowhere, so the next sweep re-checks them from scratch. A
list in prose would have exactly the failure mode this file exists to stop, so
the record is executable: `TestTheLibraryFactsThisRepositoryStates` derives
each claim from the installed package. A dependency bump that moves one of them
turns red here rather than in a reader's understanding.

**The gate.** `TestNoProseAttributesADefaultToTheLibrary` fails on prose that
states a library number instead of deriving it. It is deliberately narrow:
stating *our* number is exactly what a reader needs, and is what the corrected
paragraph does.

Nothing here reads a documentation page. `import` and `inspect` only — the
standing rule is that LangGraph facts come from the `docs-langchain` server,
and its corollary is that where the installed version disagrees with a page,
the installed version wins.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from openstategraph.step_budget import DEFAULT_STEP_BUDGET

REPO = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------- #
# The record: every library fact this repository states, derived.
# --------------------------------------------------------------------------- #


class TestTheLibraryFactsThisRepositoryStates:
    def test_graph_assembly_parameters_are_add_node_parameters(self) -> None:
        """CLAUDE.md — "retry, timeout and caching are graph-assembly
        parameters, not node concerns"."""
        from langgraph.graph import StateGraph

        params = set(inspect.signature(StateGraph.add_node).parameters)
        assert {"retry_policy", "cache_policy", "error_handler", "timeout"} <= params

    def test_set_node_defaults_exists_and_takes_those_same_four(self) -> None:
        """The claim RC-15 got wrong. Present since the 1.2 bump, and with
        exactly the signature RC-15 asks for — so RC-15's work is unblocked
        rather than waiting on a dependency."""
        from langgraph.graph import StateGraph

        assert hasattr(StateGraph, "set_node_defaults")
        assert set(inspect.signature(StateGraph.set_node_defaults).parameters) == {
            "self",
            "retry_policy",
            "cache_policy",
            "error_handler",
            "timeout",
        }

    def test_the_recursion_default_is_read_from_the_environment(self) -> None:
        """**Why a number must never be quoted for it.**

        It is not a constant. It is `getenv(...)` at import time, so any value
        written into prose is wrong on the next machine as well as on the next
        release — which is what makes "state ours instead" the honest fix
        rather than merely the shorter one.
        """
        import langgraph._internal._config as config

        source = inspect.getsource(config)
        assert "LANGGRAPH_DEFAULT_RECURSION_LIMIT" in source
        assert isinstance(config.DEFAULT_RECURSION_LIMIT, int)

    def test_overrunning_the_budget_raises_graph_recursion_error(self) -> None:
        from langgraph.errors import GraphRecursionError

        assert issubclass(GraphRecursionError, Exception)

    def test_send_interrupt_and_remaining_steps_are_all_present(self) -> None:
        """The three constructs the compiler builds on."""
        from langgraph.managed import RemainingSteps
        from langgraph.types import Send, interrupt

        assert Send is not None and interrupt is not None
        assert RemainingSteps is not None

    def test_create_agent_is_the_loop_and_it_is_importable(self) -> None:
        """CLAUDE.md's vocabulary: "Loop = `create_agent` (ReAct)"."""
        from langchain.agents import create_agent

        assert callable(create_agent)

    def test_only_the_png_drawer_reaches_a_third_party(self) -> None:
        """"Never send a user's graph to a third party" — the rule names
        `draw_mermaid_png`'s default endpoint, so the endpoint is what is
        checked rather than the rule restated."""
        import langchain_core.runnables.graph_mermaid as mermaid
        from langchain_core.runnables.graph import Graph

        assert hasattr(Graph, "draw_mermaid") and hasattr(Graph, "draw_mermaid_png")
        assert "mermaid.ink" in inspect.getsource(mermaid)

    def test_the_sync_half_is_the_one_an_implementer_owes(self) -> None:
        """`abc/async_doors.py`'s whole shape argument, in two assertions.

        `_generate`/`_run` are abstract and `_agenerate`/`_arun` are concrete:
        the library supplies the async half. That is why our ladders add
        `agrade`/`aclassify` beside the synchronous verb instead of replacing
        it, and why `_execute` could not simply become `async def`.
        """
        from langchain_core.language_models.chat_models import BaseChatModel
        from langchain_core.tools import BaseTool

        assert "_generate" in BaseChatModel.__abstractmethods__
        assert "_agenerate" not in BaseChatModel.__abstractmethods__
        assert "_run" in BaseTool.__abstractmethods__
        assert "_arun" not in BaseTool.__abstractmethods__

    def test_a_node_timeout_is_refused_for_a_synchronous_node(self) -> None:
        """`api/streaming.py`'s stop-boundary comment cites this by its own
        words, so the words are what is pinned."""
        import langgraph._internal._timeout as timeout

        assert "only supported for async" in inspect.getsource(timeout)

    def test_our_own_step_budget_is_the_number_in_force(self) -> None:
        """The one number a reader here actually needs, and the only one prose
        may state — because this is where it is defined."""
        assert DEFAULT_STEP_BUDGET == 50


# --------------------------------------------------------------------------- #
# The gate: prose may state our number, never theirs.
# --------------------------------------------------------------------------- #


def _prose_files() -> list[Path]:
    """Every surface a reader takes a library fact from.

    `CLAUDE.md` and the decision records, plus the shipped example packages —
    `workflows/*/graph.py` is the third finding of the ticket, and the reason
    it counts as prose is that a stranger reads it as documentation.
    """
    files = [REPO / "CLAUDE.md"]
    files += sorted((REPO / "docs").rglob("*.md"))
    files += sorted((REPO / "workflows").glob("*/graph.py"))
    return [f for f in files if f.is_file()]


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+|\n\n", text)


#: A ticket id (`docs-and-gaps/17`) and anything inside backticks are
#: references, never claims. Stripped before the numbers are counted, so the
#: rule catches a quoted default and not a citation of the ticket that banned
#: quoting one.
_CODE_SPAN = re.compile(r"`[^`]*`")
_TICKET_ID = re.compile(r"\b[a-z][a-z-]+/\d+\b")


def _bare(sentence: str) -> str:
    return _TICKET_ID.sub(" ", _CODE_SPAN.sub(" ", sentence))


_ABSENT = re.compile(
    r"(does not exist|doesn't exist|not exist|is absent|absent in|is missing|"
    r"does not ship|is not available|unavailable)",
    re.I,
)


class TestNoProseAttributesADefaultToTheLibrary:
    """Two rules, each drawn from one of the ticket's three findings."""

    @pytest.mark.parametrize("path", _prose_files(), ids=lambda p: p.name)
    def test_no_sentence_claims_set_node_defaults_is_absent(self, path: Path) -> None:
        """Finding 2 and finding 3, which are the same false sentence written
        twice — once in the register and once in a package a stranger reads as
        an example."""
        offenders = [
            s.strip()
            for s in _sentences(path.read_text(encoding="utf-8"))
            if "set_node_defaults" in s and _ABSENT.search(s)
        ]
        assert not offenders, (
            f"{path.relative_to(REPO)} says `set_node_defaults` is absent. It is "
            f"present on the installed langgraph, with the four-parameter "
            f"signature RC-15 asks for: {offenders}"
        )

    @pytest.mark.parametrize("path", _prose_files(), ids=lambda p: p.name)
    def test_no_sentence_quotes_the_librarys_recursion_default(
        self, path: Path
    ) -> None:
        """Finding 1.

        Narrow on purpose. A sentence is caught only when it does all three
        things at once — talks about recursion, attributes to the library, and
        carries a number that is not ours. Stating **our** budget is the point
        of the paragraph and stays legal; so does naming the environment
        variable, which is the honest way to answer "what is theirs".
        """
        offenders = []
        for sentence in _sentences(path.read_text(encoding="utf-8")):
            lowered = sentence.lower()
            if "recursion" not in lowered or "default" not in lowered:
                continue
            if not re.search(r"langgraph|the library|library's", lowered):
                continue
            quoted = {
                int(n) for n in re.findall(r"\b\d{2,}\b", _bare(sentence))
            } - {DEFAULT_STEP_BUDGET}
            if quoted:
                offenders.append((sentence.strip()[:200], sorted(quoted)))

        assert not offenders, (
            f"{path.relative_to(REPO)} quotes a recursion default for the "
            f"library. It is `getenv(\"LANGGRAPH_DEFAULT_RECURSION_LIMIT\", ...)` "
            f"at import time, so no literal is true for long — state ours "
            f"({DEFAULT_STEP_BUDGET}), or name the variable: {offenders}"
        )
