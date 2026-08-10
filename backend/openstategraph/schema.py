"""The `workflow.json` document: one normalization seam, one version policy.

**Tier 1 — semver-public.**

The schema is the most public thing this project ships — more public than any
Python symbol, because a document is what a customer commits to *their*
repository and diffs in *their* pull requests. So peeling the store's envelope
and deciding whether a document is readable belongs in a named, public module,
not in an underscore-prefixed helper inside the HTTP tree.

That is exactly where it lived: `load_workflow` — the one documented entry
point — did `from openstategraph.api.registries import _document_of`, and
`mcp_server.py` carried a second, subtly different spelling of the same idea.
Two normalizers and a private import is how a guard ends up with a hole.

**And the version was decorative.** Every document in the tree carries
`"version": 2` and every envelope carries `"version": 1`, and before this
module *no code read either number* — no comparison, no branch, no migration,
no rejection. The number was propagated as folklore: `mcp_server` wrote the
literals, and `prebuilt_architect` taught a model to emit them in a prompt
string. The consequence for an adopter is the failure this codebase treats as
the worst kind: a document written by a future OpenStateGraph loads silently
into an older one, and any field whose *meaning* changed compiles into a graph
that runs, answers, and is wrong.

## Two numbers, and only one of them is the schema

    workflow.json
      { "version": 1,                 <- the STORE ENVELOPE's file format.
        "document": { "version": 2,      Private to the store. Not this.
                      "nodes": [...] } }  <- the SCHEMA version. This one.

Nothing in the tree may carry a third.

## The policy

| Situation | Behaviour |
| --- | --- |
| `version` absent | assume `SCHEMA_VERSION`, log one INFO line, stamp it |
| `version < SCHEMA_VERSION` | run the migration chain; log which ran |
| `version == SCHEMA_VERSION` | pass through, untouched |
| `version > SCHEMA_VERSION` | **raise `SchemaVersionError`** naming both |
| `version < MIN_SUPPORTED_VERSION` | raise `SchemaVersionError` |

**A document from the future is refused, not best-effort compiled.** This is
the one judgement call in the module, so here is the argument. A newer schema
means a field was removed, renamed, or had its *meaning* changed — those are
the only changes that bump the number (see below). An older build reading such
a document does not fail: it ignores what it does not recognise and compiles a
graph that runs and gives a different answer. There is no error, no warning at
the point of use, and nothing in the output that looks wrong. Refusing costs a
user one clear message naming both versions and one `pip install -U`; degrading
costs them a wrong answer they have no way to attribute. Everywhere else this
codebase prefers degrading loudly over failing — an unresolved tool is a
warning, a missing checkpointer falls back — because those failures are
*visible in the result*. A silently-different compile is not, so it is the
exception.

## What bumps the version, and what does not

This is the part that keeps the number from becoming folklore again.

- **Bump:** removing a field; renaming a field; changing a field's meaning or
  the effect of its default; changing a port id or a node type's id; changing
  the semantics of an edge.
- **Do not bump:** adding an optional field with a safe default; adding a new
  node type; adding a port to a new node type; anything additive that an older
  build ignores harmlessly. Additive-only is precisely why we are still on 2.

Every bump ships its `MIGRATIONS[n]` function **in the same commit**, plus a
fixture document at version *n* that the suite loads and compiles. A migration
chain nobody exercises is not a migration chain.

`MIN_SUPPORTED_VERSION` rises only in a major release.

This module imports nothing from the runtime, so it stays cheap.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from openstategraph.errors import DocumentError, SchemaVersionError

logger = logging.getLogger(__name__)

#: The schema version this build writes and understands.
SCHEMA_VERSION = 2

#: The oldest version this build will migrate from. Raised only in a major.
MIN_SUPPORTED_VERSION = 1

Migration = Callable[[dict[str, Any]], dict[str, Any]]

#: `from-version -> upgrade it to from+1`. The chain is walked in order, so a
#: v1 document passes through every step to `SCHEMA_VERSION`.
#:
#: `1 -> 2` is the identity, and that is a finding rather than a placeholder:
#: the difference between the two versions was **additive only** (new node
#: types and new optional fields), so there is genuinely nothing to transform.
#: It is registered explicitly instead of being skipped, because an absent key
#: means "unsupported" and a present identity means "checked, nothing to do" —
#: and the next real migration then has a chain to slot into rather than a
#: mechanism to invent under time pressure.
MIGRATIONS: dict[int, Migration] = {
    1: lambda document: document,
}


def document_version(document: dict[str, Any]) -> int:
    """The document's schema version. Absent means "written by this build".

    Absent is the friendly reading on purpose: hand-written and
    programmatically-assembled documents omit it constantly (the editor's
    export, a test fixture, an MCP client's first draft), and refusing those
    would punish the case the format is meant to make easy. It is logged, not
    silent, and `normalize_document` stamps the number on so the *next* reader
    is not guessing too.
    """
    raw = document.get("version")
    if raw is None:
        return SCHEMA_VERSION
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise SchemaVersionError(f"document version must be an integer, got {raw!r}")
    try:
        return int(raw)
    except ValueError as exc:
        raise SchemaVersionError(f"document version must be an integer, got {raw!r}") from exc


def migrate_document(document: dict[str, Any]) -> dict[str, Any]:
    """Bring a document up to `SCHEMA_VERSION`, or refuse it with both numbers.

    The seam exists before it is needed. A migration chain added on the day the
    first breaking change lands is a chain designed under deadline, against one
    example, by whoever happens to be holding the change — and the documents it
    has to read are already committed in other people's repositories by then.

    Never mutates its argument: a caller holding the on-disk payload keeps it.
    """
    from openstategraph import __version__

    version = document_version(document)

    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"this document is schema v{version}; this build of openstategraph "
            f"{__version__} understands up to v{SCHEMA_VERSION}. "
            f"Upgrade with `pip install -U openstategraph`."
        )
    if version < MIN_SUPPORTED_VERSION:
        raise SchemaVersionError(
            f"this document is schema v{version}; this build of openstategraph "
            f"{__version__} migrates from v{MIN_SUPPORTED_VERSION} and later. "
            f"Open it in an older release and re-save it to bring it forward."
        )

    if version == SCHEMA_VERSION:
        if document.get("version") is None:
            logger.info(
                "Document declares no schema version; reading it as v%d.", SCHEMA_VERSION
            )
            return {**document, "version": SCHEMA_VERSION}
        return document

    migrated = document
    for step in range(version, SCHEMA_VERSION):
        migration = MIGRATIONS.get(step)
        if migration is None:
            raise SchemaVersionError(
                f"no migration from schema v{step} to v{step + 1} — this document "
                f"(v{version}) cannot be brought forward by openstategraph {__version__}."
            )
        migrated = migration(dict(migrated))
    logger.info(
        "Migrated document from schema v%d to v%d (%d step(s)).",
        version,
        SCHEMA_VERSION,
        SCHEMA_VERSION - version,
    )
    return {**migrated, "version": SCHEMA_VERSION}


def normalize_document(payload: Any) -> dict[str, Any]:
    """The document, whatever shape it arrived in, at this build's schema.

    Three callers, three shapes, one meaning:

    - the store saves `{version, name, savedAt, document}` — the **envelope**;
    - the editor's export posts the bare document;
    - MCP clients serialize inconsistently and some send a JSON *string*.

    All three are accepted here rather than costing a client's model a round
    trip to learn our preference. Getting it wrong is silent in the worst way:
    compiling the envelope instead of the document produces a **zero-node
    graph** that builds, runs and answers nothing.

    The envelope's own `version` is the store's file format and is deliberately
    not consulted — only the document's.

    **This is the single seam.** `load_workflow`, the store's load, the MCP
    compile/validate tools and the HTTP run endpoints all arrive here, which is
    what gives the version guard no hole to leak through.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DocumentError(f"Not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DocumentError("The document must be a JSON object.")
    inner = payload.get("document")
    document = inner if isinstance(inner, dict) else payload
    return migrate_document(document)


__all__ = [
    "MIGRATIONS",
    "MIN_SUPPORTED_VERSION",
    "SCHEMA_VERSION",
    "Migration",
    "document_version",
    "migrate_document",
    "normalize_document",
]
