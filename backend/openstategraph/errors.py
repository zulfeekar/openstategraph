"""The exceptions an adopter may catch. **Tier 1 — semver-public.**

Before this module, `load_workflow` raised a bare `FileNotFoundError` for a
directory with no `workflow.json` and a bare `ValueError` for a directory name
that cannot be a slug. A service embedding a workflow could not tell either
apart from its *own* file and value errors, so the only available handler was
`except Exception`, which swallows the bugs you want to see.

**Every class here inherits from both `OpenStateGraphError` and the builtin it
used to be.** That is not decoration: `except FileNotFoundError` in code
written against an earlier release keeps working, unchanged, while
`except OpenStateGraphError` becomes available to anyone who wants the narrow
handler. A new exception hierarchy that breaks existing handlers would be a
worse trade than the untyped errors it replaces.

Deliberately small. An exception type is a promise to keep raising it, so this
module holds only failures the code raises **today** (plus `SchemaVersionError`,
which the version guard raises — ticket 04, same batch). Findings that are
*reported* rather than raised — an unknown node type, an unresolved tool —
stay on `.warnings` and in validation output, because raising them would break
the "degrade loud, never silent" rule that lets a workflow with one bad tool
still answer the questions it can.
"""

from __future__ import annotations


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


__all__ = [
    "GENERIC_FAILURE_MESSAGE",
    "CredentialError",
    "DocumentError",
    "InvalidPackageName",
    "MissingProviderKey",
    "MissingProviderPackage",
    "OpenStateGraphError",
    "PackageNotFound",
    "ProviderRefusedCredential",
    "SchemaVersionError",
    "WorkflowPackageError",
]
