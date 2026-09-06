"""Every number in the prose appears in something the run retrieved.

`launch-readiness/151`. Rule **F3** of a private NL2SQL package's rule
contract, classified CLOSEABLE on 2026-08-25 and left unbuilt for one stated
reason — *"it needs a new node after `summarize1`"*.
That node type now exists (`guard.check`, `launch-readiness/65`).

**The sweep note says the check was "implemented as a standalone
`check_numbers_in_prose()`". It was not.** Nothing of that name has ever
existed in this repository, in the demo packages, or in any backup of them —
only the paragraph claiming it. The claim was never citeable, which is the
same defect CLAUDE.md records about numbers written in prose: an assertion
with no way to fail. This module is the check, written.

## What is a quantity, and what is prose

The gate is about **quantities presented as retrieved**, not about
model-authored prose — an answer that explains, summarises or qualifies is the
product. So the line is drawn at the narrowest defensible place and every
widening of it is a hole this docstring names:

A **candidate** is a digit run in the answer. It is *not* a candidate when it

- is part of an identifier or a word (`VLCC2`, `gpt-4o`, `8b`) — a name, not a
  count;
- is a list marker at the head of a line (`1.`, `2)`);
- carries a `%` — a proportion is almost always arithmetic *over* numbers the
  model was given, which is the ticket's own *"roughly two thirds"* case
  written in digits. **This is a deliberate hole**: an invented `81%` passes.
  It is taken because the alternative fires on every honest summary that
  computes a share, and a gate people route around is worse than a narrow one.

A candidate is **grounded** when its value appears among

- the numbers in what the run retrieved — tool results and the outputs of
  deterministic steps;
- the numbers in the question, because a user's own `100 days` is not the
  model's invention;
- the retrieved text's row count, and that count less a header line — *"there
  are 12 vessels"* over twelve retrieved rows is honest and the literal `12`
  is nowhere in them;
- any rounding of a retrieved number to 0, 1 or 2 decimal places — `27.8` over
  a retrieved `27.8333` is honest arithmetic.

**What it cannot see, stated so nobody rediscovers it as a bug**: a model that
counts a *truncated* page reports a number that is honestly grounded in what
the run actually retrieved. The measured *"29 ports"* for a 68-port result is
that case, and it is a truncation defect, not an invention. This gate catches
the invention.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

#: Node type prefixes whose output is the model's own words rather than a
#: record. Their `outputs` are the thing being checked, never the evidence.
#: `function.` is deliberately absent — a package function is deterministic,
#: so what it returns is as much a retrieved fact as a tool result.
MODEL_AUTHORED: tuple[str, ...] = ("agent.", "orchestrate.", "route.", "guard.")

#: Thousands groups are spelled out rather than `[\d,]*`, which swallowed the
#: comma at the end of `4031,` and reported the literal with punctuation
#: attached — found by the test, not by reading.
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_LIST_MARKER = re.compile(r"^\s*$")


def _value(literal: str) -> Decimal | None:
    try:
        return Decimal(literal.replace(",", ""))
    except InvalidOperation:
        return None


def numbers_in(text: str) -> set[Decimal]:
    """Every number this text states, read tolerantly.

    No context rules at all, on purpose: this reads **evidence**, and CLAUDE.md's
    rule is tolerant in reading, strict in trusting. A number in a retrieved row
    grounds a number in the answer however it was spelled or embedded.
    """
    found: set[Decimal] = set()
    for match in _NUMBER.finditer(text or ""):
        value = _value(match.group())
        if value is not None:
            found.add(value)
    return found


def _roundings(values: Iterable[Decimal]) -> set[Decimal]:
    """Each value, plus its 0/1/2-decimal roundings — honest arithmetic."""
    widened: set[Decimal] = set()
    for value in values:
        widened.add(value)
        for places in ("1", "0.1", "0.01"):
            try:
                widened.add(value.quantize(Decimal(places)))
            except InvalidOperation:  # pragma: no cover - unbounded magnitudes
                continue
    return widened


def _row_counts(evidence: str) -> set[Decimal]:
    """How many rows came back, and that less a header line."""
    rows = len([line for line in (evidence or "").splitlines() if line.strip()])
    return {Decimal(rows), Decimal(max(rows - 1, 0))}


def _is_candidate(prose: str, match: re.Match[str]) -> bool:
    """Whether this digit run is a quantity rather than a name or a share."""
    start, end = match.span()
    before = prose[start - 1] if start else ""
    after = prose[end] if end < len(prose) else ""
    # `before` is `""` when the number opens the text, and `"" in "_."` is
    # True — so until `launch-readiness/165` found it, a quantity at offset 0
    # was never a candidate and an answer beginning *"1,454,449 dark
    # vessels"* escaped this gate entirely.
    if before.isalnum() or (before and before in "_."):
        return False
    if after.isalnum() or after == "_":
        return False
    if after == "%":
        return False
    head = prose.rfind("\n", 0, start) + 1
    if _LIST_MARKER.match(prose[head:start]) and after in ".)":
        return False
    return True


def quantities_in(prose: str) -> list[tuple[str, Decimal, int]]:
    """Every digit run in `prose` that is a **quantity**, as `(literal, value, end)`.

    The candidate rule of this module's docstring, made reusable: `_is_candidate`
    was private and `ungrounded_numbers` was its only caller, so a second reader
    of "which numbers in this answer are claims" would have had to re-implement
    the identifier / list-marker / percentage exclusions and drift from them.
    `launch-readiness/165` is that second reader (`counted_rows.py`), and it
    needs `end` as well, to see what noun the claim was attached to.
    """
    found: list[tuple[str, Decimal, int]] = []
    for match in _NUMBER.finditer(prose or ""):
        if not _is_candidate(prose or "", match):
            continue
        value = _value(match.group())
        if value is None:
            continue
        found.append((match.group(), value, match.end()))
    return found


def ungrounded_numbers(prose: str, evidence: str, question: str = "") -> list[str]:
    """The quantities in `prose` that nothing the run retrieved supports.

    In order of first appearance, deduplicated by literal — a reader chasing
    one invented number does not need it three times.
    """
    grounded = _roundings(numbers_in(evidence)) | numbers_in(question) | _row_counts(evidence)
    unsupported: list[str] = []
    seen: set[str] = set()
    for literal, value, _end in quantities_in(prose):
        if literal in seen or value in grounded:
            continue
        seen.add(literal)
        unsupported.append(literal)
    return unsupported


def retrieved_evidence(state: Mapping[str, Any], model_authored: Iterable[str]) -> str:
    """Everything this run actually retrieved, as one block of text.

    Two rails, because a workflow uses one or the other and a check that read
    only one would be silently inert on half the graphs anybody draws:

    - **Tool results.** An agent's SQL rows come back as `ToolMessage`s and
      never touch `outputs` — a bound tool is not a graph node.
    - **Deterministic step outputs.** A package function's `execute1` writes
      its rows to `outputs`, which is the shape the NL2SQL package uses.

    Model-authored outputs are excluded by node id: an agent's own draft is
    the thing being checked, so counting it as evidence would ground every
    number against itself.
    """
    excluded = set(model_authored)
    parts: list[str] = []
    # **The rail that actually carries an agent's results.** The paragraph
    # above says an agent's rows "come back as `ToolMessage`s" — they come
    # back to the *agent's own loop*: `_agent` returns `outputs`, `answer` and
    # `tool_use`, and no messages, so this walk found nothing on any graph
    # whose SQL runs inside an agent. `launch-readiness/165` measured that on
    # a live run and gave `tool_report` a place to record the exchange.
    for row in (state.get("tool_use") or {}).values():
        for exchange in (row or {}).get("queries") or []:
            parts.append(str((exchange or {}).get("result") or ""))
    for message in state.get("messages") or []:
        if getattr(message, "type", "") == "tool":
            parts.append(str(getattr(message, "content", "")))
    for node_id, text in (state.get("outputs") or {}).items():
        if node_id not in excluded:
            parts.append(str(text))
    return "\n".join(parts)


def check_numbers_in_prose(
    candidate: str, state: Mapping[str, Any], model_authored: Iterable[str]
) -> str:
    """`guard.check`'s F3 gate: empty is a pass, text is the revise reason.

    Same verdict contract as every other check the node calls — an empty
    return passes, a non-empty return is both the reason and the feedback sent
    upstream. The feedback is developer- and model-facing (it travels the
    `feedback` channel to the node being corrected), never customer copy, so
    `launch-readiness/143`'s sentence-shape rule does not reach it.
    """
    evidence = retrieved_evidence(state, model_authored)
    unsupported = ungrounded_numbers(candidate, evidence, str(state.get("question") or ""))
    if not unsupported:
        return ""
    return (
        "These figures appear in the answer and in nothing this run retrieved: "
        + ", ".join(unsupported)
        + ". Every quantity must come from a result you actually have. Remove them, "
        "or retrieve the data that supports them and say so."
    )
