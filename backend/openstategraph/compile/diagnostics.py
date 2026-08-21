"""Every way a compiled graph quietly lost a capability, and what to say.

Seven lists used to live on `NodeRuntime` — 7 of its 23 public attributes —
and `api/registries.runtime_warnings()` reached across into all seven to turn
them into sentences, three of them through `getattr(runtime, name, [])`. That
defensive access was the tell: the contract between the two sides was never
firm enough for either to depend on it (reviews-2026-08-14 ticket 07).

The data and its only reader live together now, and a finding is a **value**
rather than a field. Adding a kind is a table entry, not another attribute on
the runtime plus another loop in `runtime_warnings` — which is the open/closed
rule applied to the one part of the compiler that grows every time a node type
learns a new way to be incomplete.

**The rule these sentences serve** is `errors.py`'s: degrade loud, never
silent. An agent that quietly loses its tools does not fail — it answers from
parametric knowledge, confidently and wrongly. Observed exactly that: a Reddit
tool node wired to an agent produced an authoritative-sounding answer about
global music revenue having queried nothing. Every sentence below exists
because some run looked like it worked and had not.
"""

from __future__ import annotations

import re
from enum import Enum


class Finding(str, Enum):
    """A way a compiled graph came out less capable than it was drawn.

    `str`-valued for the reason `Reducer` is: a member survives a JSON round
    trip with no encoder, so a finding can cross the run/stream seam as data.

    **Declaration order is report order.** It reproduces the order the seven
    loops in `runtime_warnings` happened to be written in, which is now a
    property that can be read rather than one spread across a function.
    """

    #: A tool node on the canvas with no implementation behind it.
    UNRESOLVED_TOOL = "unresolved_tool"
    #: A function node wired on the canvas with no discovered callable.
    UNRESOLVED_FUNCTION = "unresolved_function"
    #: A Team mount whose child graph cannot enforce the outcome on its card.
    #:
    #: `TeamNode`'s *Expected outcome* never reaches the compiler, so a user
    #: writes a constraint, reasonably believes it binds the run, and gets no
    #: signal that it does not. Reported rather than refused: a Team without a
    #: loop is a legal graph that answers questions. What it cannot do is keep
    #: the promise printed on its card (production-ready ticket 03).
    UNENFORCED_OUTCOME = "unenforced_outcome"
    #: A grader whose `revise` port is wired to nothing (`workflow-gallery` 31).
    #:
    #: The compiler's conditional edge is given only the destinations that
    #: were drawn, and `_router_for` falls back to the first of them when the
    #: recorded decision names none — which is right for a *missing* decision
    #: and silent for a decision that exists and was understood. So a grader
    #: that judged the answer inadequate sent it to the output anyway.
    #:
    #: Reported rather than refused, and deliberately not on `plan.warnings`:
    #: a grader used as a recorder is a legal graph that answers questions,
    #: `support-triage` ships exactly that shape on purpose, and
    #: `plan.warnings` is the channel `validate` turns into PROBLEMS FOUND.
    #:
    #: For the same reason it is a **report**, not a failure — see
    #: `REPORT_ONLY` below. The run does everything it was drawn to do; this
    #: sentence is advice about the drawing, and it is the identical
    #: observation `run_health` publishes as `unrouted` (`workflow-gallery` 50).
    UNWIRED_REVISE = "unwired_revise"
    #: A node type this build has no factory for, as `(type, node id)`.
    #:
    #: The loud half of a rule that was only half kept. `errors.py` records the
    #: policy — an unknown node type is *reported*, not raised, so a document
    #: containing one still answers what it can — and `_passthrough`
    #: implemented the degrade while reporting nothing. Its docstring claimed
    #: "the gap is visible as an unchanged value", which is exactly what hides
    #: it: the skipped node forwarded its input, so the run answered the user's
    #: own question back and looked like it worked. Found through the typo
    #: `agent.react` for `agent.llm`.
    UNKNOWN_NODE_TYPE = "unknown_node_type"
    #: A subgraph node whose workflow could not be loaded.
    UNRESOLVED_SUBGRAPH = "unresolved_subgraph"
    #: A per-mount override problem — unknown child node id, wrong shape.
    OVERRIDE_PROBLEM = "override_problem"
    #: A capability that failed to *load* — a tool module that would not
    #: import, an abstract class discovery could not instantiate, a plugin
    #: distribution that half-installed.
    #:
    #: Distinct from `UNRESOLVED_TOOL`, which is a node on the canvas finding
    #: no implementation; this is an implementation that never became one.
    #: They share a channel deliberately: from a developer's seat "the tool I
    #: wrote is not here" is one question, and answering half of it in a server
    #: log they never open is how the original bug survived.
    CAPABILITY_FAILED = "capability_failed"
    #: An Output node with no guardrail anywhere upstream of it, **in a
    #: document that has one somewhere else** (guardrails ticket 02).
    #:
    #: The condition is deliberately the *inconsistent* case, not the absent
    #: one. Ticket 02 weighed making the outbound guard something Output just
    #: does — impossible to forget, and invisible, and a second job for a node
    #: that has one. It chose the node, on the condition that its absence be
    #: loud; this is that condition, scoped by the rule stated at the top of
    #: this module. Warning every document that has no guardrail would fire on
    #: every shipped example and on every workflow anyone has drawn,
    #: and "a warning a user cannot act on is a warning they learn to skip".
    #:
    #: What this catches is the realistic mistake instead: somebody added a
    #: second Output later, wired it straight off the agent, and the answer
    #: reaching the user down *that* path never meets the policy the document
    #: says it has. The asymmetry ticket 02 argued from is why it is worth a
    #: sentence at all — a missing inbound guard is a missed block, a missing
    #: outbound one is a disclosure.
    UNGUARDED_EXIT = "unguarded_exit"
    #: A Guardrail row that cannot do what its card says — an unimplemented
    #: strategy, or a `detector` that is not a valid pattern (guardrails 05).
    #:
    #: Found at build time by `BaseGuardrail.problems()`. It used to be found
    #: only by running: `resolved()` is called from `screen()`, so a missing
    #: `)` surfaced as a bare `re.error` out of the middle of a run, with a
    #: person waiting. The node still refuses to pass text through when it
    #: happens — a guardrail that fails open is the one failure worse than
    #: noisy — but the developer is told at compile time, in a sentence.
    INVALID_GUARDRAIL_RULE = "invalid_guardrail_rule"
    #: An agent or worker whose **authored** rules deny holding any tools while
    #: the canvas has tools wired to it, as `(node id, the offending phrase)`.
    #:
    #: The half of production-ready 88 that survived its own fix. That ticket
    #: made the *run* right — `held_tools_context` hands the node an
    #: authoritative list that overrules the stale sentence — which is exactly
    #: why nobody will ever be prompted to look at the sentence again. The
    #: document stays wrong, silently, in a field the developer owns.
    #:
    #: Reported and never rewritten: 88 decided the prompt field is theirs, and
    #: a platform that edits a prompt is one nobody can predict. Reported on
    #: this channel rather than `plan.warnings` for `UNWIRED_REVISE`'s reason,
    #: and deliberately **not** on `validate`'s exit code: that command's one
    #: question is "is this ready to run here", and the answer is yes — the
    #: tool is bound, and it is called.
    STALE_TOOL_DENIAL = "stale_tool_denial"


