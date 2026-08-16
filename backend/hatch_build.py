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
import re
from functools import lru_cache
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

#: The hand-written story pages — landing, gallery, and the five-artifact
#: walk-through — served by `api/routes/site.py`. Production-ready ticket 28:
#: their only route to a reader was GitHub Pages, which has never once
#: published them, so the wheel carries them and `serve` hands them out.
SITE_DEST = "openstategraph/api/static/site"

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


STALE = (
    "the built editor is stale — `dist/` is older than `src/`, so the wheel "
    "would ship an editor built before the code it is packaged with.\n"
    "Rebuild it:\n"
    "    npm run build\n"
    "or point the build at a current one:\n"
    "    OPENSTATEGRAPH_EDITOR_DIST=/path/to/dist python -m build backend"
)

#: Suffixes worth comparing. Everything the editor is actually built from;
#: a stray `.md` beside a component should not force a rebuild.
_SOURCE_SUFFIXES = (".ts", ".tsx", ".css", ".html")


#: What makes a glob a *test* glob rather than any other glob in those configs.
#:
#: The discriminator is the safety property, not a convenience. `vite.config.ts`
#: also carries `coverage.include` (`src/core/**`, `src/controller/**`) — real
#: bundle inputs, in the same file, one array away. Taking one of those for an
#: exclusion would hide the entire core from the staleness walk: a false
#: negative, which is the side `editor_is_stale` says is unacceptable to pay.
#: A glob naming `*.test.*`, `*.spec.*` or `*.stories.*` cannot be a bundle
#: input, whichever array it was found in.
_TEST_FILE_MARKERS = (".test.", ".spec.", ".stories.")


def bundle_excluded_globs(repo_root: Path) -> tuple[str, ...]:
    """The globs naming files `vite build` cannot put in the bundle.

    Read out of the vitest configs (`vite*.config.ts`) rather than kept here as
    a second list of suffixes. The JavaScript side already declares what a test
    file is — `include: ['src/**/*.test.ts']` and the generator's
    `['src/nodes/portSpecs.emit.spec.ts']` — and two lists of the same fact
    drift the first time either side adds a convention.

    Empty when there is no config to read, which excludes nothing: not knowing
    is a reason to compare more files, never fewer.
    """
    globs: list[str] = []
    for config in sorted(repo_root.glob("vite*.config.ts")):
        try:
            source = config.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover — unreadable config, compare everything
            continue
        for quoted in re.findall(r"""['"]([^'"\n]+)['"]""", source):
            leaf = quoted.rsplit("/", 1)[-1]
            if any(marker in leaf for marker in _TEST_FILE_MARKERS) and quoted not in globs:
                globs.append(quoted)
    return tuple(globs)


@lru_cache(maxsize=None)
def _glob_pattern(glob: str) -> re.Pattern[str]:
    escaped = re.escape(glob)
    body = escaped.replace(r"\*\*/", "(?:[^/]+/)*").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.compile(f"{body}$")


def _is_excluded(relative: str, globs: tuple[str, ...]) -> bool:
    return any(_glob_pattern(glob).match(relative) for glob in globs)


def editor_is_stale(dist: Path, src: Path, repo_root: Path | None = None) -> bool:
    """Whether `dist/` predates the sources it was supposed to be built from.

    Modification times, not hashes: the question is "did somebody edit the
    editor and forget to rebuild", and an mtime answers it in milliseconds
    without a content index. False negatives are possible (a touched file with
    no change) and cost one needless rebuild; a false *positive* would ship the
    defect this exists to catch, which is the asymmetry that decides the
    method.

    `False` when there is no source tree at all — a wheel built from our own
    sdist has package data and no `src/`, and refusing there would break every
    downstream repackager over a check that cannot apply.

    **Only files the bundle can contain are compared.** Test files are `.ts`,
    `vitest` collects them and Vite never bundles them, so touching one cannot
    change a byte of what the wheel ships — yet it used to demand
    `npm run build`, and did, at `HEAD`, over
    `src/nodes/guard/GuardrailNode.test.ts`. That is the harmless direction of
    the asymmetry above, and it is still the expensive one: a gate that is red
    for a reason nobody believes is a gate people clear with a reflex rebuild,
    and then it is checking nothing. `bundle_excluded_globs` narrows the input;
    the rule is unchanged.
    """
    index = dist / "index.html"
    if not index.is_file() or not src.is_dir():
        return False

    root = repo_root if repo_root is not None else src.parent
    excluded = bundle_excluded_globs(root)

    built = index.stat().st_mtime
    for path in src.rglob("*"):
        if path.suffix in _SOURCE_SUFFIXES and path.is_file():
            if path.stat().st_mtime <= built:
                continue
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:  # pragma: no cover — src outside the repo root
                return True
            if not _is_excluded(relative, excluded):
                return True
    return False


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

    # A missing editor already fails loudly; an *old* one used to ship in
    # silence. The wheel carried an editor three days behind the backend it was
    # packaged with — including a schema version, which the two sides must
    # agree on or the editor refuses documents the backend writes.
    if version != "editable" and editor_is_stale(source, root.parent / "src"):
        raise RuntimeError(STALE)

    include = {
        str(path): f"{EDITOR_DEST}/{path.relative_to(source).as_posix()}"
        for path in sorted(source.rglob("*"))
        if path.is_file() and path.suffix not in EXCLUDED_SUFFIXES
    }

    mermaid = _mermaid_source(root)
    if mermaid is not None:
        include[str(mermaid)] = f"{VENDOR_DEST}/mermaid.min.js"
    return include


def site_force_include(root: Path) -> dict[str, str]:
    """The `site/*.html` pages, source path → path inside the distribution.

    Its own function rather than a few more lines inside `editor_force_include`,
    because that one returns early in two cases that have nothing to do with
    these files — an sdist rebuild, and an editable install with no `dist/` —
    and folding the pages in there would make shipping them depend on whether
    somebody had run `npm run build`.

    Optional, like the mermaid asset and unlike the editor: absence is a 404
    with a sentence rather than a broken product, so it is not worth failing a
    build over. `test_site_pages.py` asserts *this* repository ships all three,
    which is the case that would otherwise regress in silence.
    """
    if (root / SITE_DEST / "gallery.html").is_file():
        # Building from our own sdist: already package data.
        return {}

    source = root.parent / "site"
    if not (source / "gallery.html").is_file():
        return {}

    return {
        str(path): f"{SITE_DEST}/{path.name}"
        for path in sorted(source.glob("*.html"))
    }


class EditorAssetsBuildHook(BuildHookInterface):  # type: ignore[misc,valid-type]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name not in ("wheel", "sdist"):
            return
        include = build_data.setdefault("force_include", {})
        include.update(editor_force_include(Path(self.root), version))
        include.update(site_force_include(Path(self.root)))
