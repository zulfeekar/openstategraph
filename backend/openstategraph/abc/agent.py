"""The agent ladder: ``IAgent`` → ``AbstractAgentNode`` → ``Base/React/Deep/Custom``.

This mirrors the library's own layering (CLAUDE.md's three-tier table):

| Tier        | Construct                       | Class here        |
| ----------- | ------------------------------- | ----------------- |
| LangGraph   | hand-written ``StateGraph``     | ``CustomGraphNode`` |
| LangChain   | ``create_agent`` (ReAct)        | ``ReactAgentNode``  |
| Deep Agents | ``create_deep_agent``           | ``DeepAgentNode``   |

Two rules the shape enforces:

- **The base holds the minimum.** ``AbstractAgentNode`` owns the three
  resolvers — ``resolve_model`` / ``resolve_prompt`` / ``resolve_middleware``
  — and the one template method that sequences them. A concrete supplies only
  what makes it that tier: which constructor it calls. Nothing else may accrete
  here; a new shared concern is a collaborator (like ``SystemPrompt``), not a
  new base member.

- **``DeepAgentNode`` is a sibling of ``ReactAgentNode``, never a subclass.**
  ``create_deep_agent`` is ``create_agent`` plus a fixed middleware slot
  assembly — the relationship is *data*, so it is expressed as a constructor
  swap, not as inheritance. (An earlier draft had ``DeepAgentNode extends
  ReactAgentNode``; CLAUDE.md records why that was wrong.)

Retry, timeout and caching are **not** here, and must never be: they are
graph-assembly parameters (``add_node`` / ``set_node_defaults``), applied by
the compiler to every node family alike.

**And neither is an async door, which is a finding rather than an oversight.**
``async-first/05`` gave the router, grader and orchestrator ladders an awaitable
twin of the verb that calls a model — ``aclassify``, ``agrade``, ``aplan``.
This ladder has no such verb: ``build()`` *constructs* a Runnable and hands it
back, and the caller awaits ``ainvoke`` on the object it was given. There is no
``self.model.invoke(...)`` anywhere in this module, resolution is arithmetic on
configuration rather than I/O, and an ``abuild()`` would have been public
surface with nothing behind it — a second spelling of a step that never blocks.
Pinned by ``tests/test_the_agent_ladder_needs_no_async_door.py``, because
"nothing to do here" is the claim most likely to stop being true quietly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any, ClassVar, Protocol, runtime_checkable

from openstategraph.abc.middleware import MiddlewareSlotTable
from openstategraph.abc.narration import build_narration_middleware
from openstategraph.abc.prompt import SystemPrompt


@runtime_checkable
class IAgent(Protocol):
    """The contract consumers depend on: a name, and a build to a Runnable."""

    name: str

    def build(self) -> Any: ...


class AbstractAgentNode(ABC):
    """Shared *capability*, never shared *composition*.

    Everything every agent tier needs exactly once: config in, and the three
    resolution steps that turn config into a model, a prompt and a middleware
    list. The composition itself — which constructor — belongs to the concrete
    tier.

    **A node holds its prompt, not its prompt's ingredients**
    (install-experience 19). `default_rules`, `rules`, `skill`, `replace_rules`
    and `context` were five attributes here, and `system_prompt()` reassembled
    a `SystemPrompt` out of them on every call. They are that object's own
    layers, and it already owns the order they compose in, so keeping a second
    copy was keeping one piece of knowledge in two places. What is left is
    `self.prompt`, composed once in `__init__` from the class's `PROMPT`.
    """

    #: The canonical slot order the base owns. Contributors name a slot; they
    #: never say "position 3". Slots the base does not know about flatten
    #: after these, in first-set order.
    SLOT_ORDER: ClassVar[tuple[str, ...]] = (
        # First, and the position is the whole argument: `before_*` hooks run
        # first to last, so screening placed anywhere else would run after
        # another middleware had already acted on the injected text. Optional
        # — the slot is only ever filled when a workflow asked for it and the
        # extra is installed (`openstategraph.injection`).
        "injection-screening",
        "skills",
        "filesystem",
        # After `filesystem`, and the position is an argument
        # (`launch-readiness/143`). It sat second until then, on a preference
        # about hook order: its `before_model` line should announce intent
        # early, and because `after_*` runs last-to-first, sitting early made
        # its `after_model` line land late (`launch-readiness/104`). Half of
        # that argument has since expired — `after_model` is silent by default
        # now, because it is the one hook in the loop that knows nothing worth
        # reporting.
        #
        # What replaced it is a `wrap_tool_call` constraint, and `wrap_*`
        # **nests**: the first middleware in the list wraps all the others. So
        # sitting second put narration *outside* `OffloadMiddleware`, and what
        # it saw of a large tool result was the pointer offload had already
        # substituted — `[offloaded: 48213 chars written to path=...]`. The
        # one moment the run knows something true was being read after another
        # middleware had rewritten it. Inside offload, narration sees the
        # result the tool actually returned and can say what it found; offload
        # still substitutes its pointer for the model, unchanged.
        #
        # It stays after `injection-screening`, which is the one hard
        # constraint here and is security-sensitive.
        "narration",
        "subagents",
        "summarization",
        "limits",
        "patch-tool-calls",
        # Last, and the position is an argument rather than the default it used
        # to be (ticket 46, item 3). `node_runtime` has contributed this slot
        # since deepagents' `RubricMiddleware` was wired up, and the base had
        # never declared it — so it flattened through `MiddlewareSlotTable`'s
        # *unknown-slot* bucket, the place reserved for a third party's slot,
        # landing after `patch-tool-calls` because nobody had said otherwise.
        #
        # It belongs there on purpose. `RubricMiddleware` implements
        # `before_agent` and `after_agent` and nothing else, and `after_*` hooks
        # run **last to first** — so last in this list means its verdict is
        # taken first, on what the agent itself produced, before any later
        # `after_agent` middleware reshapes it. That is the only subject it can
        # act on: the loop's remedy is "agent, revise your answer", and a
        # complaint about somebody else's post-processing is one the agent
        # cannot fix. (It is also, today, the only `after_agent` in this table
        # — summarization is `before_model`, the limits are `before_model` /
        # `after_model`, filesystem and subagents are `wrap_*` — so declaring
        # it changes no flattened list that exists now. What it changes is that
        # a plugin's unknown slot can no longer land in front of it.)
        "rubric",
    )

    def __init__(
        self,
        *,
        name: str,
        model: Any = None,
        tools: Any = (),
        middleware: dict[str, Any] | None = None,
        narrate: bool = True,
    ) -> None:
        self.name = name
        self.model = model
        self.tools = list(tools)
        #: Named slot contributions from config; replacement is by slot name.
        self._middleware_contributions = dict(middleware or {})
        #: Default **on** (`launch-readiness/104`, owner scope decision): a
        #: silent model-driving step is a defect on every node, not an
        #: opt-in per workflow. `False` is the declared way to go quiet — a
        #: recorded decision on the node, never code someone deleted — and a
        #: `middleware={"narration": ...}` contribution still wins either
        #: way, so a package can swap in a sharper narrator without this
        #: flag at all.
        self.narrate = narrate

    # -- the three resolvers: the single places config becomes a thing ----- #

    def resolve_model(self) -> Any:
        return self.model

    def resolve_middleware(self) -> MiddlewareSlotTable:
        """Config contributions into the canonical slot order, replacement by name.

        A tier with slots of its own overrides *this*, merging them before
        ``self._middleware_contributions`` so config still replaces by name.
        There was a separate ``middleware_preset()`` hook for that until
        install-experience 21; it returned ``{}``, no tier ever overrode it —
        ``DeepAgentNode`` differs by constructor, and deepagents assembles its
        own stack internally — and a second named seam onto the same table is
        one more thing to read and one more place the order could be decided.
        """
        table = MiddlewareSlotTable(order=self.SLOT_ORDER)
        # The base's own default filler — "inherit the capability to
        # compose, not the composition": this calls a factory rather than
        # hardcoding an instance, so `_middleware_contributions` below can
        # still replace the slot by name (a sharper narrator, or `None` to
        # go quiet) without touching this method.
        if self.narrate:
            table.set("narration", build_narration_middleware())
        table.merge(self._middleware_contributions)
        return table

    # -- what a concrete tier supplies ------------------------------------ #

    @abstractmethod
    def build_agent(
        self, *, model: Any, tools: list[Any], system_prompt: str | None, middleware: list[Any]
    ) -> Any:
        """Calls this tier's constructor. The only abstract member."""

