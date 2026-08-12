"""Getting the SQL back out of an answer that was written for a human.

Execution accuracy needs a query to execute, and this workflow's product is an
*answer*, not a query — so the harness has to recover the SQL the system says
it ran. That is a real property of grading a product rather than a benchmark
submission, and it is why `sql_recovered` is a first-class column on the
scorecard: a system that answers correctly but never states its query cannot be
verified, and "cannot be verified" is a finding, not a rounding error.

The recovery is deliberately dumb and deterministic:

1. **Fenced blocks win.** ```` ```sql … ``` ```` is what a model emits when
   asked to state its query, and a fence has unambiguous boundaries.
2. **Otherwise, a bare statement** starting at `SELECT` and ending at the first
   `;`. A bare match must also contain `FROM`, so English prose is not mistaken
   for a query. `WITH` is honoured only inside a fence, on purpose: "…answer
   **with** a figure **from** the catalogue" is a sentence a refusal really
   writes, and scoring it as an executed query would turn correct behaviour
   into a `should_have_refused`. A CTE stated unfenced therefore recovers from
   its inner `SELECT` and usually fails to execute — a visible `sql_error`
   rather than a silent mis-grade.
3. **The last query wins.** A retry loop narrates the query it abandoned before
   the one it kept.

No model is involved in the recovery, because a recovery step that itself needs
a model makes the metric depend on the thing being measured.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"```[ \t]*(?:sql)?[ \t]*\r?\n?(.*?)```", re.DOTALL | re.IGNORECASE)
_BARE = re.compile(r"\bselect\b[^;]*", re.IGNORECASE | re.DOTALL)
_STARTS_A_QUERY = re.compile(r"^\s*(?:select|with)\b", re.IGNORECASE)


def _clean(statement: str) -> str:
    return statement.strip().rstrip(";").strip()


def recover_sql(text: str | None) -> str | None:
    """The last SQL statement stated in `text`, or `None` if there is none."""
    if not text:
        return None

    fenced = [_clean(block) for block in _FENCE.findall(text)]
    queries = [block for block in fenced if _STARTS_A_QUERY.match(block)]
    if queries:
        return queries[-1]

    bare = [
        _clean(match.group(0))
        for match in _BARE.finditer(text)
        if "from" in match.group(0).lower()
    ]
    return bare[-1] if bare else None


def recover_from_run(answer: str, outputs: dict[str, str]) -> tuple[str | None, str]:
    """The answer first, then the individual node outputs.

    Returns the statement and where it came from — `"answer"`, `"outputs"` or
    `""`. The answer is preferred because it is what a user sees and therefore
    what the system is claiming; a node output is corroboration when the final
    message summarised instead of quoting.
    """
    from_answer = recover_sql(answer)
    if from_answer:
        return from_answer, "answer"
    for _node, text in sorted(outputs.items()):
        recovered = recover_sql(text)
        if recovered:
            return recovered, "outputs"
    return None, ""


__all__ = ["recover_from_run", "recover_sql"]
