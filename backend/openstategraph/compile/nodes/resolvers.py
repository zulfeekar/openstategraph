"""`resolve.vocabulary` and `resolve.source` — settled before the model, not by it.

Two families and one reason to change: **a question the run answers for
itself.** What a word means here, and which store is entitled to answer — both
were once things a model picked, and both picked differently on every run. The
registry registers them as siblings and says so in one comment; this is that
comment given a file.

The shape they share is the whole argument for the pair. Each reads a package
function by `function.<name>`, resolves against it before any model is asked
anything, and — the property that matters — has **no silent path out**. A
source that will not resolve is *reported* (`Finding.UNRESOLVED_FUNCTION`) and
rendered as an uncovered block, never passed through, because a resolver that
found nothing and said nothing is indistinguishable from a term that was never
ambiguous. That is the shape behind six defects on `launch-readiness`, and it
is the reason these two are one module rather than two.

Neither writes `answer`: both are intermediate steps, and a resolution landing
in `answer` would let a run whose model never spoke end with a metadata block
presented as its answer.

`compile/nodes/__init__.py` carries the argument for the package and the
binding mechanism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from openstategraph.compile.workflow_compiler import CompiledPlan
from openstategraph.compile.upstream import upstream_sources
from openstategraph.compile.state import RunState
from openstategraph.abc.tool_notes import record_notes
from openstategraph.compile.context import _text
from openstategraph.compile.diagnostics import Finding
from openstategraph.compile.state import _upstream_text
from openstategraph.sources import (
    DEFAULT_WHEN_UNDECIDED,
    resolve_source,
    unresolved_catalogue,
)
from openstategraph.vocabulary import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_WHEN_UNCOVERED,
    resolve_vocabulary,
    unresolved_source,
)

if TYPE_CHECKING:
    # The class these functions are methods of. Type-only: the import that
    # matters runs the other way, once, when `NodeRuntime`'s class body binds
    # them. See this package's `__init__.py` for why that is the seam.
    from openstategraph.compile.node_runtime import NodeRuntime


def _resolve_vocabulary(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """*What is this word called here?* — answered before the model runs.

    `launch-readiness/135`. The engine is `openstategraph.vocabulary`;
    this builder is the seam between it and a drawn node — which source,
    how many entries, and what the run carries downstream when nothing
    was covered.

    Three properties are the point of the node and are asserted by
    `tests/test_a_resolver_that_covers_nothing_says_so.py`:

    - **It is a step, not a tool.** Vocabulary must not be a choice: when
      the model picked which source told it what a term meant, it picked
      differently on every run.
    - **Rank, then cap** (`launch-readiness/130`), with the searches still
      concurrent — the ranking is what stopped thread scheduling choosing
      the axis, not serialising.
    - **It reports what it covered, not only what it found.** A resolver
      that found nothing and said nothing is indistinguishable from a term
      that was never ambiguous, which is the shape behind six defects on
      this map. So there is no silent path out of here — an unresolved
      source is *reported*, never passed through (`unresolved_source`).

    `answer` is deliberately not written. This is an intermediate step,
    and a resolution that landed in `answer` would let a run whose model
    never spoke end with a metadata block presented as its answer.
    """
    data = node.get("data") or {}
    source_name = _text(data, "source").strip()
    key = f"function.{source_name}" if source_name else ""
    source = self.services.functions.get(key) if key else None
    try:
        max_entries = int(data.get("maxEntries") or DEFAULT_MAX_ENTRIES)
    except (TypeError, ValueError):
        max_entries = DEFAULT_MAX_ENTRIES
    when_uncovered = _text(data, "whenUncovered").strip() or DEFAULT_WHEN_UNCOVERED

    # A resolver placed behind a routed edge reads its wired upstream, not
    # the turn's original question — the same gap `launch-readiness` 66
    # closed on `_discovered_function`.
    sources = upstream_sources(plan, node_id)

    def run(state: RunState) -> dict[str, Any]:
        question = _upstream_text(state, sources) or state.get("question", "")
        if source is None:
            self.diagnostics.record(
                Finding.UNRESOLVED_FUNCTION, f"resolve.vocabulary:{source_name}"
            )
            block = unresolved_source(key or source_name, when_uncovered)
        else:
            resolution = resolve_vocabulary(
                question,
                source,
                max_entries=max_entries,
                source_name=key,
                when_uncovered=when_uncovered,
            )
            # `launch-readiness/127`'s tuple, on the run's own rail: the
            # output node discloses the substitution whether or not the
            # model mentions it.
            record_notes(resolution.substitutions)
            block = resolution.render()

        output = f"{question}\n\n---\n{block}" if question else block
        return {"outputs": {node_id: output}}

    return run


def _resolve_source(self: "NodeRuntime", node_id: str, node: dict[str, Any], plan: CompiledPlan) -> Any:
    """*Which store is answering this, and what else could have?*

    `launch-readiness/150`. The engine is `openstategraph.sources`; this
    builder is the seam between it and a drawn node — which catalogue,
    what the figures are called, and what the run carries downstream when
    several systems of record are live and nothing settles which.

    The user's complaint it exists for was *"in the may number 1664 is
    given in the table. I do not understand where this number comes from"*
    — three of seven complaints in one round were this shape. A number
    with no stated source and a number from the wrong source look
    identical, and that is this project's most expensive failure attached
    to the thing a user trusts most.

    Four properties are asserted by
    `tests/test_a_run_names_the_source_it_used.py`:

    - **It is a step, not a tool**, for the same measured reason
      `resolve.vocabulary` is: a source the model picks is a source that
      changes between runs.
    - **The alternatives are the payload.** `Substitution` maps one term
      to another; this is one choice among several declared alternatives,
      so it mints its own note kind (`SourceChoice`) on the run's rail and
      `_output` discloses it whether or not the model mentions it.
    - **Nothing to choose is not the same as could not tell.** A catalogue
      declaring one source and a catalogue declaring none render
      differently, by construction, with no toggle between them.
    - **It settles nothing it was not told.** Where several sources are
      live and none is named or default, no choice is recorded — that is
      `guardrails/06`'s abstain, which is open and unbuilt, and this step
      leaves the seam rather than inventing a second way to ask.

    `answer` is deliberately not written, exactly as for the vocabulary
    resolver: an intermediate step whose block landed in `answer` would
    let a run whose model never spoke end with metadata as its answer.
    """
    data = node.get("data") or {}
    catalogue_name = _text(data, "catalogue").strip()
    key = f"function.{catalogue_name}" if catalogue_name else ""
    catalogue = self.services.functions.get(key) if key else None
    quantity = _text(data, "quantity").strip()
    when_undecided = _text(data, "whenUndecided").strip() or DEFAULT_WHEN_UNDECIDED

    sources = upstream_sources(plan, node_id)

    def run(state: RunState) -> dict[str, Any]:
        question = _upstream_text(state, sources) or state.get("question", "")
        if catalogue is None:
            self.diagnostics.record(
                Finding.UNRESOLVED_FUNCTION, f"resolve.source:{catalogue_name}"
            )
            block = unresolved_catalogue(key or catalogue_name, when_undecided)
        else:
            selection = resolve_source(
                question,
                catalogue,
                quantity=quantity,
                catalogue_name=key,
                when_undecided=when_undecided,
            )
            # The run's own rail: the output node names the source whether
            # or not the model remembered to.
            record_notes(selection.notes)
            block = selection.render()

        output = f"{question}\n\n---\n{block}" if question else block
        return {"outputs": {node_id: output}}

    return run
