"""Every place that reads a model's answer reads it the same way.

The agent's version of this bug shipped and was fixed (ticket 03: every run a
user could see returned their own question). A review then found the same
`isinstance(content, str)` in four more places, each failing differently and
none of them loudly:

    abc/grader.py        a repr instead of PASS/FAIL
    abc/router.py        a repr instead of a branch name
    abc/orchestrator.py  a repr instead of worker labels
    api/streaming.py     no token frames at all

These tests pin the shared reader, and — more importantly — pin that those
four call sites actually use it.
"""

from __future__ import annotations

from pathlib import Path

from openstategraph.messages import content_text

REPO = Path(__file__).resolve().parents[2]


class TestContentText:
    def test_a_plain_string_is_itself(self) -> None:
        assert content_text("PASS") == "PASS"

    def test_a_block_list_reads_as_its_text(self) -> None:
        assert content_text([{"type": "text", "text": "PASS", "index": 0}]) == "PASS"

    def test_blocks_are_joined_in_order(self) -> None:
        assert (
            content_text(
                [
                    {"type": "text", "text": "FAIL\n"},
                    {"type": "text", "text": "no revenue table"},
                ]
            )
            == "FAIL\nno revenue table"
        )

    def test_reasoning_is_not_part_of_the_answer(self) -> None:
        # A thinking model's private deliberation rides in the same list. It
        # must never reach a grader's verdict or a customer's screen.
        blocks = [
            {"type": "thinking", "thinking": "the user probably wants FAIL", "signature": "s"},
            {"type": "text", "text": "PASS"},
        ]

        assert content_text(blocks) == "PASS"

    def test_anything_else_is_empty_not_a_repr(self) -> None:
        # The whole defect was a repr masquerading as an answer. Empty is a
        # visible failure; "[{'type': ...}]" is one that reads as success.
        assert content_text(None) == ""
        assert content_text(object()) == ""


class TestNobodyReadsItTheOldWay:
    """The regression guard, and the reason this file exists.

    Fixing four call sites is worth little if the fifth is written next month.
    """

    SITES = [
        "backend/openstategraph/abc/grader.py",
        "backend/openstategraph/abc/router.py",
        "backend/openstategraph/abc/orchestrator.py",
        "backend/openstategraph/api/streaming.py",
        "backend/openstategraph/compile/node_runtime.py",
        # `_final_text` — the caller the deleted copy had — left for
        # `compile/reporting.py` in the `docs-and-gaps/03` split. The scan
        # follows it: a census that goes on naming the file the code left
        # is green and blind, which is the defect this file is about.
        "backend/openstategraph/compile/reporting.py",
    ]

    def test_no_call_site_stringifies_message_content(self) -> None:
        offenders = []
        for site in self.SITES:
            text = (REPO / site).read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("*"):
                    continue
                # `str(content)` / `str(reply.content)` — the exact shape that
                # turned a block list into a Python repr.
                if "str(content)" in line or "str(reply.content)" in line:
                    offenders.append(f"{site}:{number}: {stripped}")

        assert offenders == [], "message content must be read with content_text(): " + "; ".join(
            offenders
        )


class TestNobodyWritesASecondReader:
    """The other half of the guard, and the half that was missing.

    `TestNobodyReadsItTheOldWay` scans for `str(content)` — the *stringifying*
    spelling of the bug. It cannot see the failure mode that actually
    happened next: a call site that reads the shapes correctly, but does so in
    its own hand-rolled copy of `content_text`. `compile/node_runtime.py`
    carried one for months (`_content_text`), byte-identical in behaviour, in
    the one file whose docstring is an account of why this knowledge must
    exist exactly once (docs-and-gaps 14).

    Identical today is the hazard, not the reassurance: DRY's rule is
    duplication of *knowledge*, and a second copy is a second thing to fix the
    next time a provider ships a shape neither expects.

    The telltale is `isinstance(content, ...)` — a module branching on the
    shape of a message's content is deciding for itself how to read one.
    """

    def test_no_call_site_branches_on_content_shape(self) -> None:
        offenders = []
        for site in TestNobodyReadsItTheOldWay.SITES:
            text = (REPO / site).read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("*"):
                    continue
                # Prose quotes the bug by name all over this codebase —
                # inside backticks it is a *mention*, not a call.
                if "`isinstance(content" in line:
                    continue
                if "isinstance(content," in line:
                    offenders.append(f"{site}:{number}: {stripped}")

        assert offenders == [], (
            "reading a message's content is content_text()'s job, once: "
            + "; ".join(offenders)
        )


class TestTheAgentAnswerReaderUsesTheSharedOne:
    """And the rewire, proven by behaviour rather than by grep.

    A scan proves the copy is gone; it does not prove the survivor is what
    replaced it. `_final_text` — the agent loop's "what did the model say this
    turn" walk-back — is the caller the deleted copy had.
    """

    def test_final_text_reads_content_through_content_text(self, monkeypatch) -> None:
        from langchain_core.messages import AIMessage

        # `reporting`, not `node_runtime`: the function moved there and the
        # patch has to land where the name it calls is resolved. Patching the
        # re-export would pass without proving anything.
        from openstategraph.compile import reporting

        monkeypatch.setattr(reporting, "content_text", lambda content: "via the shared reader")

        assert reporting._final_text([AIMessage(content="raw")]) == "via the shared reader"
