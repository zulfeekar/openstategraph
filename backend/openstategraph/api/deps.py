"""How a route handler reaches the app's assembly.

`create_app` builds one `WorkflowServices` and every handler needs it. Until
reviews-2026-08-14 ticket 15 that was arranged by defining all thirty-two
handlers *inside* `create_app`, as closures over its locals — and over three
names unpacked from the very object that exists to hold them together::

    services = WorkflowServices(workflows_root)
    workflow_store = services.store
    memory_store = services.memory_store
    runtime_for = services.runtime_for

which is the same defect ticket 07 found in `NodeRuntime.__init__`: a
parameter object built and then immediately flattened, so the grouping lasts
exactly as long as the call. The comment there said the local names were kept
"so every endpoint reads as it did", and the cost was that no handler had a
name anything could import. A test of one route had to construct the whole
application.

`app.state.services` was already the assembly point — the module docstring in
`main.py` called it "reachable for ops and tests". This makes it the way in
for handlers too, so a handler can be a module-level function.

**A dependency, not a global.** `create_app` is a factory precisely so tests
get an isolated instance with its own `workflows_root`; a module-level
singleton would undo that. Reading it off the request keeps one app's services
with that app.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

# Imported for real, not under `TYPE_CHECKING`. FastAPI resolves a handler's
# annotations at registration time through Pydantic, and a forward reference
# it cannot resolve is not an error there — the parameter is taken for a
# **query parameter** instead, which is how `services` would have appeared in
# the published contract.
from openstategraph.api.services import WorkflowServices


def get_services(http: Request) -> WorkflowServices:
    """This app's assembly, from the request it is serving."""
    services: WorkflowServices = http.app.state.services
    return services


#: The annotation a handler uses: `def handler(services: Services) -> ...`.
#:
#: Invisible to OpenAPI — a `Depends` parameter is not a request parameter, and
#: `Request` contributes no schema — so moving a handler out of `create_app`
#: leaves `docs/openapi.json` byte-identical. That is the constraint ticket 15
#: set, and it is checkable rather than hoped for.
Services = Annotated[WorkflowServices, Depends(get_services)]


def get_principal_id(http: Request, services: Services) -> str:
    """Who this request is on behalf of — decided here, never sent here.

    The one line providers-and-credentials ticket 01 exists for.
    `user_email` used to be a field on `RunRequest`, typed into a box in
    `/chat` and copied into `configurable` unverified, where it became the key
    of a memory namespace: any client could read and write any person's
    memories by naming them.

    `auth.py` does not cover this and does not try to — it is admission (one
    shared token, every holder the same principal), and this is identity. The
    default resolver identifies nobody, so per-person memory does not bind
    until a deployment says how to know who someone is.

    A dependency rather than a closure inside `create_app` (ticket 15). It was
    always a pure function of the headers and the principal resolver, and the
    three run endpoints that call it are the ones that most need to be
    readable on their own.
    """
    who = services.principals.resolve(http.headers)
    return who.id if who is not None else ""


#: The identity a run executes under. Empty string means "nobody named".
PrincipalId = Annotated[str, Depends(get_principal_id)]
