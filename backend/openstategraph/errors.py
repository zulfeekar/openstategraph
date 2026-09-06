"""The exceptions an adopter may catch. **Tier 1 — semver-public.**

Before this module, `load_workflow` raised a bare `FileNotFoundError` for a
directory with no `workflow.json` and a bare `ValueError` for a directory name
that cannot be a slug. A service embedding a workflow could not tell either
apart from its *own* file and value errors, so the only available handler was
`except Exception`, which swallows the bugs you want to see.

**A class here inherits from both `OpenStateGraphError` and the builtin it used
to be.** That is not decoration: `except FileNotFoundError` in code written
against an earlier release keeps working, unchanged, while
`except OpenStateGraphError` becomes available to anyone who wants the narrow
handler. A new exception hierarchy that breaks existing handlers would be a
worse trade than the untyped errors it replaces.

The rule is *the builtin it used to be*, so a failure that was never a builtin
gets none — `ProviderUnreachable` is the one, and says why at itself. Until
providers-and-credentials 08 this paragraph said "every class", which read as
a requirement to invent a base rather than as the compatibility promise it is.

Deliberately small. An exception type is a promise to keep raising it, so this
module holds only failures the code raises **today** (plus `SchemaVersionError`,
which the version guard raises — ticket 04, same batch). Findings that are
*reported* rather than raised — an unknown node type, an unresolved tool —
stay on `.warnings` and in validation output, because raising them would break
the "degrade loud, never silent" rule that lets a workflow with one bad tool
still answer the questions it can.
"""

from __future__ import annotations

from typing import Any


#: What someone who cannot fix it is told, whatever went wrong.
#:
#: One sentence, in one place, because it is shown by three surfaces — the
#: run's `answer`, a terminal `error` frame's `detail`, and a failed node's
#: entry in `outputs`. Three copies of a sentence is three chances to fix two
#: of them.
GENERIC_FAILURE_MESSAGE = (
    "The workflow could not finish — a step failed before an answer was "
    "produced. Try again, or contact whoever runs this workflow."
)


class OpenStateGraphError(Exception):
    """Base for every error this framework raises on purpose.

    `except OpenStateGraphError` is the one handler that means "the workflow
    layer failed", as distinct from the model, the network, or your own code.

    **It also knows how to read.** An error is shown to two audiences that
    need different things, and asking *what kind of error is this* at each
    surface is a type switch standing in for polymorphism — the shape this
    project's own rules reject. The two methods below are the whole interface;
    a subclass with nothing special to say inherits both.

    There is deliberately no `IError` protocol above this. Python's `except`
    is the consumer, and it accepts only classes deriving from
    `BaseException` — `except SomeProtocol` raises `TypeError: catching
    classes that do not inherit from BaseException`. An interface no consumer
    can bind to is unbindable rather than merely leaky, the same reason
    `CLAUDE.md` gives for refusing `IOrchestrator`. This class **is** the
    interface, and `Exception` is the ladder's abstract rung.
    """

    def developer_message(self) -> str:
        """This error, for someone who can act on it.

        `str(self)` by default: our own errors are written as the copy, which
        is the point of raising them instead of a vendor's. Overridden only
        where a developer needs more than the sentence a customer's absence
        of detail is derived from.
        """
        return str(self)

    def customer_message(self) -> str:
        """This error, for someone who cannot act on it.

        Generic by default, and that is the safe direction: a subclass opts
        *in* to saying more, so a new error type cannot leak a variable name
        or a file path to a customer by forgetting to override anything.
        """
        return GENERIC_FAILURE_MESSAGE


class WorkflowPackageError(OpenStateGraphError):
    """The package on disk is not one we can load.

    The package — the folder with `workflow.json`, `tools/`, `functions/` — is
    the artifact an adopter commits, so its failures are grouped: a caller
    scanning a directory of packages wants one `except` for "skip this
    folder", not a list.
    """


class PackageNotFound(WorkflowPackageError, FileNotFoundError):
    """No `workflow.json` in the directory that was passed."""


class InvalidPackageName(WorkflowPackageError, ValueError):
    """The directory name cannot be a slug, so nothing would be discovered.

    Raised rather than degraded on purpose: the slug scopes tool, function,
    skill and knowledge discovery, so a package the store cannot address would
    load, compile, run and quietly find none of its own capabilities.
    """


class DocumentError(OpenStateGraphError, ValueError):
    """The payload is not shaped like a workflow document."""


class SchemaVersionError(DocumentError):
    """The document's schema version is not one this build can read.

    Both directions: too new (a future OpenStateGraph wrote it, and
    best-effort compiling it would produce a graph that runs and answers
    differently) and too old to migrate. The message names both versions —
    see `openstategraph.schema`.
    """


