"""The grader ladder: ``IGrader`` → ``BaseGrader`` → ``Grader``.

Same shape as the router, for the same reason: a grader always has to do the same
things — reach a pass/fail verdict, say *why*, and produce feedback specific
enough to act on — and none of that is domain knowledge. What varies is the
**criteria**.

Two things the base owns that are easy to get wrong if every grader reimplements
them:

**Cheap deterministic checks run before the model.** An empty candidate, a
transported error, a blank result — these are facts, and paying a model to notice
them is slower, costlier and less reliable than looking. The observed failure
modes in the Chinook run were all of this kind. The model is only asked about
judgements a rule cannot express.

**Feedback is the point, not the verdict.** A grader that says "fail" without
saying what to change turns the revise loop into pure cost, because the agent
retries the same thing. So `reason` is mandatory on a rejection and the base
refuses to emit an empty one.

Criteria are **prebuilt and overridable**: a developer inherits defaults that
already work, adds their own on top, or replaces them outright. What they cannot
touch is the output contract — see `SystemPrompt`.
"""

from __future__ import annotations

from openstategraph.messages import content_text

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openstategraph.abc.prompt import SystemPrompt


class Verdict(BaseModel):
    """A grader's decision.

    `feedback` is separate from `reason` on purpose: the reason explains the
    verdict to a human reading a trace, while the feedback is written *for the
    upstream agent* and is what travels back along the revise edge.
    """

    passed: bool
    reason: str = ""
    feedback: str = ""
    #: Which deterministic check rejected it, when one did. Empty for a model
    #: judgement, which makes the two distinguishable in a trace.
    failed_check: str = ""

    @classmethod
    def reject(cls, reason: str, *, check: str = "", feedback: str = "") -> Verdict:
        return cls(
            passed=False,
            reason=reason,
            # Default the feedback to the reason rather than leaving it blank: a
            # rejection with nothing actionable makes the loop pure cost.
            feedback=feedback or reason,
            failed_check=check,
        )


@runtime_checkable
class IGrader(Protocol):
    """The contract consumers depend on."""

    def grade(self, candidate: str, *, question: str = "") -> Verdict: ...


