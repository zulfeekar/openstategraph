"""System-prompt composition — a collaborator, not a base class.

Every node that drives a model has the same shape of problem: some of the prompt
is **machinery** the developer must not be able to break, and some is **domain
rules** only they can write. A router must always emit one branch name; a grader
must always emit a verdict; an agent must always call tools before answering.
None of that is domain knowledge, and all of it is deletable if it lives in an
editable textarea.

**Why this is a collaborator and not an `AbstractPromptedNode`.** It would be
natural to give Router, Grader and Agent a common prompted-node ancestor. But
they compile to *different graph constructs* — a conditional edge, a conditional
edge with a feedback port, a node — which makes them different families, and
CLAUDE.md's boundary rule is explicit: a concern needed by two different families
is a collaborator, not a superclass. Pushing it up would start the god base class
that rule exists to prevent, and would force every family to carry a prompt even
when a hand-written `CustomGraphNode` has none.

So each family *composes* one of these. Nothing inherits it.

The ordering rule is the substance of the design:

    preamble  →  context  →  developer rules  →  output contract

**The contract is last, deliberately.** Prompts are order-sensitive the way
middleware is: later instructions win ties. If developer text came last, a rule
like "explain your reasoning" would countermand the output format and every parse
would fail. Their rules shape the *decision*; the base keeps the *shape of the
answer*.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SystemPrompt:
    """An ordered, named prompt assembly.

    Frozen and rebuilt by `with_*` methods rather than mutated, so a node cannot
    accidentally hand a half-configured prompt to a model — and so the assembly
    is inspectable in a test without running anything.
    """

    #: Locked. What this node *is*. Never an editable field.
    preamble: str
    #: Locked, and rendered last so developer text cannot override it.
    output_contract: str
    #: Machine-generated situational detail: the branch list, a table schema,
    #: the rubric. Not authored free-hand, so it is not "rules".
    context: tuple[str, ...] = field(default_factory=tuple)
    #: The one part a developer writes.
    rules: str = ""

    def with_context(self, *sections: str) -> SystemPrompt:
        kept = tuple(s.strip() for s in sections if s and s.strip())
        return SystemPrompt(
            preamble=self.preamble,
            output_contract=self.output_contract,
            context=self.context + kept,
            rules=self.rules,
        )

    def with_rules(self, rules: str) -> SystemPrompt:
        return SystemPrompt(
            preamble=self.preamble,
            output_contract=self.output_contract,
            context=self.context,
            rules=(rules or "").strip(),
        )

    def render(self) -> str:
        """Flattens to the string a model sees. The only place order is decided."""
        parts = [self.preamble.strip(), *self.context]
        if self.rules:
            parts.append(f"Rules:\n{self.rules}")
        parts.append(self.output_contract.strip())
        return "\n\n".join(part for part in parts if part)

    def describe(self) -> dict[str, object]:
        """What the editor shows so a developer can see the whole prompt.

        The locked sections are surfaced read-only rather than hidden: a
        developer writing rules needs to know what the machinery already says,
        or they will duplicate or contradict it.
        """
        return {
            "preamble": self.preamble.strip(),
            "context": list(self.context),
            "rules": self.rules,
            "output_contract": self.output_contract.strip(),
            "editable": ["rules"],
        }


__all__ = ["SystemPrompt"]