class RunContextError(OpenStateGraphError, ValueError):
    """A run supplied run context the workflow did not ask for, or omitted some
    it did.

    `organisms-first-class/70`. **The caller is wrong, not the document** —
    which is what separates this from `DocumentError`, its sibling for a
    payload that is not shaped like a workflow. A declaration that is itself
    malformed is still a `plan.warnings` problem and still exits `validate`
    non-zero; this is the other side of the same field schema, raised when a
    run tries to fill it.

    Typed rather than left a bare `ValueError` for this module's standing
    reason, and with one that is particular to it: the failure it replaces was
    `TypeError: RunContext.__init__() got an unexpected keyword argument
    'zzz'`, raised by a `dataclasses`-generated `__init__` naming a class the
    workflow author never wrote and cannot see. That message names neither the
    workflow nor anything the author can act on, it is not catchable apart from
    any other `TypeError` in the process, and it arrives from inside
    `graph.invoke` rather than at the door. Every sentence this class carries
    names the offending **key** and the **workflow**.
    """


class ThreadNotResumable(OpenStateGraphError, ValueError):
    """`CompiledWorkflow.resume()` was asked to continue a thread it cannot.

    Three distinct causes, one type, because the caller's move is the same for
    all three — say so and stop: the checkpointer holds no such thread; the
    thread finished and has no pause waiting for a decision; or the thread
    belongs to a different package, which a shared saver makes perfectly
    findable from the wrong one. The message names which.

    Typed rather than left a bare `ValueError` for the reason this module
    exists: a service embedding a workflow needs "that approval is already
    answered" to be catchable apart from its own value errors, and a person at
    a terminal needs it to be a sentence rather than a traceback.
    """


class CredentialError(OpenStateGraphError, RuntimeError):
    """A provider's credential is the reason this run cannot proceed.

    The family exists because there are two of these and they are **not the
    same failure**: a credential that is absent and one that was read and
    refused need opposite actions from the reader, and a caller who wants to
    handle "anything to do with credentials" should not have to list them.

    Groups the way `WorkflowPackageError` groups package failures, and for the
    same reason: one `except` for one decision.
    """


class MissingProviderKey(CredentialError):
    """A model names a provider whose credential is not set (ticket 03).

    Raised in place of the vendor SDK's own error, which names *its*
    environment variable and knows nothing about this project's `.env` or
    `.env.example` — so an adopter had to work out for themselves that the two
    were the same thing. The message carries the exact fix, built by
    `providers.ProviderSpec.missing_key_message`.

    Deliberately loud rather than a fallback to a working provider: silently
    answering with a different model than the one asked for is the failure mode
    that costs an afternoon, because the run *succeeds*.
    """


class MissingProviderSetting(OpenStateGraphError, RuntimeError):
    """A provider's credential is present and its constructor still cannot run.

    The **fifth** provider shape, and deliberately **not** a `CredentialError`
    — which is the whole reason it is a class of its own rather than a
    `MissingProviderKey` with different words. Both of that family's actions —
    set the key, replace the key — are wrong advice here: the key is set, is
    correct, and is not what is missing. Azure OpenAI needs an endpoint and an
    api-version as well, and a service that had all four under their real
    names got `pydantic_core.ValidationError` out of `AzureChatOpenAI` and a
    500 carrying no sentence at all (providers-and-credentials/18).

    The message names the variable and is built by `providers.ProviderGap`,
    beside the other four, so the five shapes stay in one voice.
    """


class ProviderUnreachable(OpenStateGraphError):
    """A provider's address is configured, and nothing is listening at it.

    The **fourth** provider shape, and not a `CredentialError`: no credential
    was absent and none was rejected, so both of that family's actions — set
    the variable, replace the value — are the wrong advice. What is wrong is
    the *address*, or the daemon that should be answering at it. Ticket 03's
    matrix enumerated absent, wrong and valid; this is the one a developer is
    most likely to reach by accident, having set `OLLAMA_HOST` once, stopped
    the daemon, and forgotten (providers-and-credentials 08).

    **The only class here that carries no builtin base, deliberately.** Every
    other one keeps the builtin it used to be, so an existing `except` keeps
    working. This was never a builtin: it arrived as `httpx.ConnectError`,
    which is a vendor's type, and the tempting builtin — `ConnectionError` —
    is an `OSError`, which would put every unreachable provider inside the
    `except OSError` an adopter wrote around their file handling. A base that
    captures an error in handlers written for something else is worse than no
    base at all.

    Constructed by `chat_model.unreachable_endpoint_error_from`, the sibling
    adapter to `credential_error_from`, and worded by
    `providers.ProviderEnvironment.unreachable_endpoint_message`.
    """


