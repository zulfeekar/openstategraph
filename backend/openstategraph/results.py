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
    #: Everything worth telling a reader about this run: what the package
    #: could not resolve when it compiled, what broke while it ran, and what
    #: it is worth knowing about *how* the answer was reached — a node that
    #: produced nothing, a grader that ran out of attempts, a revise verdict
    #: with no edge. The same report the HTTP doors carry (`run_health`).
    warnings: list[str]
    #: The half of `warnings` that is a claim the run **failed** — and the
    #: only half a script may gate on. `warnings` is the report; this is the
    #: verdict, and `cli.run_exit_code` reads this one.
    #:
    #: The split exists because folding a run's whole health onto `warnings`
    #: would have flipped `openstategraph run`'s exit code for every run with
    #: a silent node, which `silent_node_warnings` forbids in as many words:
    #: a silent node is a report about how the answer was reached, not a claim
    #: that the run failed, and the two must not share a channel a script
    #: gates on (`workflow-gallery` 49). `RunHealth` has had this split all
    #: along; this is the same split at the door.
    failures: list[str]
    #: How many grader revise laps the run took. 0 for a graph with no loop.
    attempts: int

    def __new__(
        cls,
        answer: str = "",
        *,
        decisions: dict[str, str] | None = None,
        outputs: dict[str, str] | None = None,
        warnings: list[str] | None = None,
        failures: list[str] | None = None,
        attempts: int = 0,
    ) -> "RunResult":
        self = super().__new__(cls, answer)
        self.answer = str(answer)
        # Empty containers, never None: a caller iterating `.warnings` on a
        # clean run must not have to guard for it.
        self.decisions = dict(decisions or {})
        self.outputs = dict(outputs or {})
        self.warnings = list(warnings or [])
        # `None` is not "no failures" — it is a caller that predates the
        # split, for whom `warnings` *was* the failure channel. Defaulting it
        # to empty would silently turn every such run into a success.
        self.failures = list(self.warnings if failures is None else failures)
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
            (
                str(self),
                self.decisions,
                self.outputs,
                self.warnings,
                self.attempts,
                self.failures,
            ),
        )

    @property
    def failed_nodes(self) -> dict[str, str]:
        """node id -> why that node failed, for a caller reading `outputs`.

        A failed node's output slot carries `'[summarise1 failed after
        retries: …]'`. That is deliberate and stays — downstream nodes must
        still read *something* — but every surface renders `outputs` as each
        node's **output**, so a caller reading the map rather than the
        warnings got a sentinel indistinguishable from an answer
        (`workflow-gallery` 44).

        Derived from `outputs` on access rather than stored, so it is right
        for a `RunResult` assembled by hand as well as one built by `ask()` —
        the same reason `cli.run_exit_code` reads `outputs` directly.

        **Narrow on purpose.** The whole marker, anchored at both ends, is
        what counts; a node whose answer merely *mentions* one is content and
        is left alone. This product prints JSON and brackets as prose
        constantly, and tolerance here would be permission to call an answer
        a failure.
        """
        from openstategraph.compile.workflow_compiler import parse_failure_marker

        found: dict[str, str] = {}
        for node, value in self.outputs.items():
            reason = parse_failure_marker(str(value or ""))
            if reason is not None:
                found[node] = reason
        return found

    def __repr__(self) -> str:
        return (
            f"RunResult({str.__repr__(self)}, decisions={self.decisions!r}, "
            f"outputs={self.outputs!r}, warnings={self.warnings!r}, "
            f"failures={self.failures!r}, attempts={self.attempts!r})"
        )


def _rebuild(
    answer: str,
    decisions: dict[str, str],
    outputs: dict[str, str],
    warnings: list[str],
    attempts: int,
    failures: list[str] | None = None,
) -> RunResult:
    """Module-level so `pickle` can find it by name.

    `failures` is last and optional so a `RunResult` pickled by an older
    version still unpickles — a five-tuple written before the split lands on
    the same back-compat path as a caller that never passed it.
    """
    return RunResult(
        answer,
        decisions=decisions,
        outputs=outputs,
        warnings=warnings,
        failures=failures,
        attempts=attempts,
    )


__all__ = ["RunResult"]
