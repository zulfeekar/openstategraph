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


#: The keys that make a bare JSON object a suggestion rather than data.
#:
#: Both, deliberately. `nodeType` alone appears in documents and in prose about
#: node types; it is `attachTo` — a node id on *this* canvas — that no ordinary
#: answer carries.
_SUGGESTION_KEYS = ("nodeType", "attachTo")

#: A brace-balanced JSON object, so a nested `{...}` does not end the match.
_BARE_OBJECT = re.compile(r"\{(?:[^{}]|\{[^{}]*\})*\}", re.DOTALL)


#: What a model says when nothing in the catalogue fits.
#:
#: `advisor_context` now permits it, and a prompt that permits an answer its
#: parser cannot read is `every-workflow-green` 17 all over again. So the two
#: are written together and this constant is the only spelling of it.
DECLINED = "none"


def _offered(parsed: Any) -> dict[str, Any] | None:
    """The suggestion, or None when the model declined to make one.

    A decline is a *successful* answer: asked to post to Slack with no Slack
    tool in the catalogue, "nothing here does this" is the correct reply, and
    proposing `tool.email-send` because it is nearest is a confident wrong turn
    a developer pays for in a node, an edge and a re-run
    (`every-workflow-green` 29).

    An empty `nodeType` counts as a decline too. A model that has understood
    "there is nothing" and left the field blank has said the same thing, and
    treating that as a malformed suggestion would send it back to guessing.
    """
    if not isinstance(parsed, dict):
        return None
    node_type = str(parsed.get("nodeType") or "").strip()
    if not node_type or node_type.lower() == DECLINED:
        return None
    return parsed


def _split_unfenced(answer: str) -> tuple[str, dict[str, Any] | None]:
    """The same split, for a model that emitted the object without the fence.

    Found live (`every-workflow-green` 15): `classifier-router-qa` answered
    "I don't have a tool that can retrieve real-time information" and then
    printed the raw payload — `{"nodeType": "tool.web-search", "attachTo":
    "agent-world", ...}` — straight into the prose. Two things went wrong at
    once. The developer lost the card, because nothing reached the developer
    channel; and the promise one docstring up, that a customer's answer cannot
    contain one of these, was simply false.

    The tolerance is the same argument `Grader.normalise` makes and the same
    one ticket 13 made for `validate_workflow`: a protocol that only works when
    the model formats it perfectly is a protocol that fails in production.

    **Narrow on purpose.** This product prints JSON as prose constantly — SQL
    result rows, and `workflow-architect` answers with an entire workflow
    document — so an object is taken only when it carries both keys in
    `_SUGGESTION_KEYS`. Everything else is left exactly where the model put it.
    """
    for match in _BARE_OBJECT.finditer(answer):
        try:
            parsed = json.loads(match.group(0))
        except (ValueError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        if not all(key in parsed for key in _SUGGESTION_KEYS):
            continue
        if _offered(parsed) is None:
            # A decline, unfenced. Still stripped from the prose — the raw
            # object is machinery either way, and showing it is the thing this
            # module exists to prevent.
            prose = re.sub(r"\n{3,}", "\n\n", answer.replace(match.group(0), "", 1))
            return (re.sub(r"[ \t]{2,}", " ", prose).strip() or NO_PROSE), None
        prose = re.sub(r"\n{3,}", "\n\n", answer.replace(match.group(0), "", 1))
        prose = re.sub(r"[ \t]{2,}", " ", prose).strip()
        return (prose or NO_PROSE), parsed
    return answer, None


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

    With no fence at all, `_split_unfenced` takes over: a model that emits the
    object bare used to leave it sitting in the prose, which broke the promise
    two paragraphs up in front of a real user (`every-workflow-green` 15).
    """
    match = _FENCE.search(answer)
    if not match:
        return _split_unfenced(answer)
    prose = re.sub(r"\n{3,}", "\n\n", _FENCE.sub("", answer, count=1)).strip()
    if not prose:
        prose = NO_PROSE
    try:
        parsed = json.loads(match.group(1))
    except (ValueError, TypeError):
        return prose, None
    return prose, _offered(parsed)


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


def _closing_brace(text: str, start: int) -> int | None:
    """Index of the `}` that closes the `{` at `start`, or None if unclosed.

    Depth-counted rather than regex-matched, because a suggestion payload is
    flat but the prose around it is not — `workflow-architect` streams whole
    documents, and a nested object must not end the scan early.
    """
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _is_suggestion(candidate: str) -> bool:
    """Whether this object is the capability payload, by the same two keys
    `_split_unfenced` uses. One rule, so the streamed and settled halves of
    the boundary cannot disagree about what a suggestion is."""
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, dict) and all(key in parsed for key in _SUGGESTION_KEYS)


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

    #: How much text may be held while waiting for a `{` to close.
    #:
    #: A suggestion payload is a couple of hundred characters, so this never
    #: bites on the case it exists for. It bites on a model that opens a brace
    #: and never closes it, and on a genuinely enormous JSON answer — and in
    #: both it simply gives up and emits, because withholding a reader's text
    #: indefinitely would be a worse bug than the one being fixed.
    MAX_OBJECT_HOLD = 2000

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
            # An **unfenced** suggestion, which the marker search above cannot
            # see (`every-workflow-green` 15). `split_suggestion` learned to
            # take one out of the settled answer; without this, a customer
            # still watched it arrive token by token first.
            brace = buffer.find("{")
            if brace != -1:
                closed = _closing_brace(buffer, brace)
                if closed is not None:
                    candidate = buffer[brace : closed + 1]
                    out.append(buffer[:brace])
                    if not _is_suggestion(candidate):
                        out.append(candidate)
                    buffer = buffer[closed + 1 :]
                    continue
                if len(buffer) - brace < self.MAX_OBJECT_HOLD:
                    # Undecided. Hold from the brace and wait for more.
                    out.append(buffer[:brace])
                    self._tail = buffer[brace:]
                    return "".join(out)
                # Given up — see `MAX_OBJECT_HOLD`. Emit the brace itself and
                # carry on scanning after it, so a second object later in the
                # same stream is still caught.
                out.append(buffer[: brace + 1])
                buffer = buffer[brace + 1 :]
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
