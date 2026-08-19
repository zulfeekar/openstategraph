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

from openstategraph.messages import content_text

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from openstategraph.abc.prompt import SystemPrompt


class Classification(BaseModel):
    """A router's decision. A named shape, never free text."""

    branch: str
    #: **Every** branch the answer matched, in the document's declared order.
    #:
    #: Always populated, even in `best` mode where it holds one — so a reader
    #: never has to ask which mode produced it (`every-workflow-green` 27).
    #: `branch` stays the single primary, because `decisions[node_id]` is what
    #: the compiler's conditional edge dispatches on and widening that key
    #: would change control flow (ticket 09 is the record of learning that).
    branches: list[str] = Field(default_factory=list)
    #: Set when the model's answer was unusable and the fallback was taken.
    fell_back: bool = False
    reason: str = ""

    def model_post_init(self, _context: Any) -> None:
        # One place fills it, so no construction site can forget and hand a
        # caller an empty list that means "one branch" somewhere else.
        if not self.branches:
            object.__setattr__(self, "branches", [self.branch])


class Branch(BaseModel):
    """One branch: a stable ``id`` for wiring and a human ``name`` for the model.

    The editor's edges point at ``branch:<id>`` ports (ticket 20 — ids survive
    renames), so the conditional edge dispatches on the **id**. The model can
    only classify by **name** — ``b1-data`` is opaque where ``data_query`` is
    not. The two must never be conflated: the id belongs to the graph, the name
    belongs to the prompt, and this pair is the only place both live together.
    """

    id: str
    name: str

    @classmethod
    def of(cls, value: "str | dict[str, Any] | Branch") -> "Branch":
        """Accepts every historical spelling of a branch.

        - v1 documents stored a bare name (``"greeting"``) — id and name are
          the same string, which is exactly why v1 files kept routing.
        - v2 documents store ``{"id": ..., "name": ...}``; a missing half
          borrows the other, so a hand-written mapping stays convenient.
        """
        if isinstance(value, Branch):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError("A branch needs a name")
            return cls(id=text, name=text)
        raw_id = str(value.get("id") or "").strip()
        raw_name = str(value.get("name") or "").strip()
        if not raw_id and not raw_name:
            raise ValueError("A branch needs an id or a name")
        return cls(id=raw_id or raw_name, name=raw_name or raw_id)


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

    Subclasses supply `rules` and nothing else. The prompt assembly, the branch
    validation and the fallback are inherited behaviour, not copied code.

    There was a `describe_rules()` override point here until
    install-experience 19; it was `return self.rules.strip()`, one line under
    the attribute it read, and nothing in the repository overrode it except a
    test written to show that it could be. A subclass that wants richer rules
    passes them to `super().__init__(rules=…)`, which is also the demonstration
    this ladder exists to make: a new kind of router is *configuration*.
    """

    #: The locked prompt machinery, as one object (install-experience 19).
    #: None of it is exposed as an editable field anywhere in the UI, because a
    #: developer who deletes it gets a router that cannot be parsed.
    #:
    #: `output_contract` is rendered *after* the developer's rules so it cannot
    #: be countermanded by them — `SystemPrompt.render` owns that order, which
    #: is precisely why the three strings belong to one object rather than
    #: sitting loose on the class for each caller to combine.
    #:
    #: `default_rules` is the bottom rules layer, so a router with an empty
    #: `rules` field and no wired skill still classifies on something better
    #: than the branch names. That layer was **described but not built**:
    #: `docs/decisions/skill-layer.md` names three rules layers —
    #: `default_rules` → `rules` → `skill` — for all five model-driven
    #: families, and `system_prompt()` never called `.with_defaults()`, so a
    #: router had two. The gap was invisible while every shipped router carried
    #: a long inline `rules` string; it stops being invisible the moment a
    #: developer drops a bare Router on a canvas, which is exactly what "works
    #: out of the box" has to survive.
    #:
    #: Generic on purpose — how to *decide*, never what the branches mean. The
    #: branch list is context, and the branch semantics are the developer's
    #: `rules`.
    PROMPT: ClassVar[SystemPrompt] = SystemPrompt(
        preamble=(
            "You are a router. Your only job is to decide which single branch a "
            "message belongs to. You never answer the message itself. When a "
            "conversation is shown, classify the NEW message in its light: a "
            "follow-up about a previous answer (how did you get it, explain, "
            "why, tell me more) belongs to the branch that produced that "
            "answer, not to whichever branch the follow-up's words resemble."
        ),
        output_contract=(
            "Reply with exactly one branch name from the list above. "
            "No punctuation, no explanation, no quotes — the branch name alone."
        ),
        default_rules=(
            "- Decide from what the message NEEDS, not from how it is phrased.\n"
            "- Exactly one branch. If two fit, take the more specific one.\n"
            "- Never answer the message, and never invent a branch name."
        ),
    )

    #: The same machinery, for `match_mode="all"`.
    #:
    #: A separate `ClassVar` rather than string surgery on `PROMPT`, because
    #: both are **locked sections** — a developer cannot edit either, and the
    #: one thing worse than a wrong contract is one assembled at runtime from
    #: two half-sentences nobody can read in the source.
    #:
    #: The parser and the prompt must agree. `every-workflow-green` 17 is the
    #: record of them disagreeing: the orchestrator's prompt taught the model a
    #: shape its own parser could not read, and every subtask fell to the
    #: default worker. So a mode that accepts several names has to ask for
    #: several names.
    PROMPT_ALL: ClassVar[SystemPrompt] = SystemPrompt(
        preamble=(
            "You are a router. Your only job is to decide which branches a "
            "message belongs to. You never answer the message itself. A message "
            "often asks more than one thing — name every branch it needs, not "
            "just the closest one. When a conversation is shown, classify the "
            "NEW message in its light: a follow-up about a previous answer "
            "(how did you get it, explain, why, tell me more) belongs to the "
            "branch that produced that answer, not to whichever branch the "
            "follow-up's words resemble."
        ),
        output_contract=(
            "Reply with every branch name from the list above that the message "
            "needs, separated by commas. Most messages need one. "
            "No punctuation beyond the commas, no explanation, no quotes — the "
            "branch names alone."
        ),
        default_rules=(
            "- Decide from what the message NEEDS, not from how it is phrased.\n"
            "- Name a branch only if the message genuinely needs it. Two is "
            "common for a compound question; naming all of them is almost "
            "always wrong."
        ),
    )

    def __init__(
        self,
        branches: "list[str | dict[str, Any] | Branch]",
        *,
        fallback: str | None = None,
        rules: str = "",
        skill: str = "",
        replace_rules: bool = False,
        model: Any = None,
        match_mode: str = "best",
    ) -> None:
        if not branches:
            raise ValueError("A router needs at least one branch")
        #: `"best"` — one destination, the historical and default behaviour.
        #: `"all"` — every branch the question matched, run in parallel.
        #:
        #: Opt-in on purpose. Routing one ticket to one desk is a real pattern
        #: that `support-triage` depends on, and broadcasting would multiply
        #: model cost by the branch count. An unrecognised value is treated as
        #: `"best"`, because a typo in a config field must not silently
        #: broadcast (`every-workflow-green` 27).
        #: Private: it is constructor configuration that only `normalise`
        #: reads, and a public attribute here would grow this class's surface
        #: for nothing — the ceiling test caught exactly that.
        self._match_mode = "all" if match_mode == "all" else "best"
        #: The full id/name table. `self.branches` below stays `list[str]`
        #: (names) so `IRouter` and every prompt-side consumer are untouched.
        self.branch_table = [Branch.of(entry) for entry in branches]
        self.branches = [branch.name for branch in self.branch_table]
        self._ids_by_name = {branch.name: branch.id for branch in self.branch_table}
        names_by_id = {branch.id: branch.name for branch in self.branch_table}
        # A fallback may arrive as a name or (from the canvas `fallback` field)
        # as an id; normalise to the name. Default to the last branch rather
        # than raising: a router with an unusable fallback is worse than one
        # with an arbitrary but valid one.
        resolved = names_by_id.get(fallback or "", fallback)
        self.fallback = resolved if resolved in self.branches else self.branches[-1]
        self.model = model
        #: **This router's prompt, composed once and held** — the branch list
        #: as context, the developer's `rules` and the wired skill's body as
        #: rules layers over the class's defaults, governed by the one
        #: extend/replace switch every layer shares
        #: (`docs/decisions/skill-layer.md`).
        #:
        #: Held rather than reassembled per call (install-experience 19). The
        #: branch list is fixed at construction — `branch_table` is built above
        #: and never mutated — so a method that rebuilt this on every
        #: `classify()` was rebuilding a constant.
        self.prompt = (
            (self.PROMPT_ALL if self._match_mode == "all" else self.PROMPT)
            .with_context(self._describe_branches())
            .with_rules(rules, replace_defaults=replace_rules)
            .with_skill(skill)
        )

    def route_key(self, name: str) -> str:
        """The graph-side key for a classified branch name.

        This is what the compiler's conditional edge dispatches on — the
        ``branch:<id>`` port id with its prefix stripped. An unknown name is
        passed through untouched rather than raised on: the caller's own
        fallback handling stays in charge of what a misroute means.
        """
        return self._ids_by_name.get(name, name)

    def _describe_branches(self) -> str:
        """How the branch list is presented.

        Private: it was public as an override point "rarely worth overriding",
        and in the whole repository nothing has ever overridden or called it
        except `system_prompt()` one screen below (install-experience 21). A
        public member with one internal caller is surface an adopter has to
        read past to find the one thing this class asks them to write, which is
        `rules`.
        """
        lines = []
        for name in self.branches:
            marker = "  (used when nothing else matches)" if name == self.fallback else ""
            lines.append(f"- {name}{marker}")
        return "Branches:\n" + "\n".join(lines)

    # -- inherited behaviour ---------------------------------------------- #

    def resolve_system_prompt(self) -> str:
        """The string a model sees, in the locked order.

        `SystemPrompt` is **composed, not inherited** — Router, Grader and Agent
        compile to different graph constructs, so they are different families, and
        CLAUDE.md says a cross-family concern is a collaborator. A shared
        `AbstractPromptedNode` would be the beginning of a god base class and
        would force a prompt onto `CustomGraphNode`, which has none.

        `self.prompt` is the structure, and it is public for the reason this
        method is not the only thing that wants it: the editor renders the
        locked sections read-only beside the one editable field, which is how a
        developer knows what the machinery already says instead of duplicating
        it.
        """
        return self.prompt.render()

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
        #
        # Declared order, not the order the model happened to mention them in:
        # a reader can predict the document's order and cannot predict a
        # model's sentence.
        matches = [name for name in self.branches if name.lower() in cleaned]
        if len(matches) == 1:
            return Classification(branch=matches[0], reason="Found in a longer answer")

        # Several matched. In `best` mode that is ambiguity and falls through
        # to the fallback below, exactly as it always has. In `all` mode it is
        # the answer: a compound question — "what do you know about music? what
        # is your skill?" — genuinely belongs to two desks, and running one and
        # dropping the rest is what this mode exists to stop
        # (`every-workflow-green` 27).
        if len(matches) > 1 and self._match_mode == "all":
            return Classification(
                branch=matches[0],
                branches=matches,
                reason=f"Matched {len(matches)} branches",
            )

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
        # See `openstategraph.messages`: a stringified block list is a repr,
        # which matches no branch name and falls back to the default branch
        # without saying so.
        return self.normalise(content_text(response.content))

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
        # Same widened element type as `BaseRouter` — narrowing it to `list[str]`
        # here was a Liskov violation the type checker caught: the base accepts
        # `Branch` objects and dicts, and this subclass forwards them verbatim.
        branches: "list[str | dict[str, Any] | Branch]",
        *,
        fallback: str | None = None,
        rules: str = "",
        skill: str = "",
        replace_rules: bool = False,
        model: Any = None,
        match_mode: str = "best",
        destinations: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            branches,
            fallback=fallback,
            rules=rules,
            skill=skill,
            replace_rules=replace_rules,
            model=model,
            match_mode=match_mode,
        )
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