class BaseAgentNode(AbstractAgentNode):
    """The usable default: a plain ``create_agent`` loop — **and the tier that
    has a prompt**.

    ``_constructor`` is an instance attribute so a test can record the call
    without patching the library, and so a subclass swaps constructors by
    assignment rather than by overriding ``build_agent`` again.

    The prompt machinery lives here rather than on ``AbstractAgentNode``
    (ticket 45). It sat one level up, so ``CustomGraphNode`` — whose own
    docstring says "prompt machinery must never be forced onto this class" —
    inherited ``PROMPT``, ``self.prompt`` and ``resolve_prompt()`` and used
    none of them. That is the Interface Segregation failure CLAUDE.md names in
    its argument against an ``AbstractPromptedNode``, committed one class
    higher than the place it was being argued about.

    The line the base still holds is *capability, not composition*:
    ``resolve_prompt()`` remains the single place config becomes a prompt for
    every tier that has one, and the locked order inside ``SystemPrompt`` is
    still owned by the collaborator rather than by any class in this ladder.
    """

    #: The locked prompt machinery this node type declares, as **one object
    #: rather than three loose strings** (install-experience 19).
    #:
    #: `preamble` and `output_contract` are empty by default — an agent, unlike
    #: a router, legitimately answers free-form, so the base imposes no
    #: contract. A tier or a node type that *does* own machinery overrides this
    #: ClassVar with `AbstractAgentNode.PROMPT.with_defaults(...)` or a fresh
    #: `SystemPrompt`; `SystemPrompt` is frozen, so one shared instance per
    #: class is safe by construction.
    #:
    #: `default_rules` is the bottom rules layer every agent inherits, declared
    #: **once** here rather than copied into each prebuilt document. The bar it
    #: exists to meet is the owner's, and it is about the *node*, not about any
    #: one example: an Agent dropped on a blank canvas, with nothing typed into
    #: its prompt field and nothing wired to its `skill` port, must still
    #: behave. Before this layer, an unconfigured agent had no rules at all and
    #: `resolve_prompt()` returned `None` — which is precisely the state that
    #: let a tool-holding agent answer a database question out of parametric
    #: memory (CLAUDE.md's recorded Ollama finding).
    #:
    #: Deliberately about honesty and tool discipline only. Anything domain-
    #: shaped here would be a fragile base class: it would reach every agent in
    #: every workflow, and a subclass could only append to it. Domain rules
    #: belong in the node's own `rules` or in a wired skill file — the two
    #: layers above this one (`docs/decisions/skill-layer.md`).
    #:
    #: A caller that passes `default_rules=` explicitly (the Worker does)
    #: replaces this layer for that instance.
    PROMPT: ClassVar[SystemPrompt] = SystemPrompt(
        preamble="",
        # Locked, and rendered last (`SystemPrompt.render()`) so nothing a
        # developer writes in `rules` can countermand it — the same seam
        # Router and Grader already use. Was `""` here: "an agent, unlike a
        # router, legitimately answers free-form, so the base imposes no
        # contract" — true of the *shape* of the answer, but silent about
        # what the answer must not contain. That silence is
        # `launch-readiness/27`: a customer-audience answer opened "Perfect.
        # I now have the official documentation." — the model's inner
        # monologue about its own tool loop, published verbatim, because
        # nothing told it not to. `content_text` on the agent's final
        # message *is* the answer (`compile/node_runtime.py`); there is no
        # separate scratchpad channel to strip this from downstream, so the
        # only place to stop it is the instruction the model reads before it
        # writes.
        #
        # This is a different mechanism from `every-workflow-green/19`,
        # which fixed the orchestrator's `_worker` path: a worker with no
        # tools had no way to say it was stuck, so it narrated instead. That
        # fix (`advisor_context`) does not apply here — a plain agent node
        # has no worker/advisor distinction — so this is the same defect
        # *shape* reappearing on a surface 19 never covered, not a
        # regression of it.
        #
        # The fenced-code-block clause is `launch-readiness/35`: `sql-qa`'s
        # own `rules` already asked for "answer the question in one
        # sentence... then state the query", and ~1 in 6 live runs still
        # published the fenced ```sql block with no sentence at all — exit
        # 0, `warnings: []`, and the reader received a query instead of an
        # answer. A package-level rule a model can silently skip belongs
        # exactly nowhere as reliably as the locked contract rendered last,
        # which is why this is here rather than a stronger sentence in
        # `sql-qa/workflow.json`. Kept general — "a fenced code block and
        # nothing else" — because the defect shape is not SQL-specific: any
        # agent that quotes evidence in a fence can equally forget to say
        # the answer it is evidence for.
        output_contract=(
            "Give only your final answer. Do not narrate your tool use, your "
            "reasoning process or your own thinking (\"Let me search\", "
            "\"Perfect, I now have...\") — the reader never sees the tool "
            "loop and that text is not the answer. Do not refer to an "
            "earlier attempt, a prior draft, or that this is a retry or a "
            "correction — answer as if it were the first and only attempt. "
            "Never answer with a fenced code block and nothing else — a "
            "query, a snippet or any other fenced code is evidence for your "
            "answer, not a substitute for it. Always say the answer itself, "
            "in plain language, before any code fence you include."
        ),
        default_rules=(
            "- Answer the question that was asked, and stop there.\n"
            "- Where you hold a tool that can establish a fact, use it. Never answer "
            "from memory what a tool could check, and never state a figure you did "
            "not obtain.\n"
            "- If you cannot answer honestly, say what is missing instead of "
            "approximating it."
        ),
    )

    def __init__(
        self,
        *,
        default_rules: str = "",
        rules: str = "",
        skill: str = "",
        replace_rules: bool = False,
        context: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        #: **This node's prompt, composed once and held** — not five loose
        #: attributes and a method that reassembles them on every call
        #: (install-experience 19). The ingredients that used to live here were
        #: `default_rules`, `rules`, `skill`, `replace_rules` and `context`; all
        #: five are layers of `SystemPrompt`, which already owns the order they
        #: compose in, so keeping a second copy of them on the node was keeping
        #: the same knowledge in two places.
        #:
        #: `default_rules` falls back to the class's layer rather than to
        #: nothing: an agent with no defaults at all is the state that layer
        #: exists to abolish. The caller with its own directive — the Worker —
        #: passes one and replaces it entirely, which is why the fallback is on
        #: the empty string rather than merged.
        prompt = self.PROMPT.with_context(context)
        if default_rules:
            prompt = prompt.with_defaults(default_rules)
        self.prompt = prompt.with_rules(rules, replace_defaults=replace_rules).with_skill(skill)
        from langchain.agents import create_agent

        self._constructor = create_agent

    def resolve_prompt(self) -> str | None:
        """The string the model sees, or ``None`` when nothing is configured.

        ``None`` matters: passing ``system_prompt=""`` to ``create_agent``
        would still *override* the library's own default, which is not what an
        unconfigured node means.

        **In practice it is now never ``None`` for a stock agent**, because
        ``PROMPT.default_rules`` is a layer every agent inherits. That is the
        point of that layer and it reverses an earlier reading of this method:
        "nothing configured" used to mean "defer to the library", and it now
        means "inherit this node type's own minimum". The ``None`` path
        survives for a subclass that deliberately blanks *both* locked
        layers — defaults and the anti-narration output contract
        (``launch-readiness`` 27 made the latter non-empty too) — with a
        fresh ``SystemPrompt(preamble=..., output_contract="")``: a
        hand-written tier whose harness owns its prompt entirely.

        Kept as a method rather than collapsed into ``self.prompt.render()`` at
        the call site, because the locked order — preamble, context, rules,
        output contract last — is the rule this seam exists to enforce, and the
        ``None`` is a second rule the raw render does not express.
        """
        rendered = self.prompt.render()
        return rendered or None

    # -- the template method ---------------------------------------------- #

    def build(self) -> Any:
        """Resolve everything, then let the tier construct. Never overridden
        to change *sequence* — only ``build_agent`` varies."""
        return self.build_agent(
            model=self.resolve_model(),
            tools=self.tools,
            system_prompt=self.resolve_prompt(),
            middleware=self.resolve_middleware().flatten(),
        )

    def build_agent(
        self, *, model: Any, tools: list[Any], system_prompt: str | None, middleware: list[Any]
    ) -> Any:
        kwargs: dict[str, Any] = {"model": model, "tools": tools, "name": self.name}
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        if middleware:
            kwargs["middleware"] = middleware
        return self._constructor(**kwargs)


class ReactAgentNode(BaseAgentNode):
    """The LangChain tier: ``create_agent``, no preset slots.

    Exists as a named tier (rather than using ``BaseAgentNode`` directly) so
    that "react" in a document maps to a class whose meaning cannot drift if
    the base ever grows a different default.
    """


class DeepAgentNode(BaseAgentNode):
    """The harness tier: ``create_deep_agent``.

    A sibling of ``ReactAgentNode`` — same base, different constructor and a
    ``subagents`` pass-through. The deepagents package pre-assembles its own
    middleware stack internally; slots contributed here ride after it via the
    library's ``middleware`` parameter.
    """

    def __init__(
        self,
        *,
        subagents: list[dict[str, Any]] | None = None,
        backend: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        from openstategraph._extras import require_extra

        deepagents = require_extra("deepagents", "deep", "tier='deep' agent nodes")

        self._constructor = deepagents.create_deep_agent
        self.subagents = list(subagents or [])
        #: The store this tier's own `read_file`/`grep`/`glob` read, when a
        #: compiler has one to give (`launch-readiness/111`). **Private on
        #: purpose**: `subagents` is a declaration a document makes and is
        #: read back, while this is a construction detail nothing reads back,
        #: and the public-surface census on this ladder is argued member by
        #: member (`tests/test_public_surface_ceiling.py`) rather than grown
        #: by habit.
        #:
        #: It is the pass-through that makes progressive disclosure and
        #: tool-result offload dereferenceable at all: both hand the model a
        #: path, and without this the harness reads a different store and
        #: finds nothing there — which is a silent wrong answer, not an error.
        self._backend = backend
        #: **What the harness is, said once by the platform**
        #: (`launch-readiness/120`). Everything this tier hands the model that
        #: no other tier does — a virtual filesystem, and an offload seam that
        #: replaces a large tool result with a path — was, until this line,
        #: explained to it by nobody. The pointer says where a result went; the
        #: habit ("re-read it, do not fetch it twice") had no home at all, so
        #: every package author either wrote it themselves, differently, or did
        #: not write it. That is the platform failing to say something once.
        #:
        #: Composed here rather than declared on `PROMPT`, because a ClassVar
        #: cannot be conditional and this text must be. `harness_preamble()`
        #: gates it on `surface_can_dereference` — the *same* condition that
        #: decided whether the middlewares were contributed — so a deep node
        #: whose file tools read a store this seam never wrote to is told
        #: nothing, and `BaseAgentNode.PROMPT.preamble` stays empty for the
        #: tiers with no harness to describe.
        #:
        #: Prepended to whatever preamble the class declares rather than
        #: replacing it: a tier that owns machinery of its own keeps it, and
        #: the harness contract is the outermost fact about the run.
        from openstategraph.abc.deep_tier_offload import (
            DEEP_TIER_FILE_TOOLS,
            harness_preamble,
        )

        harness = harness_preamble(
            tuple(getattr(t, "name", "") for t in self.tools) + DEEP_TIER_FILE_TOOLS,
            shares_backend=self._backend is not None,
            # A fact, not a guess: the compiler contributes this slot only when
            # it actually projected skills into the run's store.
            skills_disclosed="skills" in self._middleware_contributions,
        )
        if harness:
            declared = self.prompt.preamble.strip()
            self.prompt = replace(
                self.prompt,
                preamble=f"{harness}\n\n{declared}" if declared else harness,
            )

    def build_agent(
        self, *, model: Any, tools: list[Any], system_prompt: str | None, middleware: list[Any]
    ) -> Any:
        kwargs: dict[str, Any] = {"model": model, "tools": tools, "name": self.name}
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        if middleware:
            kwargs["middleware"] = middleware
        if self.subagents:
            kwargs["subagents"] = self.subagents
        if self._backend is not None:
            kwargs["backend"] = self._backend
        return self._constructor(**kwargs)


class CustomGraphNode(AbstractAgentNode):
    """The LangGraph tier: the developer already built the graph.

    Holds a user-authored Runnable (a compiled ``StateGraph``, or anything
    with ``invoke``) and returns it untouched — resolution has nothing to
    resolve, which is exactly why prompt machinery must never be forced onto
    this class (CLAUDE.md's argument against ``AbstractPromptedNode``).
    """

    def __init__(self, *, name: str, runnable: Any) -> None:
        super().__init__(name=name)
        self.runnable = runnable

    def build_agent(self, **_kwargs: Any) -> Any:  # pragma: no cover - via build()
        return self.runnable

    def build(self) -> Any:
        if self.runnable is None:
            raise ValueError(
                f"CustomGraphNode {self.name!r} has no runnable — a custom tier "
                "references code in the workflow's functions/, it cannot be blank"
            )
        return self.runnable


def agent_node_for_tier(tier: str) -> type[BaseAgentNode]:
    """The one place a document's ``tier`` string becomes a class.

    Unknown values fall back to ReAct rather than raising: a misconfigured
    tier should degrade to the plainest working agent, not abort a compile.
    ``custom`` also lands here deliberately — a custom graph needs a runnable
    no tier string can supply, so reaching it is a wiring step (the compiler
    resolves the referenced function), never a lookup.
    """
    # Annotated because an inferred dict of two ABCs joins to `ABCMeta`, which
    # is not the return type and would make every caller's `.tier` untyped.
    tiers: dict[str, type[BaseAgentNode]] = {"react": ReactAgentNode, "deep": DeepAgentNode}
    return tiers.get(tier, ReactAgentNode)


__all__ = [
    "IAgent",
    "AbstractAgentNode",
    "BaseAgentNode",
    "ReactAgentNode",
    "DeepAgentNode",
    "CustomGraphNode",
    "agent_node_for_tier",
]
