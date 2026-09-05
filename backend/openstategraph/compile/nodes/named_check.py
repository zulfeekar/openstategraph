"""What a node that names a package function shares with the next one.

`osg-agent-experience/42`. Two node families now call a function the document
names by its short name: `guard.check` asks *is anything wrong with this*, and
`route.check` asks *which way does this go*. Those are different questions —
one closes a loop, the other opens a fork — so they are different families and
`CLAUDE.md`'s boundary rule applies: what they share is a **collaborator**,
never a common ancestor.

What is genuinely shared is small and worth naming exactly, because everything
else about the two nodes differs:

- the lookup — `function.<name>` in `services.functions`, the same namespace a
  `function.*` node binds through, so a check is written once and can be either;
- the call, whose exceptions become **readable data** rather than a dead run.
  A deterministic function retried reproduces its own failure, so there is
  nothing to gain by raising; `_discovered_function` and `BaseTool.run` already
  answer it this way.

`_BUILT_IN_CHECKS` deliberately does **not** live here. It is `guard.check`'s
alone: every entry takes the evidence as well as the text (`fn(text, state,
model_authored)`), which is a wider signature answering *"did this run retrieve
this number"* — a question about a candidate, not about a destination.
"""

from __future__ import annotations

from typing import Any, Callable


def call_check(fn: Callable[..., Any], *arguments: Any) -> tuple[str, str]:
    """`(what the function answered, what stopped it answering)`.

    At most one of the two is ever non-empty. A raised exception is rendered
    as `TypeError: …` and comes back as the second, which is what turns a
    check that blows up into a routed run with an explanation rather than a
    traceback the caller never sees.

    **Variadic on purpose, and it is the reason this is one function and not
    two.** The two families call their function with different arguments —
    `guard.check` may hand it the run summary as an opt-in second parameter
    (`osg-agent-experience/50`), and its built-ins take the state and the set
    of model-authored nodes — while what happens *around* the call is
    identical. Fixing the arity here would have made the shared thing fit one
    caller and not the other, which is how a collaborator turns into a
    special case.

    Total on the return value as well: a function answering `None`, an
    integer or an object is stringified rather than trusted to be a `str` —
    tolerant in reading. A **falsy** answer is the empty string, so a check
    returning `0` or `None` reads as "answered nothing" rather than as the
    literal `"0"`; that is the reading `guard.check` has always had and the
    one `route.check` needs, since neither has a branch called `0`. Every
    caller still resolves what comes back against a declared set, which is
    the strict half of the rule.
    """
    try:
        returned = fn(*arguments)
    except Exception as exc:  # noqa: BLE001 — errors are data here, by rule
        return "", f"{type(exc).__name__}: {exc}"
    if isinstance(returned, str):
        return returned.strip(), ""
    return ("" if not returned else str(returned).strip()), ""


__all__ = ["call_check"]
