"""The four keys that say who a run is *for*, read in exactly one place.

`thread_id`, `session_id`, `user_email` and `workflow_slug` are put into a
run's `configurable` block by the **server** — never by a client, never by a
model (`principal.py`, memory ticket 01). Four separate places used to read
them back out, each with its own `or {}`, its own `str()` and its own idea of
what an absent value is; three readings of one identity are three chances for
one of them to learn a normalisation the others do not, which is the argument
`memory.workflow_scope_slug` already makes in its own docstring one level down.

So: one accessor, and the keys named once. What this module deliberately does
**not** do is normalise. `memory.py` lowercases and substitutes periods
because a Store namespace label forbids them; `prebuilt_session` strips because
a model is about to read the value in a sentence. Those are the callers'
concerns and folding them in here would give every reader the union of every
other reader's rules.

`configurable` is who the run is *for*. `context`
(`compile/run_context.py`) is what the workflow asked its *caller* for. They
are different channels, and the reserved-key refusal that keeps them apart
reads its list from here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

#: `configurable` key -> the label a model sees. Ordered: who, then which
#: conversation, then where — the order a sentence would want them in.
#:
#: **The one place the four run-identity keys are named.**
#: `prebuilt_session` renders them, `compile/run_context` refuses a
#: `settings.context` declaration that tries to claim one, and `run_identity`
#: below reads them. A second list anywhere is a second chance to drift.
RUN_IDENTITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("user_email", "user"),
    ("session_id", "session"),
    ("thread_id", "conversation (thread) id"),
    ("workflow_slug", "workflow"),
)

#: Just the keys, in the same order, for callers that do not want the labels.
RUN_IDENTITY_KEYS: tuple[str, ...] = tuple(key for key, _label in RUN_IDENTITY_FIELDS)


def run_identity(
    config: Mapping[str, Any] | None = None,
    *,
    log: logging.Logger | None = None,
) -> dict[str, str]:
    """Who this run is for: every identity key, as a string, or `{}`.

    With no argument the ambient run config is read — `get_config()`, which
    **raises** when there is no runnable context (a unit test, a tool called
    from a script). That is not an error worth surfacing: *we do not know who
    you are* is a complete answer, and it is spelled `{}`.

    So the two cases ticket 07 separated stay separate, and they are now
    separate for every reader rather than for the one that bothered:

    - `{}` — no config reached this code at all. On the HTTP path that is a
      bug, and `log` is where it says so.
    - a dict whose values are empty strings — config arrived and carries no
      identity. A person who declined to identify is a normal run.

    Values are returned exactly as stored (`str`, never `None`). Normalising
    is the caller's, because each caller normalises for a different consumer.
    """
    if config is None:
        try:
            from langgraph.config import get_config

            config = get_config() or {}
        except Exception as exc:
            if log is not None:
                log.debug("no run config to read the run identity from (%s)", exc)
            return {}
    configurable = config.get("configurable") or {}
    return {key: str(configurable.get(key) or "") for key in RUN_IDENTITY_KEYS}