class BaseGrader(ABC):
    """Everything every grader shares, declared once.

    A grader holds its prompt rather than its prompt's ingredients
    (install-experience 19): `criteria`, `skill` and `replace_defaults` were
    three attributes that existed to be reassembled into a `SystemPrompt` on
    every call, and `describe_criteria()` was `return self.criteria.strip()`
    one line under the attribute it read. A stricter grader is a constructor
    argument, which is what "a working grader is a sentence of criteria, not a
    new class" was always supposed to mean.
    """

    #: The locked prompt machinery, as one object (install-experience 19) —
    #: `output_contract` is rendered after the criteria so they cannot
    #: countermand it, and `SystemPrompt.render` is the one place that order is
    #: decided, which is why these belong together rather than loose on the
    #: class.
    #:
    #: `default_rules` here is the prebuilt **criteria**. A developer extends or
    #: replaces them; they are not a blank field, so a grader works before
    #: anyone configures it.
    PROMPT: ClassVar[SystemPrompt] = SystemPrompt(
        preamble=(
            "You are a grader. You judge whether a candidate answer is good enough "
            "to return to the user. You never rewrite it yourself."
        ),
        output_contract=(
            "Reply with PASS or FAIL on the first line. If FAIL, add one short line "
            "saying exactly what to change. Nothing else."
        ),
        default_rules=(
            "- The answer must address the question that was asked.\n"
            "- Figures must come from the supplied data, never invented.\n"
            "- An answer that is empty, truncated or an error is a FAIL.\n"
            # The refusal clause. A grader whose criteria demand evidence —
            # "show the SQL you ran", "cite the source" — measures an honest
            # *decline* against a rule it cannot satisfy, and fails it: a
            # refusal has no query to show. Observed live, exported trace
            # 2026-08-11: an agent with no SQL tool wired answered "I'm unable
            # to determine the top-earning genre without a way to query the
            # database", which is the correct answer; the grader rejected it,
            # the retries returned empty strings, and the run delivered
            # nothing. The *right* answer was in hand on attempt one and the
            # loop destroyed it.
            #
            # It belongs here, in the base's default criteria, for two reasons.
            # It is not domain knowledge — nothing about SQL, sources or
            # figures — so every grader wants it. And criteria are the grader's
            # own language, so this needs no new verdict state, no string
            # matching against "I cannot", and nothing upstream self-reporting
            # a refusal it has every incentive to misreport. Retrying a refusal
            # cannot fix it: the capability is missing, and asking again just
            # spends the budget.
            "- An answer that honestly declines — stating it cannot be produced, "
            "and why — is a PASS. It is a correct answer, not a failed one, and "
            "retrying it cannot make the missing capability appear."
        ),
    )

    def __init__(
        self,
        *,
        criteria: str = "",
        rubric: list[dict[str, Any]] | None = None,
        skill: str = "",
        replace_defaults: bool = False,
        model: Any = None,
    ) -> None:
        self.model = model
        #: Structured rubric rows: {"criterion": str, "required": bool}.
        #: Rendered as a numbered checklist the model must judge row by row —
        #: a failed required row is a revise, with that row as the feedback.
        #: Freeform `criteria` and a rubric compose; neither replaces the other.
        #: Kept as a member because it is *config a caller supplied*, unlike the
        #: criteria text, which is now a layer of the prompt below.
        self.rubric = [r for r in (rubric or []) if str(r.get("criterion") or "").strip()]
        #: **This grader's prompt, composed once and held** (install-experience
        #: 19). `criteria`, `skill` and `replace_defaults` were three attributes
        #: that existed only to be reassembled into a `SystemPrompt` on every
        #: call; they are its rules layers, and the wired skill sits above the
        #: inline criteria under the one extend/replace switch every layer
        #: shares (`docs/decisions/skill-layer.md`).
        #:
        #: The rubric rides as **context, not rules**: it is structure the
        #: machinery renders, and it must survive `replace_defaults` untouched.
        prompt = self.PROMPT.with_rules(
            criteria, replace_defaults=replace_defaults
        ).with_skill(skill)
        rubric_text = self._describe_rubric()
        self.prompt = prompt.with_context(rubric_text) if rubric_text else prompt

    def _describe_rubric(self) -> str:
        """The rubric as a numbered checklist, or "" when none is set.

        Private (install-experience 21): nothing has ever overridden it or
        called it except the composition in `__init__`. The rubric rows are the
        extension point; their rendering is machinery.
        """
        if not self.rubric:
            return ""
        lines = ["Rubric — judge each row explicitly:"]
        for i, row in enumerate(self.rubric, 1):
            marker = "REQUIRED" if row.get("required", True) else "advisory"
            lines.append(f"R{i} [{marker}]: {str(row['criterion']).strip()}")
        lines.append(
            "A failed REQUIRED row means the candidate is rejected; name the "
            "failing row numbers in your reason."
        )
        return "\n".join(lines)

    def deterministic_checks(self, candidate: str) -> Verdict | None:
        """Facts, checked before spending a model call.

        Returns `None` when nothing is obviously wrong and a judgement is needed.
        Override to add domain checks — a subclass usually wants to call
        `super()` first so the cheap universal ones still run.
        """
        text = (candidate or "").strip()
        if not text:
            return Verdict.reject("The answer is empty.", check="empty")
        if text.lower().startswith(("error", "traceback", "exception")):
            return Verdict.reject(f"The step failed: {text[:160]}", check="error")
        return None

    # -- inherited behaviour ---------------------------------------------- #

    def resolve_system_prompt(self, question: str = "") -> str:
        """The string a model sees, in the locked order.

        `question` is the one part of a grader's prompt that is not known at
        construction — it arrives with the candidate being judged — so it is
        layered on here rather than held. Everything else is `self.prompt`.
        """
        prompt = self.prompt
        if question:
            prompt = prompt.with_context(f"The question was:\n{question}")
        return prompt.render()

    def normalise(self, answer: str) -> Verdict:
        """Reads a verdict out of whatever the model said.

        Tolerant for the same reason the router is: a grader that raises on an
        unexpected shape turns a recoverable judgement into a dead run. When the
        answer is unreadable it **passes** — a grader that cannot decide must not
        silently discard a candidate the agent worked for.
        """
        text = (answer or "").strip()
        if not text:
            return Verdict(passed=True, reason="Grader gave no answer; passing by default")

        head, _, tail = text.partition("\n")
        head_l = head.strip().lower()

        if head_l.startswith("pass"):
            return Verdict(passed=True, reason="Grader passed it")
        if head_l.startswith("fail"):
            detail = tail.strip() or head.strip()
            return Verdict.reject(detail, feedback=detail)

        # Some models answer without the leading keyword.
        if "fail" in text.lower() and "pass" not in text.lower():
            return Verdict.reject(text[:200], feedback=text[:200])

        return Verdict(passed=True, reason="Verdict unclear; passing by default")

    def grade(self, candidate: str, *, question: str = "") -> Verdict:
        """Deterministic checks first, then the model only if needed."""
        cheap = self.deterministic_checks(candidate)
        if cheap is not None:
            return cheap

        if self.model is None:
            # No model is not a failure: the deterministic checks passed, and
            # rejecting here would block a workflow for a missing dependency.
            return Verdict(passed=True, reason="No grading model configured")

        from langchain_core.messages import HumanMessage, SystemMessage

        response = self.model.invoke(
            [
                SystemMessage(content=self.resolve_system_prompt(question)),
                HumanMessage(content=candidate),
            ]
        )
        # `content_text`, never `str(content)`: a block list stringified to a
        # Python repr starts with neither `pass` nor `fail`, so a PASS fell
        # through to "verdict unclear; passing by default" and a FAIL handed
        # the raw repr to the customer as the reason it was rejected.
        return self.normalise(content_text(response.content))

    @abstractmethod
    def revise_payload(self, verdict: Verdict) -> dict[str, Any]:
        """What travels back along the `revise` edge.

        Abstract because the shape of a retry is the concrete grader's business —
        and because a typed feedback payload is what makes the cycle legal at all
        (ticket 09). A cycle with nothing flowing back is a cycle with nothing to
        learn from.
        """


class Grader(BaseGrader):
    """The default, and what the editor's Grader node instantiates.

    Almost empty, which is the demonstration: a working grader is a sentence of
    criteria, not a new class.
    """

    def revise_payload(self, verdict: Verdict) -> dict[str, Any]:
        return {"feedback": verdict.feedback, "verdict": verdict.model_dump()}


__all__ = ["BaseGrader", "Field", "Grader", "IGrader", "Verdict"]
