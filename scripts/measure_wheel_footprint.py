#!/usr/bin/env python3
"""Measure what is actually inside our wheel — docs-and-gaps ticket 19.

    python3 scripts/measure_wheel_footprint.py --write

`docs/what-is-this.md` settles the package-split question — why the editor
rides in the main wheel rather than a separate `openstategraph-editor`
distribution — on measured figures. Until this script existed those figures
were measured **once, on one machine, on 2026-08-10**, and the paragraph said
so honestly in a parenthetical. It then drifted exactly as declared: the wheel
went from 2.9 MB to 4.4, the Python from 276 KiB to a megabyte, and the
argument's ratio inverted — the editor had been 93% of the download and is now
under two thirds.

An honest hedge is not a fix. So the numbers come from here now: this script
reads a built wheel, writes `docs/wheel-footprint.json`, and renders the block
the documentation carries between its `wheel-footprint` markers.
`backend/tests/test_the_wheel_argument_is_regenerable.py` fails when the
documentation and that file disagree, and when the file stops describing the
version in `backend/pyproject.toml`.

**Build the wheel first**, from a checkout with the editor built, because a
wheel without the canvas measures the thing the argument is not about:

    npm run build && python3 -m build backend --wheel

Groups are the four questions a reader has — how much is the browser payload,
how much of that is one vendored library, how much is our own Python, how much
is the gallery we ship. `--json` prints and writes nothing else.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DIST = REPO / "backend" / "dist"
FOOTPRINT = REPO / "docs" / "wheel-footprint.json"

#: `(key, label, predicate)`. Order is the order the rendered table reads in,
#: and every file in the wheel lands in exactly one group — the totals are a
#: partition, not a sample, so a new kind of package data cannot hide.
GROUPS: tuple[tuple[str, str, Any], ...] = (
    ("editor", "the built canvas", lambda n: n.startswith("openstategraph/api/static/editor/")),
    ("mermaid", "vendored Mermaid, for /chat's flow view", lambda n: n.startswith("openstategraph/api/static/vendor/")),
    ("static_other", "the served HTML shells", lambda n: n.startswith("openstategraph/api/static/")),
    ("python", "our own Python", lambda n: n.endswith(".py")),
    ("examples", "the shipped gallery", lambda n: n.startswith("openstategraph/examples/")),
    ("metadata", "wheel metadata", lambda n: ".dist-info/" in n),
)
OTHER = ("other", "the rest of the package data")


def measure(wheel: Path) -> dict[str, Any]:
    sizes: dict[str, int] = {key: 0 for key, _, _ in GROUPS}
    counts: dict[str, int] = {key: 0 for key, _, _ in GROUPS}
    sizes[OTHER[0]] = counts[OTHER[0]] = 0

    with zipfile.ZipFile(wheel) as archive:
        for entry in archive.infolist():
            for key, _, matches in GROUPS:
                if matches(entry.filename):
                    break
            else:
                key = OTHER[0]
            sizes[key] += entry.compress_size
            counts[key] += 1

    total = wheel.stat().st_size
    browser = sizes["editor"] + sizes["mermaid"] + sizes["static_other"]
    return {
        "wheel": wheel.name,
        "version": wheel.name.split("-")[1],
        "measured": date.today().isoformat(),
        "total_bytes": total,
        "browser_bytes": browser,
        "browser_share_percent": round(100 * browser / total),
        "groups": {
            key: {"label": label, "files": counts[key], "bytes": sizes[key]}
            for key, label, _ in (*GROUPS, (OTHER[0], OTHER[1], None))
        },
    }


def kib(byte_count: int) -> str:
    return f"{byte_count / 1024:,.0f} KiB"


def render(data: dict[str, Any]) -> str:
    """The block the documentation carries. Plain text, no prose."""
    lines = [
        f"{data['wheel']}  —  {data['total_bytes'] / 1_000_000:.2f} MB, measured {data['measured']}",
        "",
    ]
    for key, entry in data["groups"].items():
        if not entry["files"]:
            continue
        lines.append(
            f"  {kib(entry['bytes']):>12}  {entry['files']:>4} files   "
            f"{entry['label']}"
        )
    lines += [
        "",
        f"  the browser payload is {data['browser_share_percent']}% of the download",
        "",
        "  regenerate: npm run build && python3 -m build backend --wheel",
        "              && python3 scripts/measure_wheel_footprint.py --write",
    ]
    return "\n".join(lines)


def newest_wheel() -> Path:
    wheels = sorted(DIST.glob("openstategraph-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise SystemExit(
            f"no wheel in {DIST}. Build one first:\n"
            "  npm run build && python3 -m build backend --wheel"
        )
    return wheels[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", nargs="?", type=Path, help="defaults to the newest in backend/dist/")
    parser.add_argument("--write", action="store_true", help=f"update {FOOTPRINT.name}")
    parser.add_argument("--json", action="store_true", help="print the measurement, not the block")
    args = parser.parse_args()

    data = measure(args.wheel or newest_wheel())
    print(json.dumps(data, indent=2) if args.json else render(data))

    if args.write:
        FOOTPRINT.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    main()
