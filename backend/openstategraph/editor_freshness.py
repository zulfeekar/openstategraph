"""Is the editor this process serves older than the source it was built from?

**The gap this closes** (production-ready 60). `openstategraph serve` hosts the
API *and* the built editor from `dist/`, same origin — that is the product: one
`pip install`, one process, one port, no CORS. The Vite dev server on 5273 hosts
the editor from `src/` with hot reload and talks cross-origin to this process.
Both render an editor, and until now nothing distinguished them.

The trap is only on this side. Edit `src/`, open the served page, and you are
looking at whatever `npm run build` last produced — with **no signal at all**.
The natural conclusion is that your change did not work.

**The comparison already exists and is not duplicated here.**
`hatch_build.editor_is_stale` is the authority: mtimes rather than hashes,
narrowed to files the bundle can actually contain, with the asymmetry argued at
the definition (a false positive would ship the defect it exists to catch). A
second implementation would be duplicated *knowledge*, which is the one kind of
duplication this project forbids outright.

**And its absence is exactly the signal we need.** `hatch_build.py` is a build
hook: present in a checkout, absent beside a `site-packages` install. So
`ImportError` means "not a checkout", which is precisely when this question is
meaningless and must be silent — the requirement the ticket set, satisfied by
construction rather than by a path test somebody has to maintain.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Said in one place because two surfaces say it — the startup log and the
#: editor's own banner, through `/api/health`. Two spellings of one warning
#: agree on the day they are written and drift on the first reword.
STALE_EDITOR_WARNING = (
    "The editor served here was built before your last change to src/. "
    "Run `npm run build`, or use the dev server on port 5273, which is never stale."
)


def editor_is_stale(repo_root: Path | None = None) -> bool | None:
    """`True`, `False`, or `None` when the question does not apply.

    Three-valued deliberately. `False` claims *"this editor is current"*, and an
    installed wheel cannot claim that — it has no `src/` to compare against, and
    answering `False` there would be a promise nothing checked. `None` is the
    honest "not a checkout", and every caller must treat it as *say nothing*
    rather than as a falsy `False`.
    """
    root = repo_root if repo_root is not None else Path(__file__).resolve().parents[2]
    dist, src = root / "dist", root / "src"
    if not dist.is_dir() or not src.is_dir():
        return None
    try:
        # The build hook is the authority; importing it is how we avoid owning
        # a second copy of the rule. Absent in an installed wheel — see above.
        import sys

        backend = root / "backend"
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from hatch_build import editor_is_stale as compare
    except Exception:
        return None
    try:
        return bool(compare(dist, src, root))
    except Exception:
        # A comparison that cannot run must not take the server with it. The
        # editor is served either way; this is advice, not a gate.
        logger.debug("could not compare editor freshness", exc_info=True)
        return None


def warn_if_stale(repo_root: Path | None = None) -> str | None:
    """Log the warning once at startup, and return what was said (or `None`)."""
    if editor_is_stale(repo_root) is not True:
        return None
    logger.warning("%s", STALE_EDITOR_WARNING)
    return STALE_EDITOR_WARNING
