"""A criterion a grader cannot honour, because it never sees what produced the text.

`BaseGrader.grade` hands the model exactly one thing beyond the criteria: the
candidate's own text (`abc/grader.py`, `grader.grade(candidate, ...)`). It does
not receive the agent's tool calls, so a criterion of the shape *"this claim
must be traceable to a page the agent actually fetched"* is unsatisfiable in
principle — the grader is asked to verify a fact it has no access to, and the
only thing it can do is guess. Measured live: a correct answer, citing a real
URL, rejected three times with the reason *"provides a URL that was not
actually fetched and verified by the agent"* (`launch-readiness` 26,
`docs/decisions/stranger-install-2026-08-24.md` §9).

This is not a reason to widen `Grader.normalise` — that function is already
tolerant of how a *verdict* is phrased, and `CLAUDE.md` is explicit that
tolerance in reading is never permission to accept something unrecognised. The
defect here is upstream of any verdict: it is the criteria text asking an
unanswerable question in the first place. So the fix is narrower and cheaper —
stop shipping the question — and this module is the one place both the
shipped templates and a developer's own criteria can be checked against it.

Phrases are pinned rather than inferred, on purpose: a heuristic broad enough
to catch every paraphrase would also flag ordinary, satisfiable criteria
("cite your source"), which is exactly the false positive `CLAUDE.md` warns
against in the mirror-image case of an over-eager parser.
"""

from __future__ import annotations

#: Each names a fact only the *run* holds — which tool ran, whether a URL was
#: dereferenced, whether a query executed — never a fact readable off the
#: candidate text alone. A criterion containing one of these asks the grader
#: to verify something `grade()` cannot see.
UNVERIFIABLE_PROVENANCE_PHRASES: tuple[str, ...] = (
    "actually fetched",
    "actually verified",
    "actually run",
    "actually queried",
    "actually called",
    "come from a tool result",
    "came from a tool result",
    "was actually fetched",
    "was actually verified",
    "was actually run",
    "was actually queried",
    "was actually called",
)


def unsatisfiable_provenance_claims(criteria: str) -> list[str]:
    """Which unverifiable-provenance phrases appear in `criteria`, if any.

    Empty means the criteria are, at least by this check, answerable from the
    candidate text alone — which is all a grader is ever handed.
    """
    lowered = (criteria or "").lower()
    return [phrase for phrase in UNVERIFIABLE_PROVENANCE_PHRASES if phrase in lowered]


__all__ = ["UNVERIFIABLE_PROVENANCE_PHRASES", "unsatisfiable_provenance_claims"]
