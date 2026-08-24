"""launch-readiness/27 — the agent's scratchpad is published to the customer.

Prior case, read first: `every-workflow-green/19` fixed narration on the
*orchestrator worker* path (`advisor_context` was missing from `_worker`'s
composed context, so a stuck worker had no way to say so and talked to
itself instead). This is (b), the same defect shape on a surface 19 never
covered: a plain `agent.llm` node (`BaseAgentNode`/`ReactAgentNode`), where
`CLAUDE.md`'s own prompt-composition table says the **output contract** is
"the base"'s and "no" for editability — but `BaseAgentNode.PROMPT.output_contract`
was deliberately left `""` ("an agent, unlike a router, legitimately answers
free-form, so the base imposes no contract"). Nothing forbade narrating the
tool loop or a previous rejected attempt, so a model's "Perfect. I now have
the official documentation." rode straight through as the answer — there is
no separate scratchpad channel to strip it from; `content_text` on the last
AI message *is* the answer (`compile/node_runtime.py`).

The fix is one clause in `BaseAgentNode.PROMPT.output_contract`, rendered
last per `SystemPrompt.render()` so developer `rules` cannot countermand it —
exactly ticket 27's own proposed location, and the layer `CLAUDE.md` says the
developer may never edit.
"""

from __future__ import annotations

from openstategraph.abc.agent import BaseAgentNode


class TestTheOutputContractForbidsNarration:
    def test_the_contract_is_no_longer_blank(self) -> None:
        """Was `""` by design; ticket 27 is why it can no longer be."""
        assert BaseAgentNode.PROMPT.output_contract.strip() != ""

    def test_the_contract_forbids_narrating_the_tool_loop(self) -> None:
        contract = BaseAgentNode.PROMPT.output_contract.lower()
        assert "narrat" in contract or "self-talk" in contract or "thinking" in contract

    def test_the_contract_forbids_referencing_a_previous_attempt(self) -> None:
        contract = BaseAgentNode.PROMPT.output_contract.lower()
        assert "earlier attempt" in contract or "prior attempt" in contract or "retry" in contract

    def test_a_developer_cannot_override_the_contract(self) -> None:
        """`rules` renders before `output_format`, so nothing a developer
        writes can appear after — and win the tie — over the contract."""
        node = BaseAgentNode(name="a1")
        node.prompt = node.prompt.with_rules(
            "Explain your reasoning step by step before answering."
        )
        rendered = node.resolve_prompt()
        assert rendered is not None
        contract_start = rendered.index("<output_format>")
        rules_start = rendered.index("<rules>")
        assert rules_start < contract_start

    def test_the_contract_is_the_last_word(self) -> None:
        node = BaseAgentNode(name="a1")
        rendered = node.resolve_prompt()
        assert rendered is not None
        assert rendered.rstrip().endswith("</output_format>")


class TestOrdinaryContentIsLeftAlone:
    """The narrow-widening rule: an instruction not to narrate must not make
    the *model's actual answer* unparseable or truncated — it is a rule fed
    to the model, not a filter run over its reply. Proven by rendering the
    prompt and confirming ordinary developer rules survive untouched,
    including one that legitimately starts with a word like "Perfect"."""

    def test_developer_rules_that_start_with_perfect_are_preserved_verbatim(
        self,
    ) -> None:
        node = BaseAgentNode(name="a1")
        node.prompt = node.prompt.with_rules(
            "Perfect grammar is required in every answer you give."
        )
        rendered = node.resolve_prompt()
        assert rendered is not None
        assert "Perfect grammar is required in every answer you give." in rendered

    def test_default_rules_are_untouched_by_the_new_contract(self) -> None:
        node = BaseAgentNode(name="a1")
        rendered = node.resolve_prompt()
        assert rendered is not None
        for line in BaseAgentNode.PROMPT.default_rules.splitlines():
            if line.strip():
                assert line in rendered
