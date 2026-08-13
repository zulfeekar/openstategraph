"""Who a run is for — decided by the server, never asserted by the client.

Memory-hardening ticket 01. Long-term memory is namespaced per person
(`memory.py`), and until this module existed that namespace was keyed on
`RunRequest.user_email` — a value the browser typed into a box and sent
verbatim. Any client could read and write any person's memories by naming
them, with no exploit required: it was the interface working as built.

`api/auth.py` did not close it and does not try to. It is **admission, not
identity**: one shared bearer token, every holder the same principal, exactly
as `decisions/mcp-layer.md` §5 records. Admission answers "may this request
happen"; this module answers "on whose behalf".

The rule it enforces is one this codebase already wrote, in
`prebuilt_session.py`:

    An identity a model can pass as an argument is an identity a
    prompt-injected document can rewrite — and here that would mean reading
    another person's memories.

That closed the *model* channel. The transport channel stayed open, because
the transport was relaying what the browser said. This closes it, and the
default is to refuse: a deployment that has configured no identity has no
identities, and user-scoped memory does not bind at all.

**No abstract base class here, deliberately.** The interface is a `Protocol`
and the two implementations share nothing but it — one refuses, one reads a
header. An `AbstractPrincipals` holding two fields would be a hierarchy that
had not earned itself, which CLAUDE.md names outright. A third implementation
(a session store, an OIDC verifier) is a *collaborator a caller supplies*,
not a subclass: `WorkflowServices(principals=…)` is the same injection seam
that already owns the store, the checkpointer, the tools and the middleware.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

#: The environment's opt-in. Named after what it holds — the header a *trusted
#: proxy* sets — because the danger is precise: reading a header the client
#: can also set is the bug this module exists to remove.
PRINCIPAL_HEADER_ENV = "OPENSTATEGRAPH_PRINCIPAL_HEADER"


@dataclass(frozen=True)
class Principal:
    """One identified person, as the server determined them.

    `id` is what keys a memory namespace, so it is normalised once here —
    folded to lower case — and never again at a call site. `memory.py` applies
    its own label hygiene (periods are not legal in a Store namespace label)
    on top; that is a storage concern, and this is an identity concern.
    """

    id: str
    #: For display only. Never keys anything, so it may be anything.
    label: str = ""


@runtime_checkable
class IPrincipals(Protocol):
    """Resolves a request's headers to the person it is on behalf of."""

    def resolve(self, headers: Mapping[str, str]) -> Principal | None:
        """The person, or `None` when this deployment cannot identify one."""
        ...


class NoPrincipals:
    """The default: nobody is identified, whatever the request claims.

    Not a stub awaiting a real implementation — it is the correct behaviour
    for every deployment that has not configured identity, and the reason the
    dangerous default is gone. Its consequence is deliberate and reported:
    user-scoped memory does not bind, and the run says so.
    """

    def resolve(self, headers: Mapping[str, str]) -> Principal | None:
        return None


class TrustedHeaderPrincipals:
    """Identity from a header a reverse proxy sets.

    The common production shape — an authenticating proxy (oauth2-proxy,
    Cloudflare Access, an ALB with OIDC) terminates auth and forwards the
    verified identity as a header.

    **Safe only if the proxy strips any client-supplied copy of that header.**
    That is the deployment's job, not this code's — which is exactly why it is
    opt-in by name rather than a list of headers we guess at. Guessing would
    reintroduce the defect: a header we read speculatively is a header a
    client can set.
    """

    def __init__(self, header: str) -> None:
        cleaned = (header or "").strip()
        if not cleaned:
            # A resolver reading "" would match nothing while looking
            # configured — the silent-misconfiguration shape this project
            # treats as worse than a failure.
            raise ValueError(f"{PRINCIPAL_HEADER_ENV} needs a header name")
        self._header = cleaned.lower()

    def resolve(self, headers: Mapping[str, str]) -> Principal | None:
        # HTTP header names are case-insensitive; a Mapping's keys are not.
        for name, value in headers.items():
            if name.lower() != self._header:
                continue
            cleaned = value.strip().lower()
            return Principal(id=cleaned, label=value.strip()) if cleaned else None
        return None


def principals_from_env() -> IPrincipals:
    """The resolver this deployment configured, or the refusing one.

    A blank value reads as *unset*, matching `auth.py`'s own reading of its
    variable: "`OPENSTATEGRAPH_API_TOKEN=` left in a `.env` is somebody
    turning it off."
    """
    header = os.environ.get(PRINCIPAL_HEADER_ENV, "").strip()
    return TrustedHeaderPrincipals(header) if header else NoPrincipals()
