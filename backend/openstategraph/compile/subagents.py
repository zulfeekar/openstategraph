"""A deep agent's declared subagents — reading them, and refusing to lie about them.

One reason to change: *what a document says a deep agent may delegate to*.

The library half was measured in `docs/decisions/deep-agent-slots.md` §3 and is
short: a `deepagents.SubAgent` is a dict of strings plus tools, so a
declaration is **data** and rides `workflow.json` with no host-language code in
it (portability guardrail 1). `DeepAgentNode` has carried a `subagents`
pass-through since it was written; until `organisms-first-class/84` nothing
ever filled it, so every deep agent delegated to exactly one anonymous
`general-purpose` worker nobody had configured.

**The failure shape this module exists to avoid** is the one 81 measured next
door: `skills=` against the default `StateBackend` loads nothing and *says
nothing*, so a caller believes a directory was wired. A declaration this module
cannot deliver is therefore never dropped in silence — it becomes a sentence on
`plan.warnings`, which is the channel `validate` prints as PROBLEMS FOUND and
exits non-zero on. Two kinds land there, and both are knowable from the
document alone, before anything runs:

- **malformed** — a row missing the three strings the library requires, or two
  rows claiming one name (`6a812bf`'s precedent: a malformed *declaration* is a
  `plan.warnings` problem, not a `Finding`, because a `Finding` names a
  capability that tried to load and failed);
- **undeliverable** — a well-formed row on a `react` or `custom` tier, where
  there is no `subagents` parameter to reach at all. Well-formed and still
  impossible, which is exactly the case `CLAUDE.md` says must be said at
  compile time rather than shipped as a silent nothing.

Two sentences about isolation must both survive into anything built on this,
because they are both true and they read as a contradiction (executed, and
pinned in `tests/test_a_deep_agent_delegates.py`):

- a subagent **never** sees the parent's message history or graph state — it
  receives a task string and reports a result as a `ToolMessage`;
- the run's **context** *does* cross into a subagent's tools unchanged
  (`a86b4d8`). Isolation is about messages and state; runtime context is a
  third channel.
"""

from __future__ import annotations

from typing import Any

from .fields import _text

#: The field key on an agent node's `data`, shared with the TypeScript field
#: schema (`src/nodes/agent/AgentNode.ts`) and pinned by
#: `tests/test_data_key_contract.py`. Spelled as a **literal at every point of
#: use** below rather than read through this constant: that contract's
#: extractor resolves a literal and *fails* on an indirection, deliberately, so
#: that it cannot quietly stop guarding. The constant is here to be imported by
#: a reader who wants the name, not to be the reader's key.
SUBAGENTS_FIELD = "subagents"

#: The only tier with a `subagents` parameter to reach. `agent_node_for_tier`
#: falls back to ReAct for anything unknown, so anything not this string is a
#: tier that would drop the declaration.
DEEP_TIER = "deep"

#: The name `create_deep_agent` auto-adds unless a caller declares it. Naming a
#: row this is how an author *replaces* the built-in general-purpose worker —
#: which is the only way to change it from a document, since disabling it needs
#: a harness profile this product does not register.
GENERAL_PURPOSE = "general-purpose"

#: `tools` on a row. `inherit` omits the key so the library hands the subagent
#: the parent's tools; `none` passes an empty list. Anything else reads as
#: `inherit`, because a tolerant reader never invents a narrower capability
#: than the author asked for.
TOOLS_INHERIT = "inherit"
TOOLS_NONE = "none"

#: `mode` on a row: the worker's **lifecycle**, and the only thing that differs
#: between the two (`async-first/08`).
#:
#: One field on the existing declaration rather than a second repeatable group,
#: deliberately. A subagent is a subagent either way — a name, a description, a
#: prompt, a tool choice, and the isolation rule — and the only question is
#: whether the parent waits. Two groups would be two sets of validation, two
#: field schemas and two chances for one to learn a rule the other did not.
#:
#: `sync` is the default and the absent value, so every document written before
#: this field existed means exactly what it meant.
MODE_SYNC = "sync"
MODE_ASYNC = "async"


def _rows(value: Any) -> list[dict[str, Any]]:
    """The declared rows, tolerantly — a list of mappings or nothing.

    Takes the *field value*, not the node's `data`, so every caller spells the
    key itself. See `SUBAGENTS_FIELD`.

    A repeatable-group field is a JSON array a user edited, so a scalar, a
    `None` and a list with a string in it all have to reduce to "no usable
    rows" rather than to an exception.
    """
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _mode(row: dict[str, Any]) -> str:
    """A row's lifecycle, tolerantly: anything unrecognised reads as `sync`.

    Tolerant in reading, strict in trusting. A document carrying a `mode` this
    version has never heard of gets the **blocking** worker, which is the answer
    that cannot surprise anyone: it runs, the parent waits, nothing is left
    running after the turn. Widening the other way would start a background
    child on a typo.
    """
    return MODE_ASYNC if _text(row, "mode", MODE_SYNC).strip() == MODE_ASYNC else MODE_SYNC


