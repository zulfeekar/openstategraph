"""The wheel carries the canvas — scale-and-adopt ticket 01.

`pip install openstategraph` used to deliver a *visual* workflow builder with
no visuals: 215 KB of Python, and a canvas that existed only inside a git clone
or the Docker image. This hook is what puts the built editor in the
distribution, so `pip install "openstategraph[server]" && openstategraph serve`
opens the real product on a machine that has never seen the repository.

**Where the assets come from**, in order:

1. `OPENSTATEGRAPH_EDITOR_DIST` — an explicit directory, for a release job that
   builds the front end somewhere else.
2. `<repo>/dist` — what `npm run build` writes in a checkout.
3. `openstategraph/api/static/editor` — already in place, which is the case
   when a wheel is being built *from our sdist*. Nothing to copy; hatchling
   ships it as ordinary package data.

**Sourcemaps are excluded.** They are 18 MB against the bundle's 5, they are a
debugging aid for people working on this repository, and nobody debugging their
own workflow needs to step through our minified React.

**A standard build with no editor anywhere FAILS, loudly.** That is the whole
point of the ticket: a wheel that silently ships without the canvas is exactly
the artifact we are replacing. Editable installs (`pip install -e backend`) are
exempt, because that is the contributor path — CI installs the backend that way
with no Node.js in the job, and a source checkout is expected to run the dev
stack or `npm run build` when it wants the editor.

The decision lives in `editor_force_include`, a free function over paths, so
`backend/tests/test_distribution_metadata.py` can exercise the failure without
running a build. The class below is the hatchling adapter and nothing else.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ModuleNotFoundError:  # pragma: no cover — outside a build environment
    # hatchling is a build-time dependency and is not installed in the dev
    # venv. The adapter is unusable without it; the logic below is not, and
    # that is the half worth testing.
    BuildHookInterface = object  # type: ignore[assignment,misc]

#: Inside the package, so it is ordinary package data once written and every
#: consumer (`api/editor_assets.py`) has one place to look.
EDITOR_DEST = "openstategraph/api/static/editor"

#: The /chat live-flow view's Mermaid, served by `api/main.py:chat_mermaid_asset`
#: with no CDN. Kept out of `editor/` so that directory stays a faithful copy of
#: `dist/`.
VENDOR_DEST = "openstategraph/api/static/vendor"

MERMAID_SOURCE = "node_modules/mermaid/dist/mermaid.min.js"

#: Debugging aids for this repository, not for an adopter. 18 MB of the 23 MB
#: `dist/` weighs.
EXCLUDED_SUFFIXES = (".map",)

NOT_BUILT = (
    "no built editor found — the wheel would ship a visual workflow builder "
    "with no visuals.\n"
    "Build it first:\n"
    "    npm ci && npm run build\n"
    "or point the build at an existing one:\n"
    "    OPENSTATEGRAPH_EDITOR_DIST=/path/to/dist python -m build backend"
)


def _editor_source(root: Path) -> Path | None:
    explicit = os.environ.get("OPENSTATEGRAPH_EDITOR_DIST", "").strip()
    candidate = Path(explicit) if explicit else root.parent / "dist"
    return candidate if (candidate / "index.html").is_file() else None


def _mermaid_source(root: Path) -> Path | None:
    """Optional, and only because it is optional at runtime too: without it
    `/chat` still works and its flow panel says so."""
    explicit = os.environ.get("OPENSTATEGRAPH_MERMAID_ASSET", "").strip()
    candidate = Path(explicit) if explicit else root.parent / MERMAID_SOURCE
    return candidate if candidate.is_file() else None


def editor_force_include(root: Path, version: str) -> dict[str, str]:
    """Source path → path inside the distribution, for every asset to ship."""
    if (root / EDITOR_DEST / "index.html").is_file():
        # Building from our own sdist: the assets are already package data.
        return {}

    source = _editor_source(root)
    if source is None:
        if version == "editable":
            return {}
        raise RuntimeError(NOT_BUILT)

    include = {
        str(path): f"{EDITOR_DEST}/{path.relative_to(source).as_posix()}"
        for path in sorted(source.rglob("*"))
        if path.is_file() and path.suffix not in EXCLUDED_SUFFIXES
    }

    mermaid = _mermaid_source(root)
    if mermaid is not None:
        include[str(mermaid)] = f"{VENDOR_DEST}/mermaid.min.js"
    return include


class EditorAssetsBuildHook(BuildHookInterface):  # type: ignore[misc,valid-type]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name not in ("wheel", "sdist"):
            return
        build_data.setdefault("force_include", {}).update(
            editor_force_include(Path(self.root), version)
        )
