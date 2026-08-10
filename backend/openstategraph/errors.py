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


class OpenStateGraphError(Exception):
    """Base for every error this framework raises on purpose.

    `except OpenStateGraphError` is the one handler that means "the workflow
    layer failed", as distinct from the model, the network, or your own code.
    """


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


class MissingProviderKey(OpenStateGraphError, RuntimeError):
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


__all__ = [
    "DocumentError",
    "InvalidPackageName",
    "MissingProviderKey",
    "OpenStateGraphError",
    "PackageNotFound",
    "SchemaVersionError",
    "WorkflowPackageError",
]