def declares_subagents(data: dict[str, Any]) -> bool:
    """Whether this node's data carries any subagent row at all.

    The question a *no declaration* path asks, kept separate from
    `subagent_specs` so that "nothing declared" and "everything declared was
    malformed" stay two different facts.
    """
    return bool(_rows(data.get("subagents")))


def subagent_specs(
    data: dict[str, Any], *, mode: str = MODE_SYNC
) -> list[dict[str, Any]]:
    """The well-formed rows of one lifecycle, as `deepagents.SubAgent` dicts.

    `mode` defaults to `sync` so the deep tier's own `subagents=` parameter
    keeps receiving exactly what it received before this field existed — an
    async row is **not** also handed to `create_deep_agent`, or the same worker
    would exist twice under one name with two different lifecycles.

    Malformed rows are **dropped**, not repaired: `subagent_declaration_problems`
    has already named each one on `plan.warnings`, and a repaired row would be a
    worker the author never wrote answering in their product's voice.

    Returns plain dicts rather than importing `deepagents.SubAgent` — this
    module is on the compile path for every document, including the ones with
    no deep tier in them and installations with no `deep` extra.
    """
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _rows(data.get("subagents")):
        name = _text(row, "name").strip()
        description = _text(row, "description").strip()
        prompt = _text(row, "systemPrompt").strip()
        if not name or not description or not prompt or name in seen:
            continue
        seen.add(name)
        # `seen` is filled from *every* well-formed row, not only the matching
        # ones: a duplicate name is a duplicate whichever lifecycle the second
        # row claims, and the problems walk below has already said so.
        if _mode(row) != mode:
            continue
        spec: dict[str, Any] = {
            "name": name,
            "description": description,
            "system_prompt": prompt,
        }
        if _text(row, "tools", TOOLS_INHERIT).strip() == TOOLS_NONE:
            # An empty list is not the same as omitting the key: omitted means
            # "inherit the parent's tools", `[]` means "none of them". The
            # subagent still gets the harness's own filesystem and task tools,
            # which are middleware and not ours to withhold.
            spec["tools"] = []
        specs.append(spec)
    return specs


def _node_problems(node_id: str, data: dict[str, Any]) -> list[str]:
    rows = _rows(data.get("subagents"))
    if not rows:
        return []
    tier = _text(data, "tier", "react").strip() or "react"
    if tier != DEEP_TIER:
        return [
            f'Agent "{node_id}" declares {len(rows)} subagent(s) but its runtime is '
            f'"{tier}" — only the deep agent runtime (create_deep_agent) can delegate, '
            "so none of them will exist at run time. Switch the agent's Runtime to "
            "Deep agent, or remove the subagents."
        ]

    problems: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        name = _text(row, "name").strip()
        where = f'Agent "{node_id}" subagent {index}'
        if name:
            where = f'Agent "{node_id}" subagent "{name}"'
        missing = [
            label
            for label, value in (
                ("a name", name),
                ("a description", _text(row, "description").strip()),
                ("a system prompt", _text(row, "systemPrompt").strip()),
            )
            if not value
        ]
        if missing:
            problems.append(
                f"{where} is missing {', '.join(missing)} — the deep agent runtime "
                "requires all three (the name is what the model delegates to, the "
                "description is how it decides to, and the prompt is the worker "
                "itself). This subagent was not created."
            )
            continue
        if name in seen:
            problems.append(
                f'{where} repeats a name already declared on this agent — a subagent '
                "name is what the model delegates to, so only the first was created."
            )
            continue
        seen.add(name)
    return problems


def subagent_declaration_problems(document: Any) -> list[str]:
    """Every subagent problem in a document, in node order then row order.

    Mirrors `run_context.context_declaration_problems`: one tolerant walk over
    the saved document, returning sentences for `plan.warnings`, never raising.
    """
    if not isinstance(document, dict):
        return []
    problems: list[str] = []
    for node in document.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        data = node.get("data")
        if not isinstance(data, dict):
            continue
        problems.extend(_node_problems(str(node.get("id", "")), data))
    return problems


def async_subagent_specs(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The well-formed **async** rows. The opt-in signal for the slot.

    Named rather than spelled `subagent_specs(data, mode=MODE_ASYNC)` at each
    call site, because "does this agent carry the five async tools" is a
    question the compiler asks in two places and a reader asks in more.
    """
    return subagent_specs(data, mode=MODE_ASYNC)


def declares_async_subagents(data: dict[str, Any]) -> bool:
    """Whether any row asks for a background worker, well-formed or not.

    Kept apart from `async_subagent_specs` for the reason `declares_subagents`
    is kept apart from `subagent_specs`: *nothing declared* and *everything
    declared was malformed* are two different facts, and a warning that says
    the wrong one is a warning nobody can act on.
    """
    return any(_mode(row) == MODE_ASYNC for row in _rows(data.get("subagents")))


__all__ = [
    "SUBAGENTS_FIELD",
    "MODE_ASYNC",
    "MODE_SYNC",
    "GENERAL_PURPOSE",
    "TOOLS_INHERIT",
    "TOOLS_NONE",
    "async_subagent_specs",
    "declares_async_subagents",
    "declares_subagents",
    "subagent_specs",
    "subagent_declaration_problems",
]
