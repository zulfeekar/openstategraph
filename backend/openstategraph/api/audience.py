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
| **that** a capability was lost — `CAPABILITY_NOTICE`, appended to `answer` | **both**, differently | ticket 51. The sentences above stay developer-only; *the fact* cannot, because the alternative is a customer reading a degraded answer as a confident one and concluding the product does not know things. A developer gets the list and no notice; a customer gets the notice and no list. It rides `answer` rather than a field of its own for a hard reason as well as a soft one — a customer `done` frame may not carry a `warnings` key at all (see `payload` below, and the test that requires it *absent*), and `answer` is the one field every customer client already renders. |
| guardrail `redactions` — counts and entity types per node, never values | developer | a customer must not be told what was removed from their own answer, and the developer needs to know the machinery rewrote it |
| `statements` — what the run executed, with the tool that ran it and what came back | developer | `one-chinook-honest/30`. The evidence behind an answer, quoting node ids, tool names and a customer's own literal values. No credential can reach it: only an argument recognised as a *statement* is ever recorded, never the argument map (`executed_statements`) |
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
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# The fence grammar itself lives one layer down, in
# `openstategraph.developer_channel`, because the runtime needs it too: ticket
# 27 required the conversation record to be written without a fence, and
# `compile/` cannot import `api/` without inverting the layering. Re-exported
# here (rather than left to each caller to find) because this module is where
# every *transport* caller already reaches for the split.
from openstategraph.compile.reducers import RESET
from openstategraph.compile.state import customer_visible_channels
from openstategraph.developer_channel import capability_gap as capability_gap
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


def deployment_audience() -> Audience:
    """The audience for a door whose caller cannot be trusted to name one.

    `resolve()` is for a transport with a **client declaration** to cap — the
    HTTP run doors, where a first-party surface says which of itself it is.
    The MCP run door has no such client: the thing filling in the arguments is
    a customer's own model, and an audience a model can name is the `advisor`
    flag respelled — the boolean on the customer's own endpoint that put this
    boundary one DevTools edit away, and that this module exists to have
    deleted (`the-boundary-nobody-checked/08`).

    So the deployment declares it, once, in the same variable that caps every
    other door. `ceiling()` already fails closed on a typo; this puts the floor
    under its `None`. **Unset is `CUSTOMER`** — for a caller who cannot name an
    audience, the absence of a permission is not a permission, which is the
    direction `visible_state` already takes for an unmarked channel. An MCP
    deployment that is an authoring workbench sets `OPENSTATEGRAPH_AUDIENCE=developer`
    and a person can see, change and revoke that.
    """
    return ceiling() or Audience.CUSTOMER


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


def visible_state(values: Mapping[str, Any], audience: Audience) -> dict[str, Any]:
    """The state channels this audience may read, out of a run's own state.

    **The seam for every door that publishes raw state**, and the third of its
    kind here for the reason the other two give: `clean_output` and
    `redaction_report` exist because a rule applied at one door and not at the
    next is not a rule (ticket 15). `the-boundary-nobody-checked/02` found the
    same shape one surface further out — `GET /api/threads/{id}` published
    every checkpointed channel, including `tool_use` and `redactions`, to
    whoever asked.

    A developer gets what is there. A customer gets only the channels
    `compile/state.py` marks `CUSTOMER_VISIBLE` — **the declaration lives on
    the channel**, so this function holds no list of its own and cannot drift
    from one. A channel this build has never heard of (a mounted child's, an
    older checkpoint's, a future release's) is unmarked and therefore refused,
    which is the direction a boundary has to fail in.
    """
    if audience is Audience.DEVELOPER:
        return dict(values)
    allowed = customer_visible_channels()
    return {key: value for key, value in values.items() if key in allowed}


def visible_channel_names(names: Iterable[str], audience: Audience) -> list[str]:
    """`visible_state` for a list of channel *names*, order preserved.

    A checkpoint's `updated_channels` is names without values, and a name is
    the disclosure there — *this step wrote `redactions`* tells a customer the
    machinery rewrote their answer, which is precisely what
    `DeveloperChannel.redactions` exists to keep on the other side.
    """
    if audience is Audience.DEVELOPER:
        return [str(name) for name in names]
    allowed = customer_visible_channels()
    return [str(name) for name in names if str(name) in allowed]


