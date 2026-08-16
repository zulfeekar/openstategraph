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
}


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

    def warnings(self) -> list[str]:
        """Every finding, spelled out, grouped in `Finding` declaration order."""
        return [
            _SENTENCES[finding].format(*subjects)
            for finding in Finding
            for subjects in self._findings.get(finding, ())
        ]
