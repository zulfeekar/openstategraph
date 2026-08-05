"""The router ladder: ``IRouter`` → ``BaseRouter`` → ``Router``.

The point of the ladder is that **a developer never rewrites the machinery**. A
router always has to do the same three things — emit exactly one branch name,
choose from a known list, fall back when nothing matches — and none of that is
domain knowledge. What varies is only the *rules*: "if it mentions revenue or
tables it is a dataquery, if it is a greeting say greeting."

So the base owns the contract and the concrete supplies the rules. Adding a new
kind of router should mean writing a sentence, not a class.

The composition rule, which is the part that is easy to get wrong:

    system prompt = LOCKED preamble  +  developer rules  +  LOCKED output contract

**The contract goes last on purpose.** Prompts are order-sensitive in the same
way middleware is (ticket 08): later instructions win ties. If the developer's
text came last they could countermand the output format — "explain your
reasoning" — and every classification would fail to parse. Putting the contract
after their text means their rules shape the *decision* while the base keeps
control of the *shape of the answer*.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from dyflow.abc.prompt import SystemPrompt


class Classification(BaseModel):
    """A router's decision. A named shape, never free text."""

    branch: str
    #: Set when the model's answer was unusable and the fallback was taken.
    fell_back: bool = False
    reason: str = ""


@runtime_checkable
class IRouter(Protocol):
    """The contract consumers depend on.

    A `Protocol`, so a hand-written classifier can satisfy it without inheriting
    from us — the interface describes a shape, and demanding inheritance to
    participate is what closes a hierarchy for extension.
    """

    branches: list[str]
    fallback: str

    def classify(self, question: str) -> Classification: ...


class BaseRouter(ABC):
    """Everything every router shares, declared exactly once.

    Subclasses supply `rules` (or override `describe_rules`) and nothing else.
    The prompt assembly, the branch validation and the fallback are inherited
    behaviour, not copied code.
    """

    #: Locked. Not exposed as an editable field anywhere in the UI, because a
    #: developer who deletes it gets a router that cannot be parsed.
    PREAMBLE: ClassVar[str] = (
        "You are a router. Your only job is to decide which single branch a "
        "message belongs to. You never answer the message itself."
    )

    #: Locked, and appended *after* the developer's rules so it cannot be
    #: countermanded by them.
    OUTPUT_CONTRACT: ClassVar[str] = (
        "Reply with exactly one branch name from the list above. "
        "No punctuation, no explanation, no quotes — the branch name alone."
    )

    def __init__(
        self,
        branches: list[str],
        *,
        fallback: str | None = None,
        rules: str = "",
        model: Any = None,
    ) -> None:
        if not branches:
            raise ValueError("A router needs at least one branch")
        self.branches = list(branches)
        # Default to the last branch rather than raising: a router with an
        # unusable fallback is worse than one with an arbitrary but valid one.
        self.fallback = fallback if fallback in self.branches else self.branches[-1]
        self.rules = rules
        self.model = model

    # -- the parts a subclass may shape ----------------------------------- #

    def describe_rules(self) -> str:
        """The domain rules. Overridable, but a string is usually enough.

        This is the whole extension point. A `SupportRouter` that wants richer
        rules overrides this; a developer configuring a node in the editor just
        sets `rules`.
        """
        return self.rules.strip()

    def describe_branches(self) -> str:
        """How the branch list is presented. Rarely worth overriding."""
        lines = []
        for name in self.branches:
            marker = "  (used when nothing else matches)" if name == self.fallback else ""
            lines.append(f"- {name}{marker}")
        return "Branches:\n" + "\n".join(lines)

    # -- inherited behaviour ---------------------------------------------- #

    def system_prompt(self) -> SystemPrompt:
        """The assembled prompt, as a structure rather than a string.

        `SystemPrompt` is **composed, not inherited** — Router, Grader and Agent
        compile to different graph constructs, so they are different families, and
        CLAUDE.md says a cross-family concern is a collaborator. A shared
        `AbstractPromptedNode` would be the beginning of a god base class and
        would force a prompt onto `CustomGraphNode`, which has none.

        Returning the structure lets the editor render the locked sections
        read-only beside the one editable field, which is how a developer knows
        what the machinery already says instead of duplicating it.
        """
        return (
            SystemPrompt(preamble=self.PREAMBLE, output_contract=self.OUTPUT_CONTRACT)
            .with_context(self.describe_branches())
            .with_rules(self.describe_rules())
        )

    def resolve_system_prompt(self) -> str:
        """The string a model sees."""
        return self.system_prompt().render()

    def normalise(self, answer: str) -> Classification:
        """Turns whatever the model said into a valid branch.

        Tolerant on purpose. A router is the entry point, so a strict parse that
        raises is a total outage — and the observed failure of
        `response_format` in the Chinook run was exactly that. Matching
        leniently and falling back is always recoverable; a misroute is not an
        outage.
        """
        cleaned = answer.strip().strip("\"'`.,").lower()
        if not cleaned:
            return Classification(
                branch=self.fallback, fell_back=True, reason="Empty answer"
            )

        for name in self.branches:
            if cleaned == name.lower():
                return Classification(branch=name, reason="Exact match")

        # A chatty model wraps the name in a sentence; find it anyway rather
        # than discarding a decision that was actually made.
        matches = [name for name in self.branches if name.lower() in cleaned]
        if len(matches) == 1:
            return Classification(branch=matches[0], reason="Found in a longer answer")

        return Classification(
            branch=self.fallback,
            fell_back=True,
            reason=(
                f"Ambiguous answer matched {len(matches)} branches"
                if matches
                else f"Answer {answer.strip()[:60]!r} matched no branch"
            ),
        )

    def classify(self, question: str) -> Classification:
        """Runs the classification. Subclasses rarely need to touch this."""
        if self.model is None:
            return Classification(
                branch=self.fallback, fell_back=True, reason="No model configured"
            )

        from langchain_core.messages import HumanMessage, SystemMessage

        response = self.model.invoke(
            [
                SystemMessage(content=self.resolve_system_prompt()),
                HumanMessage(content=question),
            ]
        )
        content = response.content
        text = content if isinstance(content, str) else str(content)
        return self.normalise(text)

    @abstractmethod
    def compile_path_map(self) -> dict[str, str]:
        """The router's complete declared destination set.

        Abstract because only a concrete router knows what its branches connect
        *to* — the editor supplies that from the canvas wiring. Ticket 03: a
        renderer with no declared destination set has to assume the router might
        reach any node.
        """


class Router(BaseRouter):
    """The default, and the one the editor's Router node instantiates.

    Deliberately almost empty. Everything it does is inherited — which is the
    demonstration: a working router is a branch list plus a sentence of rules,
    not a new class.
    """

    def __init__(
        self,
        branches: list[str],
        *,
        fallback: str | None = None,
        rules: str = "",
        model: Any = None,
        destinations: dict[str, str] | None = None,
    ) -> None:
        super().__init__(branches, fallback=fallback, rules=rules, model=model)
        #: branch name -> graph node name, taken from the canvas wiring.
        self.destinations = destinations or {}

    def compile_path_map(self) -> dict[str, str]:
        """Maps each branch to the node its edge lands on.

        Unwired branches are omitted rather than pointed at `END`, so a
        half-wired router is visible as a missing destination instead of
        silently terminating a run.
        """
        return {
            branch: self.destinations[branch]
            for branch in self.branches
            if branch in self.destinations
        }


__all__ = ["BaseRouter", "Classification", "Field", "IRouter", "Router"]
