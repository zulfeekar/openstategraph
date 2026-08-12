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

    preamble  →  context  →  developer rules  →  wired skill  →  output contract

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
    #: Prebuilt domain rules the node ships with, so a developer inherits
    #: something that already works instead of a blank field.
    default_rules: str = ""
    #: The one part a developer writes inline, on the node itself.
    rules: str = ""
    #: Whether each supplied layer **adds to** the ones beneath it or
    #: **replaces** them. The layers, bottom to top, are
    #: `default_rules` → `rules` → `skill`.
    #:
    #: Extending is the default because it is the safe direction: a developer
    #: adding a criterion keeps everything the node already knew. Replacing is
    #: explicit, and deliberately possible — prebuilt behaviour that cannot be
    #: overridden is a straitjacket, and someone will eventually need a grader
    #: that ignores our defaults entirely.
    #:
    #: One flag for all three layers, not one per pair: two spellings of
    #: extend/replace on one node is the duplication-of-knowledge defect, and a
    #: developer cannot predict a prompt assembled from two modes. With no skill
    #: wired the meaning is *exactly* what it has always been ("the developer's
    #: rules replace the prebuilt ones"), so documents storing the grader's
    #: `criteriaMode` keep their behaviour unchanged.
    #:
    #: Note what it does **not** reach: the preamble and the output contract are
    #: machinery, never rules, so `replace` cannot break the node's ability to
    #: produce a parseable answer.
    replace_defaults: bool = False
    #: The body of a **wired skill file** — the reusable, shareable form of the
    #: same thing `rules` is. It is a rules layer, never context: it is authored
    #: prose that shapes the decision, and a developer who writes it expects it
    #: to win over the inline text the node happened to ship with. Rendered
    #: *after* `rules` for exactly that reason (later instructions win ties),
    #: and still before the output contract, which nothing may countermand.
    #:
    #: Declared last, though it composes *between* `rules` and the contract:
    #: this dataclass's field order is a positional-construction contract an
    #: adopter may already depend on, and `render()` — not this list — is where
    #: prompt order is decided.
    skill: str = ""

    def with_context(self, *sections: str) -> SystemPrompt:
        kept = tuple(s.strip() for s in sections if s and s.strip())
        return SystemPrompt(
            preamble=self.preamble,
            output_contract=self.output_contract,
            context=self.context + kept,
            # Every field must be carried forward. Because this type is frozen
            # and rebuilt, a forgotten field here silently resets to its default
            # — which is how `with_context` briefly dropped the developer's
            # override and made a `replace` behave like an `extend`.
            default_rules=self.default_rules,
            rules=self.rules,
            skill=self.skill,
            replace_defaults=self.replace_defaults,
        )

    def with_defaults(self, default_rules: str) -> SystemPrompt:
        """The prebuilt rules a node ships with."""
        return SystemPrompt(
            preamble=self.preamble,
            output_contract=self.output_contract,
            context=self.context,
            default_rules=(default_rules or "").strip(),
            rules=self.rules,
            skill=self.skill,
            replace_defaults=self.replace_defaults,
        )

    def with_rules(self, rules: str, *, replace_defaults: bool = False) -> SystemPrompt:
        """The developer's rules, either added to the defaults or replacing them."""
        return SystemPrompt(
            preamble=self.preamble,
            output_contract=self.output_contract,
            context=self.context,
            default_rules=self.default_rules,
            rules=(rules or "").strip(),
            skill=self.skill,
            replace_defaults=replace_defaults,
        )

    def with_skill(self, skill: str) -> SystemPrompt:
        """The body of the skill file wired into this node's `skill` port.

        Deliberately does not take its own mode: `replace_defaults` governs
        every rules layer at once, so a node has one extend/replace switch
        rather than one per layer pair.
        """
        return SystemPrompt(
            preamble=self.preamble,
            output_contract=self.output_contract,
            context=self.context,
            default_rules=self.default_rules,
            rules=self.rules,
            skill=(skill or "").strip(),
            replace_defaults=self.replace_defaults,
        )

    def rule_layers(self) -> tuple[str, ...]:
        """The supplied rules layers, bottom to top. The ordering lives here."""
        return tuple(part for part in (self.default_rules, self.rules, self.skill) if part)

    def effective_rules(self) -> str:
        """What the model actually sees as rules.

        `replace` keeps the **topmost supplied** layer and drops the ones
        beneath it, so a wired skill replaces the node's inline prompt and its
        prebuilt defaults, and — with no skill wired — the inline prompt
        replaces the defaults exactly as it always has.

        Replacing with an *empty* string falls back to the layer below rather
        than producing a node with no rules at all — clearing a field is far
        more often a mistake than a deliberate request for no guidance, and
        that is why the filtering happens before the choice.
        """
        layers = self.rule_layers()
        if not layers:
            return ""
        if self.replace_defaults:
            return layers[-1]
        return "\n".join(layers)

    def render(self) -> str:
        """Flattens to the string a model sees. The only place order is decided."""
        parts = [self.preamble.strip(), *self.context]
        rules = self.effective_rules()
        if rules:
            parts.append(f"Rules:\n{rules}")
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
            "default_rules": self.default_rules,
            "rules": self.rules,
            "skill": self.skill,
            "replace_defaults": self.replace_defaults,
            "effective_rules": self.effective_rules(),
            "output_contract": self.output_contract.strip(),
            # Only these two. Everything else is machinery — `skill` included:
            # its text is authored in a file and arrives over a wire, so the
            # inspector shows it, it is not typed there.
            "editable": ["rules", "replace_defaults"],
        }


__all__ = ["SystemPrompt"]
