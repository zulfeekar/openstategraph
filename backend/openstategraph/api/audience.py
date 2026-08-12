"""Who a run is for, and what that entitles them to see.

## The finding this exists because of

The rule was the owner's: *"the suggestion of tool or methods should only be
visible to workflow edit users, not customer facing."* Before this module the
rule was held by a **frontend convention** — `src/view/ask/suggestion.ts`
parses a ```suggestion fence out of the answer, and
`api/static/chat.html` has no equivalent, so the customer page simply never
rendered one.

That is not a boundary, and the raw payload proved it. `chinook-assistant`
asked over the customer surface's own request shape, with one boolean added:

    POST /api/runs/stream   {"advisor": true, ...}

    event: done
    data: {"answer": "The current weather in Dublin is sunny …\\n\\n
           ```suggestion\\n{\\"nodeType\\": \\"tool.email-send\\",
           \\"attachTo\\": \\"agent-web\\", …}\\n```", ...}

The developer-only text was **in the `answer` field**, the one field every
customer surface renders. `advisor` was an ordinary request field on the same
endpoint `/chat` posts to, with no gate of any kind, so the boundary was one
DevTools edit deep. And `warnings` — sentences naming node ids, unbound tool
types and mount overrides — rode the customer's `done` frame unconditionally
and `chat.html` printed them in red.

## The seam

Three moves, in order of how much they buy:

1. **A run carries its audience.** One field, `audience`, on `RunRequest` and
   `ResumeRequest`, defaulting to `CUSTOMER`. Nothing is developer-only by
   accident any more; a surface that wants developer content must say so.
   This replaces `advisor`, which is not an additional flag but the same fact
   spelled a second way — and a flag and its audience can disagree, which is
   exactly the failure above (`CLAUDE.md`'s one-declaration rule).

2. **Developer content rides a channel, never the prose.** `done` carries a
   `developer` object, and `answer` is split *unconditionally* — for every
   audience, before the audience is even consulted. A suggestion fence
   therefore cannot appear in a customer answer because no code path puts one
   there, not because the customer's client declines to look. This is also
   what makes the injection angle stop mattering: a model can emit anything
   into its answer, including something shaped like a developer fence, and
   the worst it achieves is deleting its own text. (Deleting *all* of it left
   a blank answer on a 200 — ticket 22 — so the split now leaves a sentence
   behind rather than nothing; see `developer_channel.NO_PROSE`.)

3. **A deployment can cap the ceiling.** `OPENSTATEGRAPH_AUDIENCE=customer`
   in the environment makes `resolve()` refuse to raise any request to
   `DEVELOPER` — so a process that serves only `/chat` cannot be talked into
   developer content by a request at all. Environment rather than config
   file, following `auth.py`: this is a security control, and
   `config_file._reject_secrets` already establishes that such things live
   beside the provider keys.

## What this does **not** claim

There is no per-user authorization here, and this module must not grow one.
`auth.py` is explicit that the shared token answers "is this stranger allowed
in", never "who is this", and says in as many words not to build per-user
authorization on top of it. So an unset `OPENSTATEGRAPH_AUDIENCE` leaves the
audience a client *declaration*, and the enforcement it buys is (2) and (3),
not identity. What changes is that there is now **one function** to give a
real identity check to when identity arrives, instead of five features each
developer-only by their own convention.

## What rides the channel, and what deliberately does not

| Content | Channel | Why |
| --- | --- | --- |
| capability suggestions | developer | proposes an edit to a workflow the customer cannot edit |
| `runtime_warnings` — unbound tools, unresolved functions/subgraphs, mount overrides, discovery failures | developer | authoring diagnostics, naming node ids and tool types; a customer can act on none of it |
| plan warnings | developer | same: findings about the document as an artifact |
| `mermaid` | **both** | `/chat` renders it as its live flow diagram, and `GET /api/workflows/{slug}/graph` already serves it to that page. Moving it here while leaving that endpoint open would be theatre, and it is topology, not guidance. |
| `decisions` / `outputs` / `attempts` | **both** | facts about *this run*, which is the customer's own turn. `/chat`'s trace already shows them frame by frame. |
| a `token` frame's **text** | depends — see `AnswerChannel` | the reply is the customer's; a tool payload, a branch name, a verdict and the echoed question are not. The *frame* still goes to both, emptied and marked `withheld`, because it is the only one that says where a run is mid-node. |

The first three were three separate conventions; they are one declaration
now, and a fourth developer-only feature joins by naming a field here rather
than by inventing a fourth convention. `modelField.ts` and `containerFit.ts`
are this repo's precedents for that move.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from collections.abc import Iterable
from typing import Any

# The fence grammar itself lives one layer down, in
# `openstategraph.developer_channel`, because the runtime needs it too: ticket
# 27 required the conversation record to be written without a fence, and
# `compile/` cannot import `api/` without inverting the layering. Re-exported
# here (rather than left to each caller to find) because this module is where
# every *transport* caller already reaches for the split.
from openstategraph.developer_channel import split_suggestion as split_suggestion

#: Deployment ceiling. Set to `customer` on a process that serves only the
#: customer chat surface and no request can raise itself above it. Unset —
#: the default, and every development stack — means the request decides.
AUDIENCE_ENV = "OPENSTATEGRAPH_AUDIENCE"


class Audience(str, Enum):
    """Who is on the other end of a run.

    `str`-valued so it serialises as itself on the wire and Pydantic accepts
    the literal, rather than the contract carrying an integer nobody can read.
    """

    #: Someone using a shipped workflow. Gets the answer and the run.
    CUSTOMER = "customer"
    #: Someone editing the workflow. Also gets what is wrong with it and what
    #: could be added to it.
    DEVELOPER = "developer"


def ceiling() -> Audience | None:
    """The highest audience this deployment permits, or None for no cap.

    An unrecognised value is a cap of `CUSTOMER` rather than an error or a
    silent pass: the only reason to set this variable is to restrict, so a
    typo must fail closed. A process that meant to be permissive leaves it
    unset.
    """
    raw = os.environ.get(AUDIENCE_ENV, "").strip().lower()
    if not raw:
        return None
    return Audience.DEVELOPER if raw == Audience.DEVELOPER.value else Audience.CUSTOMER


def resolve(requested: Audience | str | None) -> Audience:
    """The audience this run actually gets, request capped by deployment."""
    try:
        asked = Audience(requested) if requested else Audience.CUSTOMER
    except ValueError:
        asked = Audience.CUSTOMER
    cap = ceiling()
    if cap is Audience.CUSTOMER:
        return Audience.CUSTOMER
    return asked


def clean_output(value: Any) -> Any:
    """A settled text value with any developer fence split out of it.

    `None` and non-strings pass through untouched — a frame's `output` is
    `None` for most nodes and the field's meaning must not change shape here.

    Lives beside `split_suggestion` rather than in `streaming.py`, where it
    began, because it is the same rule applied to a different field and **both
    run endpoints owe it**. Ticket 15 found what a private copy costs: the
    streaming endpoint cleaned its accumulated `outputs` map and `/api/runs`
    did not, so the very same question answered over the blocking endpoint
    returned a clean `answer` beside three node outputs carrying the whole
    fence. One declaration, two callers (`CLAUDE.md`'s DRY rule).
    """
    if not isinstance(value, str) or not value:
        return value
    prose, _ = split_suggestion(value)
    return prose


@dataclass(frozen=True)
class AnswerChannel:
    """Which streamed text is the reply, and which is the machinery producing it.

    ## The finding

    Move 2 above split the *settled* answer and, with `ProseGuard`, the fence
    inside streamed prose. Neither reaches the other half of the streaming
    path: `token` frames carried **every** message LangGraph produced, and most
    of them were never the reply at all. QA watched `concierge` on `/chat` and
    read, in the block that becomes the answer, a Chinook schema dump, the
    router's branch name `music_store`, the mounted router's `data_query`, and
    the grader's `FAIL` welded onto the end of a sentence. A run takes 8-70 s,
    so that was the majority of the customer's experience.

    `ProseGuard` was never going to catch it — it polices one marker *inside*
    model prose. This is text that is not prose.

    ## The rule

    Two questions, and a frame must pass both to be the reply:

    | Evidence | Verdict |
    | --- | --- |
    | the message is a tool's result (`kind == "tool"`) | machinery — raw payload, addressed to a model |
    | the emitting node was compiled from a control type | machinery — a branch name, a verdict, the echoed question |
    | any *namespace* segment names such a node | machinery — a `tier: "deep"` router classifies inside its own compiled agent, so the frame's own name is `model` |
    | otherwise | the reply |

    The type knowledge belongs to the compiler and stays there:
    `NodeRuntime.machinery_nodes` declares the names, computed from
    `MACHINERY_NODE_TYPES` and unioned up from every mounted child — a mount
    compiles a second document whose names the parent has never heard of, and
    `data_query` came from exactly there. This module only decides who may
    see it, which is the one thing it is for.

    An empty `machinery` set is not a failure: the `kind` test needs no
    cooperation from the compiler and still removes the largest leak by
    volume, so an ad-hoc caller degrades towards showing prose rather than
    towards a silent mute.
    """

    #: Graph node names — and the canvas ids they were compiled from, since a
    #: `token` frame is reported under whichever of the two is known — whose
    #: streamed text is machinery.
    machinery: frozenset[str] = frozenset()

    def carries(
        self, node: str, kind: str, namespace: Iterable[str] = ()
    ) -> bool:
        """Whether this `token` frame is the reply, and so a customer's to see."""
        if kind == "tool":
            return False
        if node in self.machinery:
            return False
        return not any(str(segment).split(":")[0] in self.machinery for segment in namespace)


@dataclass(frozen=True)
class DeveloperChannel:
    """Everything a finished run knows that only a workflow editor may see.

    Frozen and built once at the end of a run rather than appended to as the
    run goes, because it is answering one question — "what does the developer
    get on this `done` frame" — and a mutable version invites a caller to add
    a field on one path and not the other.
    """

    #: Authoring diagnostics: plan findings plus `runtime_warnings()`.
    warnings: list[str] = field(default_factory=list)
    #: The one capability suggestion this run produced, if any.
    suggestion: dict[str, Any] | None = None

    def payload(self, audience: Audience) -> dict[str, Any]:
        """The frame fragment to merge into `done` — `{}` for a customer.

        Absent rather than empty for a customer, so a client cannot read
        "there were no warnings" out of a frame that was never entitled to
        carry any. `{"developer": {...}}` for a developer, always present so a
        developer client never has to distinguish "no findings" from "an older
        backend".
        """
        if audience is not Audience.DEVELOPER:
            return {}
        return {"developer": {"warnings": list(self.warnings), "suggestion": self.suggestion}}