class StepBudgetExhausted(OpenStateGraphError):
    """A run spent its whole step budget without reaching an answer.

    **Two events, one class, and the reason they share it is that the fix for
    the second was to stop them differing** (`launch-readiness/176`). Until
    that ticket this said *a mounted workflow*, and it was accurate: the mount
    boundary translated LangGraph's exhaustion and the **top-level** case — the
    common one, every document without a mount — reached `ask()`, the CLI,
    `POST /api/runs`, MCP and the SSE `error` frame verbatim.

    They were weighed as siblings and kept as one. The candidate distinction
    was *the mount produced nothing, while a parent may have had a draft on
    `answer` that never reached an output node* — but a blocking door has no
    returned state at all when `ainvoke` raises, so that draft is not
    recoverable at three of the four doors and the difference cannot be acted
    on. What both events **are** is the same: the ceiling stopped a graph that
    was still running, there is no answer to publish, and the reader's next
    move is the drawing rather than a retry. Two classes would have given an
    adopter two `except` clauses for one condition.

    The *sentences* still differ, because the mount has one more thing to say
    — which package, and whether its own saved budget was overruled — and
    `run_journal.budget_exhausted` leaves an error that is already ours alone
    for exactly that reason. The top-level wording lives in
    `step_budget.step_budget_exhausted_message`, beside the vocabulary.

    `organisms-first-class` 60, on the mount. A mount is *"another workflow run as one
    isolated step — task in, answer out"*, and the child is a separate
    `invoke` with its own superstep counter but the **run's** number: a
    mount inherits the budget of the run that mounted it. When the child's
    own guard cannot fire — `56`'s rule needs a few supersteps of slack to
    stop a loop and still publish — the exhaustion arrives at the mount
    boundary as LangGraph's `GraphRecursionError`, and it used to be
    reported verbatim: a vendor's advice to *increase the limit*, which
    `step_budget.py` and `stepBudget.ts` exist to contradict, plus a
    `docs.langchain.com` URL no other copy in this product carries.

    So the boundary translates it, exactly as `credential_error_from`
    translates a vendor's `AuthenticationError`: once a foreign failure is
    one of ours, every surface treats it like any other error we raise
    rather than re-deciding what it meant.

    **No builtin base**, the second class here without one and for
    `ProviderUnreachable`'s reason. It was never a builtin: it arrived as
    `GraphRecursionError`, which derives from `RecursionError`, and keeping
    that would put every exhausted mount inside an `except RecursionError`
    an adopter wrote around their own deep recursion — a base that captures
    an error in handlers written for something else is worse than none.

    It stays a **failure** rather than a report, unlike the loop door's
    budget stop: there the graph had a candidate to publish, and here the
    step produced nothing at all. A mount that quietly answered nothing
    would be the silence `production-ready` 96 exists to name.

    **And it is written down.** Neither event used to leave a row in the run
    store, so the two runs that cost the most and returned nothing were the
    ones a reader asking *what has this machine run, and what did it cost* was
    never told about. Both now record `kind="exhausted"`
    (`run_journal.EXHAUSTED_KIND`), which is deliberately neither `failed` —
    no node wrote the failure sentinel — nor a finished `run`.
    """


class MissingProviderPackage(OpenStateGraphError, ImportError):
    """A model names a provider whose LangChain integration is not installed.

    The *other* wall in front of a model call, and deliberately **not** a
    `CredentialError`: setting a variable cannot fix it and `pip` cannot fix a
    missing key, so a caller handling one has nothing useful to do about the
    other. What they share is a shape, not a family — both are refusals this
    framework writes itself, in one line, at the moment a model is used
    (workflow-gallery ticket 38).

    `ImportError` is kept as a base for the reason every class in this module
    keeps the builtin it used to be: this arrived as a bare ImportError out of
    `init_chat_model`, `cli.main` catches ImportError to exit 3 on a missing
    extra, and an adopter's `except ImportError` around `load_workflow` keeps
    working unchanged.
    """


class NoProviderInstalled(OpenStateGraphError, ImportError):
    """Nothing this install can call a model with, asked before a run starts.

    The sibling of `MissingProviderPackage`: that one is *this* model's
    provider missing, this one is **every** provider missing, which is a
    different sentence — there is no vendor to name, only a choice of install
    lines. It is the state a bare `pip install openstategraph` leaves, and also
    the state a typo'd extra leaves, because pip warns and exits 0 for an extra
    a distribution does not declare.

    Raised by `resolve_model` when nothing was asked for and there is no
    candidate to elect. Returning a model name instead would hand back a
    provider that cannot be imported and let the failure surface as a vendor
    traceback three layers down — the round trip workflow-gallery ticket 38
    exists to end.

    `ImportError` for the reason `MissingProviderPackage` keeps it: `cli.main`
    catches ImportError to exit 3 on a missing extra, and an adopter's
    `except ImportError` around `load_workflow` keeps working unchanged.
    """