def redaction_report(state_value: Any) -> list[dict[str, Any]]:
    """`state["redactions"]` flattened into the channel's shape.

    The runtime keys its rows by node id because that is what a merge reducer
    needs; a reader wants a flat list with the node named on each row. One
    declaration here for the reason `clean_output` is here: **both** run
    endpoints owe it, and ticket 15 measured what a private copy costs when
    only one of two doors applies the rule.

    Defensive about the shape rather than trusting it — this reads a state
    key that a mounted child, a stub graph or an older checkpoint may not
    have written at all — and it copies only the four fields it knows, so a
    future row carrying more cannot widen the channel by accident.
    """
    if not isinstance(state_value, dict):
        return []
    report: list[dict[str, Any]] = []
    for node_id, rows in state_value.items():
        if node_id == RESET or not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            report.append(
                {
                    "node": str(node_id),
                    "entity": str(row.get("entity", "")),
                    "strategy": str(row.get("strategy", "")),
                    "count": int(row.get("count", 0) or 0),
                }
            )
    return report


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
    #: What the run said it needed when **nothing in the library provides it**
    #: — the description a new, workflow-scoped module would be built from
    #: (`every-workflow-green` 34).
    #:
    #: Separate from `suggestion` because they open different doors: one places
    #: a tool that already exists, the other starts an interview. Collapsing
    #: them would make a card that cannot tell the user which of the two is
    #: about to happen.
    #:
    #: Developer only, like `suggestion`, and for the same reason — a customer
    #: is never offered a tool, and is never told what the canvas lacks.
    #:
    #: The `noqa` is a **false positive silenced, not a defect hidden**. Ruff
    #: reads this as redefining the module-level `capability_gap` re-export at
    #: the top of the file; a class body is its own scope, so it does no such
    #: thing, and both bindings work. Neither can be renamed to make the linter
    #: quieter — the function is a published re-export and this field is on the
    #: `done` frame every developer client reads. Both are pinned in
    #: `tests/test_two_capability_gaps_share_one_name.py`, which is what keeps
    #: this line safe to leave silent (`organisms-first-class` 47).
    capability_gap: str | None = None  # noqa: F811
    #: What each Guardrail node did, as `{node, entity, strategy, count}`.
    #: **Counts and entity types, never values** (guardrails ticket 03).
    #:
    #: A redaction that happens silently is its own defect — a developer
    #: debugging "why did the agent answer that?" is reading text the
    #: machinery quietly rewrote. The obvious fix, showing what was removed,
    #: recreates the leak in the surface people read most often. The audience
    #: boundary is the answer that was already here: this side gets the
    #: counts, the customer gets clean text, and neither has to be told
    #: anything about the other. `abc.guardrail.Redaction` has no field that
    #: could carry a value, so a later edit cannot widen this by accident.
    #:
    #: A field here rather than a sentence in `warnings`, which was cheaper
    #: and wrong: every guarded run would then report warnings, the editor
    #: renders warnings as problems, and a channel that cries wolf on the
    #: happy path is one people learn to skip.
    redactions: list[dict[str, Any]] = field(default_factory=list)
    #: What this run actually executed, as `{node, tool, statement, result,
    #: truncated}` (`one-chinook-honest/30`). Built by
    #: `openstategraph.executed_statements.statements_executed` from the run's
    #: own `tool_use`, which is where `launch-readiness/165` already recorded
    #: every exchange an agent's loop had.
    #:
    #: Developer only, and the reason is the same one `163` gave one field
    #: along: this is the *evidence*, and evidence names node ids, tool names,
    #: tables and literal values out of a customer's own data. A customer gets
    #: the answer; the person who can audit the workflow gets what produced it.
    #:
    #: Two diagnoses in one day had to reconstruct these statements from the
    #: model's prose about what it did — the one account that cannot be trusted
    #: when the model got it wrong.
    statements: list[dict[str, Any]] = field(default_factory=list)

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
        return {
            "developer": {
                "warnings": list(self.warnings),
                "suggestion": self.suggestion,
                "capabilityGap": self.capability_gap,
                "redactions": list(self.redactions),
                "statements": list(self.statements),
            }
        }


#: What a customer reads when a capability did not reach their run — ticket 51.
#:
#: One fixed sentence, and every word of it is a decision:
#:
#: - **"part of this workflow"**, not "an MCP server", not a node id, not a
#:   URL. A customer has no way to act on any of those and no vocabulary to
#:   place them in; the raw sentences are precisely what `/chat` stopped
#:   printing in red (ticket 04), and reintroducing them under a softer label
#:   would undo that.
#: - **"may be incomplete"**, not "is wrong". The run may well have answered
#:   perfectly without the missing capability. What the reader is owed is the
#:   *doubt* — the failure this ticket is about is a confidently wrong answer
#:   with nothing on the page to suggest today differs from yesterday.
#: - **leading with "Note:"**, and separated from the reply by a blank line,
#:   so it reads as an aside rather than as part of the answer.
#: - **no count.** "Two of my tools" invites the question "which two", which
#:   is the developer channel's job to answer and not this sentence's.
#: - **no Markdown, and that one was found in a browser rather than reasoned
#:   out.** The first version wrapped this in `_underscores_` to render as an
#:   italic aside; `/chat`'s own `md()` implements `**bold**`, `` `code` ``,
#:   lists, tables and headings — and no italics at all — so the customer read
#:   a sentence with literal underscores around it. The rule this leaves
#:   behind is the general one: a string the *server* writes into `answer` is
#:   read by every client that exists and every client that will, so it may
#:   assume no renderer. Markup here is a bet on a feature the reader's client
#:   may not have, for emphasis the words already carry.
CAPABILITY_NOTICE = (
    "Note: part of this workflow was unavailable for this answer, "
    "so it may be incomplete."
)


def capability_notice(warnings: Sequence[str], audience: Audience) -> str:
    """The aside to append to a customer's answer, or `""`.

    The audience split stated as code, in the module that owns every other
    one. A **developer** gets nothing here on purpose: they already have the
    sentences themselves on `DeveloperChannel.warnings`, and a vague paragraph
    in the prose beside a specific list is noise that trains people to skim
    both.

    Takes the warnings rather than a bare boolean so the caller cannot get the
    question subtly wrong — "were there warnings" is the whole condition, and
    a caller computing it separately is a caller that will one day compute it
    from a different list than the one it reports.
    """
    if audience is Audience.DEVELOPER:
        return ""
    return CAPABILITY_NOTICE if any(str(w).strip() for w in warnings) else ""


def with_capability_notice(prose: str, warnings: Sequence[str], audience: Audience) -> str:
    """`prose` with the notice appended, when one is due.

    The reply comes **first** and the notice is an aside after it. A notice
    that led would make every degraded run look like an error page, and a
    notice that replaced the answer would be a worse bug than the silence it
    is fixing.
    """
    notice = capability_notice(warnings, audience)
    if not notice:
        return prose
    return f"{prose.rstrip()}\n\n{notice}" if prose.strip() else notice