#: What each finding says, and how many subjects it takes.
#:
#: Full sentences naming the consequence, not the condition — "the agent ran
#: without it, so its answer may not be grounded" rather than "unresolved
#: tool". A warning a user cannot act on is a warning they learn to skip.
#:
#: `CAPABILITY_FAILED` carries no prefix because discovery findings already
#: name the class, the file and the fix: a discovery finding is not a
#: sub-species of an unresolved binding, it is the other half of the same
#: question.
_SENTENCES: dict[Finding, str] = {
    Finding.UNRESOLVED_TOOL: (
        'No implementation for tool "{0}" — the agent ran without it, '
        "so its answer may not be grounded in that data source."
    ),
    Finding.UNRESOLVED_FUNCTION: (
        'No function found for "{0}" — the step passed its input through unchanged.'
    ),
    Finding.UNENFORCED_OUTCOME: (
        'Team "{0}" mounts "{1}", whose graph has no grader routing revise — so its '
        "Expected outcome is documentation and nothing in the run checks it. Add a "
        "grader to that workflow and wire revise back, or read the outcome as a note."
    ),
    Finding.UNWIRED_REVISE: (
        'Grader "{0}" has no revise edge — a verdict of revise routes to its pass '
        "branch instead, so an answer this grader rejected ships as though it had "
        "been approved. Wire revise back to the node that should redraft, or read "
        "this grader as a recorder rather than a gate."
    ),
    Finding.UNKNOWN_NODE_TYPE: (
        'Node "{1}" has type "{0}", which this build does not implement — the step '
        "passed its input through unchanged, so any answer downstream of it skipped "
        "that work."
    ),
    # "Subgraph" was a LangGraph name in a sentence a user reads, which
    # CLAUDE.md forbids — and it was not even internally true: this compiler
    # emits no LangGraph subgraph (production-ready 37). The settled words are
    # *mount* and *workflow node*, and the enum member keeps its old name
    # because it is not a surface (ticket 53).
    Finding.UNRESOLVED_SUBGRAPH: (
        'The workflow node mounting "{0}" could not load that package — '
        "the step produced nothing."
    ),
    Finding.OVERRIDE_PROBLEM: "Mount override — {0}",
    Finding.CAPABILITY_FAILED: "{0}",
    Finding.UNGUARDED_EXIT: (
        'Output "{0}" has no guardrail upstream of it, but this workflow has one on '
        "another path — so an answer that leaves this way is never checked against the "
        "policy the rest of the document keeps. Wire a Guardrail before it, or delete "
        "the one that suggests it should be there."
    ),
    Finding.STALE_TOOL_DENIAL: (
        'Agent "{0}" has tools wired to it, but its own rules still say "{1}" — the '
        "run overrules that with the generated list of what the node holds, so the "
        "answer is right and the sentence is stale. Update the line, or expect every "
        "reader of this document to believe it."
    ),
    Finding.INVALID_GUARDRAIL_RULE: (
        'Guardrail "{0}" has a row for "{1}" that {2} — that row protects nothing, '
        "and the node refuses everything rather than letting text past a policy it "
        "cannot apply. Fix the row or remove it."
    ),
}


