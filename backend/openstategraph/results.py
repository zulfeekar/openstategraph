"""What one run of a workflow produced.

**Tier 1, semver-public** (`docs/stability.md`).

`RunResult` subclasses `str`, which is a deliberate and recorded trade-off, not
a shortcut. `CompiledWorkflow.ask()` shipped in 0.3.0 returning a plain string
and `docs/adoption.md` publishes `print(workflow.ask("..."))`; a plain value
object with `__str__` would keep `print()` and f-strings working while silently
breaking `.strip()`, `.upper()`, `x + result`, `json.dumps({"a": result})`,
`re.search(p, result)` and `isinstance(result, str)`. Those break at run time,
in an adopter's service, long after the upgrade — the worst shape of failure
this codebase has. A `str` subclass breaks none of them: the object *is* the
answer, with the rest of the run attached.

The cost is real and bounded, and worth naming so nobody rediscovers it as a
surprise: `RunResult` inherits `str`'s ~40 methods, so `result.<TAB>` shows
`.title()` next to `.decisions`; it is immutable (fine — the run is over); and
`type(x) is str` is False (`isinstance` is the check anyone actually writes).

**Planned successor.** At 1.0, where a major bump makes a breaking change
affordable, this becomes a plain frozen dataclass with `.answer`. That is a
plan, recorded here rather than a regret discovered later; nothing should be
built that depends on `RunResult` being a string *forever*.
"""

from __future__ import annotations

from typing import Any


class RunResult(str):
    """The answer, plus everything else the run produced.

        answer = workflow.ask("How many invoices are there?")
        print(answer)                 # it is the answer text
        print(answer.decisions)       # ...and the branch each router took
        if answer.warnings:           # ...and what did not resolve
            ...

    Constructed by `CompiledWorkflow.ask()`; there is no reason to build one
    yourself outside a test.
    """

    #: The answer text. Identical to the object itself — present because
    #: `result.answer` is what reads correctly next to `result.decisions`,
    #: and because it is the attribute that survives the 1.0 dataclass.
    answer: str
    #: node id -> the branch label that router or grader chose.
    decisions: dict[str, str]
    #: node id -> that node's own textual output.
    outputs: dict[str, str]
    #: Capabilities the package named but the process could not resolve,
    #: carried through from `CompiledWorkflow.warnings` so a caller checking
    #: one run does not have to hold on to the workflow object as well.
    warnings: list[str]
    #: How many grader revise laps the run took. 0 for a graph with no loop.
    attempts: int

    def __new__(
        cls,
        answer: str = "",
        *,
        decisions: dict[str, str] | None = None,
        outputs: dict[str, str] | None = None,
        warnings: list[str] | None = None,
        attempts: int = 0,
    ) -> "RunResult":
        self = super().__new__(cls, answer)
        self.answer = str(answer)
        # Empty containers, never None: a caller iterating `.warnings` on a
        # clean run must not have to guard for it.
        self.decisions = dict(decisions or {})
        self.outputs = dict(outputs or {})
        self.warnings = list(warnings or [])
        self.attempts = int(attempts)
        return self

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle and `copy` keep the attributes.

        Without this, `str.__reduce_ex__` round-trips the *text* and drops
        everything attached to it — an object that still looks right and has
        quietly lost the diagnostics, which is worse than an exception.
        """
        return (
            _rebuild,
            (str(self), self.decisions, self.outputs, self.warnings, self.attempts),
        )

    def __repr__(self) -> str:
        return (
            f"RunResult({str.__repr__(self)}, decisions={self.decisions!r}, "
            f"outputs={self.outputs!r}, warnings={self.warnings!r}, "
            f"attempts={self.attempts!r})"
        )


def _rebuild(
    answer: str,
    decisions: dict[str, str],
    outputs: dict[str, str],
    warnings: list[str],
    attempts: int,
) -> RunResult:
    """Module-level so `pickle` can find it by name."""
    return RunResult(
        answer,
        decisions=decisions,
        outputs=outputs,
        warnings=warnings,
        attempts=attempts,
    )


__all__ = ["RunResult"]
