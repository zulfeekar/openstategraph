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

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openstategraph.abc.async_doors import ainvoke_model, install_doors
from openstategraph.abc.prompt import UNTRUSTED_INPUT_IS_DATA, SystemPrompt


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
            "to return to the user. You never rewrite it yourself.\n\n"
            # Locked, and locked *here* rather than in the default criteria: the
            # candidate is an upstream node's output, so a fetched page's prose
            # reaches this model verbatim. See `UNTRUSTED_INPUT_IS_DATA`.
            + UNTRUSTED_INPUT_IS_DATA
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
        context: str = "",
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
        # The rubric, then the run-context block (`organisms-first-class/72`) —
        # both generated, both context, and `with_context` drops the empty ones
        # so a grader with neither composes exactly the prompt it always did.
        self.prompt = prompt.with_context(rubric_text, context)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Give every subclass the half of `grade`/`agrade` it did not write.

        `async-first/05`'s substitutability set, answered rather than waived.
        See `abc/async_doors.py` for why the installation happens here and not
        by a `try: await` at the call site.
        """
        super().__init_subclass__(**kwargs)
        install_doors(cls, BaseGrader, [("grade", "agrade")])

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

    #: How much model prose a `reason` may carry. It is read by a person at a
    #: gate deciding whether to send something under their own name, and by the
    #: trace row beside it — both surfaces where four hundred words is a
    #: regression however informative the field has become. The number matches
    #: the bound the no-keyword branch below already applies to a rejection, so
    #: the two paths cannot disagree about what "too long" means.
    REASON_LIMIT: ClassVar[int] = 200

    @staticmethod
    def _condense(text: str) -> str:
        """Model prose as one bounded line, or "" when there is none.

        Whitespace is collapsed rather than preserved because every consumer of
        this field interpolates it into a sentence — *"The grader passed this —
        {reason}"* on the approval card, *"Its last reason: {reason}"* in the
        exhaustion warning — and a newline or a JSON blob breaks the line the
        reader is actually looking at. The ellipsis is deliberate: a truncated
        sentence that does not admit it was truncated reads as a model that
        stopped mid-thought.
        """
        collapsed = " ".join(text.split())
        if len(collapsed) <= BaseGrader.REASON_LIMIT:
            return collapsed
        return collapsed[: BaseGrader.REASON_LIMIT - 1].rstrip() + "\u2026"

    @classmethod
    def _pass_reason(cls, head: str, tail: str) -> str:
        """What an approval says, which until `workflow-gallery` 53 was nothing.

        The `fail` branch read `tail` and the `pass` branch discarded it, so a
        rejection carried the model's reasoning and an approval carried the
        literal `"Grader passed it"` — a restatement of `passed=True` in the one
        place a human is deciding whether to send the text onward.

        **Tolerant in reading**: a model puts its sentence on the next line as
        often as it puts it on the keyword's own (`PASS - the tone is right`),
        so both are read, the next line first because that is the shape the
        output contract asks for. **Strict in trusting**: nothing is invented.
        Only text the model actually wrote after the keyword becomes a reason,
        and `PASS.` — a keyword and punctuation — is treated as having said no
        more than a bare `PASS` did.

        When it said nothing, the constant is honest and stays. It is worded so
        a reader can tell the two apart: *"No reason given"* reports an absence,
        where *"Grader passed it"* read like a sentence and carried none.
        """
        said = cls._condense(tail)
        if not said:
            # Everything after the keyword on its own line. `\w*` because the
            # branch above accepts `pass`, `passed` and `passes` alike.
            remainder = re.sub(r"^pass\w*", "", head.strip(), flags=re.IGNORECASE)
            said = cls._condense(remainder.lstrip(" \t:.,;\u2013\u2014-"))
        return said or "No reason given"

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
            return Verdict(passed=True, reason=self._pass_reason(head, tail))
        if head_l.startswith("fail"):
            detail = tail.strip() or head.strip()
            return Verdict.reject(detail, feedback=detail)

        # Some models answer without the leading keyword.
        if "fail" in text.lower() and "pass" not in text.lower():
            return Verdict.reject(text[:200], feedback=text[:200])

        return Verdict(passed=True, reason="Verdict unclear; passing by default")

    def _verdict_without_a_model(self, candidate: str) -> Verdict | None:
        """The prelude both doors share: facts first, then a model or not.

        Returns a finished verdict when no model call is needed, and `None`
        when one is. Factored out rather than written twice, because the two
        cheap answers here are the family's own subtlety: the deterministic
        checks must run *before* either door reaches a model — a check that
        started costing a thread hop or a coroutine would be a regression — and
        a missing model is a pass rather than a failure, which is a decision an
        async body reimplementing the prelude could quietly invert.
        """
        cheap = self.deterministic_checks(candidate)
        if cheap is not None:
            return cheap
        if self.model is None:
            # No model is not a failure: the deterministic checks passed, and
            # rejecting here would block a workflow for a missing dependency.
            return Verdict(passed=True, reason="No grading model configured")
        return None

    def _judgement_messages(self, candidate: str, question: str) -> list[Any]:
        """The two messages a judgement is, built once for both doors."""
        from langchain_core.messages import HumanMessage, SystemMessage

        return [
            SystemMessage(content=self.resolve_system_prompt(question)),
            HumanMessage(content=candidate),
        ]

    def grade(self, candidate: str, *, question: str = "") -> Verdict:
        """Deterministic checks first, then the model only if needed."""
        settled = self._verdict_without_a_model(candidate)
        if settled is not None:
            return settled

        response = self.model.invoke(self._judgement_messages(candidate, question))
        # `content_text`, never `str(content)`: a block list stringified to a
        # Python repr starts with neither `pass` nor `fail`, so a PASS fell
        # through to "verdict unclear; passing by default" and a FAIL handed
        # the raw repr to the customer as the reason it was rejected.
        return self.normalise(content_text(response.content))

    async def agrade(self, candidate: str, *, question: str = "") -> Verdict:
        """`grade`, awaited. The grader's async door (`async-first/05`).

        Identical in every respect a caller can observe except that the model
        call is awaited: the same deterministic checks run first and still
        answer without touching a model, the same prompt is rendered, and the
        same tolerant `normalise` reads the reply.

        **A cancellation is not a verdict, and this is the family where that
        matters most.** `normalise` passes whatever it cannot read — on purpose,
        so a grader that cannot decide does not discard work an agent did — so
        a cancel laundered into an error string would come back as an
        *approval* and the candidate would ship. Nothing here catches, and
        `asyncio.CancelledError` is a `BaseException`, so a stopped run
        propagates as a stop. Pinned by a test rather than trusted.

        Not on `IGrader`, which is `runtime_checkable`: a member added there
        would un-satisfy every third-party grader at the next `isinstance`, in
        their install, silently.

        A subclass that overrides `grade` and not this method still gets its
        own body honoured here — `__init_subclass__` installs the door.
        """
        settled = self._verdict_without_a_model(candidate)
        if settled is not None:
            return settled

        response = await ainvoke_model(
            self.model, self._judgement_messages(candidate, question)
        )
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