#: Findings that are a *report* about the document rather than a claim that a
#: capability was lost. They ride `warnings()` with everything else and are
#: kept off `failure_warnings()`, so no surface can turn one into an exit code.
#: Membership is a decision about meaning: everything else here describes work
#: the run did not do.
#:
#: `UNWIRED_REVISE` joined it in `workflow-gallery` 50, which is the
#: classification pass ticket 89 left with one member. The argument is not that
#: an unwired grader is harmless — it is that **the runtime already publishes
#: the identical observation as a report**. `run_health`'s `unrouted` says a
#: verdict of revise reached no edge; this finding says the edge was never
#: drawn. Ticket 49 put `unrouted` on the report side deliberately, so leaving
#: this one on the failure side made one observation a failure when the
#: compiler noticed it and a report when the run did — and on any run that
#: answered with nothing, the compile half alone exited 1 for a graph
#: `support-triage` ships on purpose.
#:
#: The other eight stay failures, and two of them are close enough to say so
#: out loud. `UNENFORCED_OUTCOME` is the same shape one level up — a Team card
#: promising an outcome whose child graph cannot check it — and
#: `UNGUARDED_EXIT` is likewise about how a document is drawn. Both were left
#: here because each names a *promise the document makes and the run cannot
#: keep*, which is the failure side's own definition, and because the safe
#: direction of error for an exit code is to keep exiting 1: the opposite
#: green-lights a broken graph in somebody's CI. Neither is a settled call, and
#: `workflow-gallery` 51 carries the argument.
REPORT_ONLY: frozenset[Finding] = frozenset(
    {Finding.UNWIRED_REVISE, Finding.STALE_TOOL_DENIAL}
)