class UnknownProvider(OpenStateGraphError, ValueError):
    """A model reference names a prefix, and the prefix names nothing.

    Raised only where the reference cannot be rescued downstream: a **trailing
    colon** (`"nosuchvendor:"`) is a provider with an empty model name, and an
    empty model name is refused by every vendor SDK after a round trip that
    names none of this.

    Deliberately **not** raised for an unprefixed model name. `init_chat_model`
    resolves an unambiguous one itself (`"gpt-5.5"` → OpenAI), and
    `providers.py` exists because our own enumerations were narrower than the
    library's — so refusing what we do not recognise would put that narrowing
    back. `ValueError` is kept as a base because that is what a bad model
    string used to arrive as.
    """


class ProviderRefusedCredential(CredentialError):
    """A credential was read, sent, and rejected by the vendor.

    The sibling of `MissingProviderKey`, and the distinction is the whole
    point: *not set* and *set but wrong* need opposite actions, and until this
    existed only the first had words of ours — the second arrived as the
    vendor's own error, a raw dict which in OpenAI's case embeds a fragment of
    the key.

    Constructed by `chat_model.credential_error_from`, which is the adapter
    from a vendor SDK's exception into this hierarchy. That translation is why
    this is a class and not a formatted string: once a foreign failure becomes
    one of ours, every surface treats it like any other error we raise, rather
    than each one re-deciding what an `AuthenticationError` means.
    """


class RunProducedNothing(OpenStateGraphError):
    """A run finished with no answer, and something went wrong on the way.

    **The silent half of `launch-readiness/171`, and fixed independently of
    its cause.** `CompiledWorkflow.ask` returned a `RunResult` that *is* an
    empty string, with the reason on `.warnings` — a field the README's own
    example never mentions. A reader who followed the published shape

        print(workflow.ask("Say the word banana."))

    got a blank line and no way to know a node had died. Whatever the next
    cause turns out to be, that shape must not come back, so the door raises
    rather than returning nothing.

    **Only the pair raises, never either half.** An empty answer with nothing
    wrong is legal — a workflow may answer with nothing — and a step that
    failed while another node still answered is a *degrade*, which this project
    prefers to a crash. The predicate is `results.produced_nothing`, which is
    the same rule `cli.run_exit_code` has gated on since `workflow-gallery` 53,
    read from one place so an exit code and a raise cannot disagree about what
    a failed run is. A run paused at a `human.approval` gate is not a failure
    either: it is waiting, and it returns.

    **Nothing is lost by raising.** `async-first/13`'s rule for a diagnosis is
    that it is chained and never substituted; there is no live exception to
    chain here — the node failure was already recorded and swallowed by the
    retry recorder — so the whole `RunResult` rides on `.result` instead.
    Every field a caller could have read is still readable:

        try:
            answer = workflow.ask(question)
        except RunProducedNothing as nothing:
            print(nothing.result.warnings)
    """

    #: The run that produced no answer, exactly as it would have been returned.
    result: Any

    def __init__(self, message: str, result: Any = None) -> None:
        super().__init__(message)
        self.result = result

    @classmethod
    def of(cls, result: Any) -> "RunProducedNothing":
        """The one sentence, built from the run's own report.

        A classmethod rather than a formatted string at the call site because
        `ask` and `resume` both raise this, and two spellings of one sentence
        is the duplication rule failing where a reader would notice it least.
        """
        reasons = list(getattr(result, "failures", None) or []) or list(
            getattr(result, "warnings", None) or []
        )
        first = reasons[0].rstrip(". ") if reasons else ""
        more = f", and {len(reasons) - 1} more" if len(reasons) > 1 else ""
        detail = f" {first}{more}." if first else ""
        return cls(
            "The workflow ran and produced no answer."
            + detail
            + " The whole run — warnings, outputs, decisions — is on this "
            "error's `.result`.",
            result,
        )


__all__ = [
    "GENERIC_FAILURE_MESSAGE",
    "CredentialError",
    "DocumentError",
    "InvalidPackageName",
    "MissingProviderKey",
    "MissingProviderSetting",
    "MissingProviderPackage",
    "NoProviderInstalled",
    "OpenStateGraphError",
    "PackageNotFound",
    "ProviderRefusedCredential",
    "ProviderUnreachable",
    "RunContextError",
    "RunProducedNothing",
    "SchemaVersionError",
    "StepBudgetExhausted",
    "ThreadNotResumable",
    "UnknownProvider",
    "WorkflowPackageError",
]
