"""One question, asked at every run door: *is there anything to run this with?*

`osg-agent-experience/48`. With no provider configured, the try project's run
resolved the axis, scored fifteen lenses, routed, and only then died inside one
worker — *"Node failed and produced no result. Provider 'ollama' has no
credential"*. Honest, and late: a reader sees a node failure and suspects the
node.

The deferral that causes it is deliberate and stays. `NodeRuntime._base_model`
hands back a stand-in that raises on first use rather than refusing at build,
so **a workflow needing no model still runs on an installation with no
provider** — a graph of functions, tools and outputs is a real thing people
build here. What was missing is the other half: a graph that will certainly
reach a model, on an installation that certainly cannot serve one, has a
knowable answer before the first superstep.

## The sentence is not a new one

`ProviderCatalogue.elected_default().reason` — what `openstategraph providers`
prints as its header, what `GET /api/providers` publishes as `run_readiness`,
and what the runnable starter's note already quotes to say *nothing to run with
yet*. `providers-and-credentials/14` made that one function on purpose after
the CLI and the editor's banner were caught saying different things about the
same install. A fourth wording here would undo it.

## Findings, not exceptions

The refusal is a **runtime** fact about this machine, never a claim about the
document: the identical document runs the moment a credential exists, so
`validated: true` is untouched and nothing here reaches an exit code that means
*your workflow is wrong*. Each door says it in its own shape — a 503 on HTTP
(the deployment has nothing to run with, the same class of fact a missing
editor build reports), `error`/`findings` over MCP, an `error:` line and exit 1
in the terminal — but all three say **this** sentence.

## What counts as model-driven

`compile.node_runtime.drives_a_model(runtime)`, which is set where a node
actually asks the runtime for a model and unioned upward across a mount. Not a
list of node type names in this module: a node family contributed by a plugin
is handed `resolve_model` and declares itself by calling it, and a name list
here could never have known about it. The catalogue's `model_driven` set is the
*editor's* answer to a neighbouring question — which cards show the model
picker — and the two are checked against each other where they are declared,
not restated here.
"""

from __future__ import annotations

__all__ = ["NEXT_STEP", "unmet_model_requirement", "would_reach_no_model"]

#: What to do about it — appended to the readiness sentence, never folded into
#: it. `docs-onramp/09`: the refusal was true, short, and the point at which
#: install-to-first-answer stopped, because the two commands that finish the job
#: were not named at the moment of failure. `docs/declaring-a-next-step.md` is
#: this repository's own rule for the shape, written for somebody else's MCP
#: server: *a destination, not an apology*, naming the command and the argument.
#:
#: Appended **here** rather than in `elected_default().reason`, which is what
#: `openstategraph providers` prints as its header and what `GET /api/providers`
#: publishes as `run_readiness`. A next step in the reason itself would tell a
#: reader of the providers table to run the providers table, and the editor's
#: banner already has a *Show me where* button instead of a sentence. So the
#: reason stays a reason and the *refusal* carries the step — one composition,
#: three doors.
NEXT_STEP = (
    "Next step: run `openstategraph providers` to see which variable each "
    "provider reads and whether this machine has it, then "
    "`openstategraph env-example` to print the block to paste into `.env`."
)


def would_reach_no_model(*, drives_model: bool, model: object) -> bool:
    """Whether this run is certain to reach a model it cannot call.

    Two facts, and it takes both. Either alone produces a wrong refusal, and
    one of them cost a suite-wide red before this function existed:

    - **`drives_model`** — the compiler's own account, `node_runtime.
      drives_a_model(runtime)`. False for a graph of functions, tools and
      outputs, which is entitled to run with no provider at all and does.
    - **the model this run actually holds.** An `UnconfiguredProvider` is the
      stand-in `build_chat_model` returns for a machine that cannot call the
      elected provider — it raises on any attribute access, which is exactly
      the node failure this ticket is about, deferred. Anything else is a model
      somebody built and handed over, and asking the *catalogue* instead would
      refuse it: a caller that supplies its own model (a fake in a test, a
      client a host application built) is not asking this installation for a
      credential.

    `isinstance` and not a `try`, because the stand-in's whole design is that
    touching it raises; the point here is to find that out **without** touching
    it.
    """
    if not drives_model:
        return False
    from openstategraph.chat_model import UnconfiguredProvider

    return isinstance(model, UnconfiguredProvider)


def unmet_model_requirement(*, no_model: bool) -> str | None:
    """The readiness sentence for a run that has nothing to run with, or `None`.

    Split from `would_reach_no_model` for one reason: the CLI door holds a
    `CompiledWorkflow` and not a model, so the *predicate* is answered where the
    model is (`load_workflow`, recorded as `CompiledWorkflow.needs_a_provider`)
    and the *sentence* is composed here, once, for all three doors. Two
    functions in one module rather than one function three doors can each get
    half right.

    Evaluated per call rather than cached: a browser-held credential is applied
    to the process moments before this is asked, and a memoised answer would
    refuse a run the caller had just made possible.
    """
    if not no_model:
        return None
    from openstategraph.providers import provider_catalogue

    return f"{provider_catalogue().elected_default().reason}. {NEXT_STEP}"