class CompileDiagnostics:
    """What the compiler noticed and could not resolve.

    One reason to change: the ways a graph can come out incomplete. Recording
    is deduplicated here rather than at each call site — five of the seven
    buckets open-coded `if x not in bucket` and one of them did not.
    """

    def __init__(self) -> None:
        self._findings: dict[Finding, list[tuple[str, ...]]] = {}

    @staticmethod
    def sentence_for(finding: Finding) -> str:
        """The template for a kind. Every member has one, and a test says so."""
        return _SENTENCES[finding]

    def record(self, finding: Finding, *subjects: str) -> None:
        """Note a finding, once. Recording the same subjects twice is a no-op."""
        expected = _SENTENCES[finding].count("{")
        if len(subjects) != expected:
            # Raised rather than formatted loosely: a template with an
            # unfilled slot ships "{1}" to a user, which is worse than the
            # missing information it stands for.
            raise ValueError(
                f"{finding.value} takes {expected} subject(s), got {len(subjects)}: {subjects!r}"
            )
        recorded = self._findings.setdefault(finding, [])
        if subjects not in recorded:
            recorded.append(subjects)

    def subjects(self, finding: Finding) -> list[tuple[str, ...]]:
        """What was recorded for one kind, in the order it was recorded."""
        return list(self._findings.get(finding, ()))

    def any(self, finding: Finding) -> bool:
        """Whether anything of this kind was recorded."""
        return bool(self._findings.get(finding))

    def failure_warnings(self) -> list[str]:
        """The findings that may reach an exit code — everything but a report.

        `loader.ask()` put the whole of `warnings()` on `RunResult.failures`,
        a rule written for a mount that would not load: that is a broken run,
        it leaves no marker in `outputs`, and a `1` is the honest answer
        (`production-ready` 53). `STALE_TOOL_DENIAL` is the first finding that
        is not a claim about capability at all — the tool is bound, the run
        calls it, and the report says so in its own sentence. Found by running
        it: the CLI printed *"the answer is right and the sentence is stale"*
        prefixed `error:`, because the prefix is derived from this same
        membership (`workflow-gallery` 44).

        The split, not the removal: a report goes on `warnings()` like every
        other finding, and `8bda508`'s rule — a report cannot move an exit
        code — is what decides which list it is *also* on.
        """
        return [
            _SENTENCES[finding].format(*subjects)
            for finding in Finding
            if finding not in REPORT_ONLY
            for subjects in self._findings.get(finding, ())
        ]

    def warnings(self) -> list[str]:
        """Every finding, spelled out, grouped in `Finding` declaration order."""
        return [
            _SENTENCES[finding].format(*subjects)
            for finding in Finding
            for subjects in self._findings.get(finding, ())
        ]


#: The phrasings that count as *"this node holds no tools at all"*, and nothing
#: wider.
#:
#: `CLAUDE.md`'s rule reads both ways here. **Tolerant**: the observed prose is
#: matched however it is spelt — `hold`/`have`, contracted or not, wherever in
#: the sentence the subject sits. **Strict**: only a denial of *tools*, bare,
#: about *this* node, in *one* sentence. Everything the second half excludes is
#: ordinary correct prose on a node that holds something — "you have no
#: internet access", "you have no web-search tools", "you have no tools for
#: booking travel", "the user has no tools installed". A warning that fires on
#: any of those is a warning a developer learns to skip, which is worse than
#: the silence this finding replaces.
#:
#: So the shape is fixed and narrow: the subject `you`, a negation, and the
#: bare word `tools` — no qualifier in front of it, no purpose clause after it,
#: and no sentence boundary crossed between the subject and the claim.
_TOOL_DENIALS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\byou\b[^.!?\n]{0,40}?\bno\s+tools\b(?!\s+(?:for|to)\b)", re.IGNORECASE),
    re.compile(
        r"\byou\b[^.!?\n]{0,40}?\b(?:do\s+not|don[\u2019']t|cannot|can[\u2019']t|will\s+not|"
        r"won[\u2019']t)\s+(?:have|hold)\s+any\s+tools\b(?!\s+(?:for|to)\b)",
        re.IGNORECASE,
    ),
)


def denies_holding_tools(text: str) -> str:
    """The phrase in `text` claiming this node holds no tools, or `""`.

    Returns the offending phrase rather than a bool so the finding can quote
    it: a warning naming the sentence is one a developer can act on without
    re-reading the whole field, and the quote is the node's own words rather
    than our paraphrase of them.
    """
    for pattern in _TOOL_DENIALS:
        found = pattern.search(text or "")
        if found:
            return found.group(0).strip()
    return ""
