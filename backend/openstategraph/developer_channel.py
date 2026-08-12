"""The ```suggestion fence: one grammar, for the two layers that meet it.

A blocked agent is asked to propose the capability it is missing
(`compile.node_runtime.advisor_context`), and the proposal rides a fenced JSON
block inside the model's own answer — because that is the one channel a model
has. Two layers then have to agree about what that block is:

- the **runtime** writes it (`advisor_context` composes the instruction) and
  must keep it out of the conversation record it later replays into a prompt;
- the **transport** (`api.audience`) splits it out of every answer, for every
  audience, so a customer surface cannot render one.

Before this module the marker lived as a literal in `advisor_context` and as a
regex in `api/audience.py`, which is duplicated *knowledge* — and it could not
be resolved by one importing the other, because `compile/` sits below `api/`
and an upward import is how a layering rule dies. So the grammar lives here,
below both, and each layer imports the part it needs.

`src/view/ask/suggestion.ts` parses the same fence a third time and stays
separate on purpose: its job is *applicability* — validating the parsed object
against the live editor's registry and canvas — not transport. Neither can do
the other's work, and only this one runs on every run.
"""

from __future__ import annotations

import json
import re
from typing import Any

#: The opening marker, on its own. `ProseGuard` needs it separately from the
#: whole-fence pattern because a stream meets it a few characters at a time.
FENCE_OPEN = "```suggestion"
FENCE_CLOSE = "```"

#: Non-greedy, so the first fence wins when a model emits several: it was told
#: to emit one, and the first is the only stable choice.
_FENCE = re.compile(re.escape(FENCE_OPEN) + r"\s*\n(.*?)" + re.escape(FENCE_CLOSE), re.DOTALL)

#: What a reply says when the fence *was* the reply (ticket 22).
#:
#: Observed live on `chinook-assistant`: an agent asked to plot a chart it had
#: no tool for emitted the block and no sentence, the grader passed the run,
#: and `answer` was `""` — a 200 whose one rendered field is blank, on every
#: surface, for every client.
#:
#: The floor sits here rather than in a client because this is where the
#: emptiness is *created*: `_output` already promises the run's answer is never
#: blank, and the split is what can take it back. It says only what is known
#: from having deleted the reply — not which node type would have fixed it,
#: since a customer receives this sentence too.
NO_PROSE = "I could not answer that with the capabilities this workflow currently has."


def split_suggestion(answer: str) -> tuple[str, dict[str, Any] | None]:
    """The prose, and the capability suggestion it carried — separated.

    Called on **every** run before the audience is consulted, which is the
    whole point: the fence leaves `answer` whether or not anyone is entitled
    to see it. A customer's answer therefore cannot contain one, and a model
    that invents a fence unprompted (or is talked into one) only deletes its
    own words — and now says so, rather than saying nothing.

    A fence whose body is not a JSON object is stripped from the prose and
    yields no suggestion. It is still stripped, because a half-written fence
    is machine-facing scaffolding either way and showing it to a customer is
    the thing this exists to prevent — the editor sees the same nothing and
    simply offers no card.
    """
    match = _FENCE.search(answer)
    if not match:
        return answer, None
    prose = re.sub(r"\n{3,}", "\n\n", _FENCE.sub("", answer, count=1)).strip()
    if not prose:
        prose = NO_PROSE
    try:
        parsed = json.loads(match.group(1))
    except (ValueError, TypeError):
        return prose, None
    return prose, parsed if isinstance(parsed, dict) else None


def transcript_text(answer: str) -> str:
    """What a finished turn contributes to the conversation record.

    The write-time half of the boundary (ticket 27). `answer` keeps the fence,
    because the transport still has to route it to the developer channel;
    `messages` — the one channel a *later* model reads — never sees it.

    Filtering here rather than in the readers is the whole decision. There is
    one writer and an open-ended set of readers: the router's history block,
    an agent's payload, a supervisor's instruction, and whatever composes
    context next. A read-time filter is a rule every future reader has to
    remember, and two tickets already exist because one did not.
    """
    prose, _ = split_suggestion(answer)
    return prose


class ProseGuard:
    """Keeps a *streamed* answer free of developer fences, chunk by chunk.

    Splitting the settled answer is not enough on its own, and the test that
    proved it is in `tests/test_audience_boundary.py`: `token` frames carry
    model text **as it is produced**, so a fence reaches a client character by
    character long before any `done` frame exists to be cleaned. `/chat` shows
    those tokens in its thinking pane. A boundary that holds only at the end
    is a boundary a customer can watch being crossed.

    A regex cannot do this, because the marker itself arrives split — ``` in
    one chunk and `suggestion` in the next. So this holds back a tail that is
    still a possible prefix of the marker, emits everything that cannot be,
    and swallows the body once a fence has genuinely opened.

    One instance per streaming text (per node, per message kind); the tail is
    the whole of its state. **Applied for every audience**, like
    `split_suggestion` — one code path, so there is no customer-only branch to
    keep audited.
    """

    def __init__(self) -> None:
        self._tail = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        """The part of `chunk` that is safe to send now (often all of it)."""
        buffer = self._tail + chunk
        out: list[str] = []
        while buffer:
            if self._inside:
                end = buffer.find(FENCE_CLOSE)
                if end == -1:
                    # Still inside the fence. Keep only enough to recognise a
                    # closing marker that straddles this chunk boundary.
                    self._tail = buffer[-(len(FENCE_CLOSE) - 1) :]
                    return "".join(out)
                buffer = buffer[end + len(FENCE_CLOSE) :]
                self._inside = False
                continue
            start = buffer.find(FENCE_OPEN)
            if start != -1:
                out.append(buffer[:start])
                buffer = buffer[start + len(FENCE_OPEN) :]
                self._inside = True
                continue
            # No marker in hand. Emit everything that cannot become one, and
            # hold back the longest suffix that is still a prefix of it — the
            # only reason this class exists rather than a `str.replace`.
            hold = 0
            for size in range(min(len(FENCE_OPEN) - 1, len(buffer)), 0, -1):
                if FENCE_OPEN.startswith(buffer[-size:]):
                    hold = size
                    break
            out.append(buffer[: len(buffer) - hold] if hold else buffer)
            self._tail = buffer[len(buffer) - hold :] if hold else ""
            return "".join(out)
        self._tail = ""
        return "".join(out)


__all__ = [
    "FENCE_CLOSE",
    "FENCE_OPEN",
    "NO_PROSE",
    "ProseGuard",
    "split_suggestion",
    "transcript_text",
]
