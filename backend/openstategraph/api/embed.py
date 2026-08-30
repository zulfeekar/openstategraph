"""Mounting the whole product inside an application somebody else wrote.

**Tier 3, internal, and `[server]`-only.** Everything here imports FastAPI,
which is the extra — `CompiledWorkflow.events(...)` and the rest of the
library stay framework-free, and nothing in `core` or `compile` may import
this module.

## The shape this exists for

`docs/adoption.md` has offered two shapes: *host our server*, and *embed the
library and own the HTTP layer*. A team running a service wants the third and
has had no way to get it — their process keeps every route it already had,
**and** serves the canvas, `/chat` and the API under a path of their choosing,
reading the same `workflows/` directory the service loads. One process, two
surfaces, one directory.

`FastAPI.mount` is the whole mechanism and it is four lines. What made those
four lines impossible were three facts, none of them visible from a host:

1. **`create_app()` returned an app with no editor.** `mount_editor(app)` was
   applied to the module-level singleton at the bottom of `api/main.py`, after
   the factory returned — so the documented factory gave you the API and
   `/chat` and no canvas, and the only way to a canvas was to reach past it
   and mount `api.main.app`, the process-wide instance with its own workflows
   root. Nothing said so.
2. **The built page named every URL from the origin root.** Under a mount at
   `/osg`, `/assets/index-*.js` is a request to the *host's* root, which the
   host answers with its own 404: the page loads and nothing in it does. The
   fix is on both sides of the seam — a relative build base, and the
   `<base href>` `editor_assets.with_base_href` stamps into the served
   document. Neither half works alone.
3. **A mounted sub-application's lifespan never runs.** Starlette does not
   propagate it. Ours locks the state directory and, on the way out, releases
   every sqlite handle `WorkflowServices` owns — so a host mount would have
   held the checkpointer open for the life of the process and told nobody.

## What a host writes

```python
from fastapi import FastAPI
from openstategraph.api.embed import mount_openstategraph

app = FastAPI()          # your service, with all of your routes
mount_openstategraph(app, "/osg", workflows_root="workflows")
```

Serving the editor's files still requires `OPENSTATEGRAPH_SERVE_STATIC=1`,
unchanged and deliberately: a host that wants only the API mounted — no
canvas, no static assets in its process — gets exactly that by leaving it
unset, and the API answers either way.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Mapping

logger = logging.getLogger(__name__)


def _checked(path: str) -> str:
    """A rooted prefix with no trailing slash, or a refusal.

    Starlette accepts `"osg"`, `"/osg/"` and `""` and behaves differently for
    each; two of the three produce a mount that half works. A `ValueError` at
    import time is a stack trace in a developer's terminal, which is the
    cheapest place this can possibly fail.
    """
    if path == "/":
        return ""
    if not path.startswith("/") or path.endswith("/"):
        raise ValueError(
            f"mount path must be rooted and carry no trailing slash: {path!r} "
            '(for example "/osg", or "/" for the origin root)'
        )
    return path


def mount_openstategraph(
    app: Any,
    path: str = "/osg",
    *,
    workflows_root: Any = None,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Mount the product on `app` at `path`, and hand back the mounted app.

    Returns the sub-application rather than `None` so a host can reach
    `mounted.state.services` — the assembly point everything else already goes
    through — without a second construction path.
    """
    from openstategraph.api.editor_assets import mount_editor
    from openstategraph.api.main import create_app

    prefix = _checked(path)
    mounted = create_app(workflows_root=workflows_root)
    mount_editor(mounted, env, base_path=prefix or "/")
    app.mount(prefix or "/", mounted, name="openstategraph")
    _chain_lifespan(app, mounted)
    logger.info("OpenStateGraph mounted at %s", prefix or "/")
    return mounted


def _chain_lifespan(host: Any, mounted: Any) -> None:
    """Run the mounted app's lifespan inside the host's.

    Wrapping `router.lifespan_context` rather than adding startup and shutdown
    handlers, because the mounted app's lifespan is a single context manager
    whose two halves must bracket the host's — the state lock has to be held
    before anything can serve, and the sqlite handles released after the last
    request has completed. Two handlers cannot express that; one wrapper can.

    Read once and closed over, so calling this twice for two mounts nests them
    rather than losing one.
    """
    outer = host.router.lifespan_context

    @asynccontextmanager
    async def chained(app: Any) -> AsyncIterator[None]:
        async with mounted.router.lifespan_context(mounted):
            async with outer(app):
                yield

    host.router.lifespan_context = chained
