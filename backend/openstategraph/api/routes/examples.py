"""The shipped gallery: what exists, and taking one.

Workflow-gallery ticket 07. Two routes, and the split between them is the whole
design: the gallery is package data, so **reading** it never touches the
adopter's project, and **taking** one is an explicit write into their workflows
root that they asked for.

Its own module rather than another handler in `system.py` (which holds the
event stream, the health probe and the templates) because these two routes
share a subject and one of them mutates the catalogue — the concern `routes/
workflows.py` owns. Two subjects, two routers, per `routes/__init__.py`.

**Why the editor cannot do the copy itself.** Same reason `duplicate` is a
server route: a browser can import a document, but an example is a package —
`tests/`, `knowledge/`, `evals/`, `data/` — and a document-only import produces
nodes bound to tools that do not exist, a failure that surfaces at run time
long after the copy looked successful.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from openstategraph.api.deps import Services
from openstategraph.api.routes.workflows import announce
from openstategraph.api.schemas import CopyExampleResponse, ExampleResponse

router = APIRouter()


@router.get(
    "/api/examples",
    response_model=list[ExampleResponse],
    summary="The worked examples that ship with OpenStateGraph",
    tags=["Authoring"],
)
def list_examples() -> list[ExampleResponse]:
    """The gallery, in reading order — the same list `openstategraph examples
    list` prints, from the same catalogue.

    Reads package data only. These are **not** the caller's workflows and never
    appear in `GET /api/workflows`: they are not under the workflows root, so
    no customer surface, platform tool or `/chat` picker can see them until one
    has been copied (gallery ticket 33).
    """
    from openstategraph import examples

    return [
        ExampleResponse(
            slug=example.slug,
            name=example.name,
            summary=example.summary,
            pattern=example.pattern,
            requires=list(example.requires()),
        )
        for example in examples.catalogue()
    ]


@router.post(
    "/api/examples/{slug}/copy",
    response_model=CopyExampleResponse,
    status_code=201,
    summary="Copy an example into this project's workflows",
    tags=["Authoring"],
)
def copy_example_route(services: Services, slug: str) -> CopyExampleResponse:
    """Copy the example, and every package it mounts, into the workflows root.

    The copy severs it: from here it is an ordinary package of the adopter's,
    a draft until they publish it, and a later `pip install -U` does not reach
    back into it. `openstategraph.examples` records why an example is never
    mounted where it lies.

    404 for a slug the gallery does not have, 409 when a directory of that name
    is already there — refused for the whole set before anything is written,
    so a conflict never leaves half a dependency chain on disk.
    """
    from openstategraph import examples
    from openstategraph.scaffold import ScaffoldError, copy_example

    try:
        written = copy_example(services.store.root, slug)
    except examples.UnknownExampleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ScaffoldError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    copied = [path.name for path in written]
    for created in copied:
        announce(services, "saved", created)
    return CopyExampleResponse(slug=slug, copied=copied)
