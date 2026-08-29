"""`docs/what-is-this.md` settles the package split on measured figures.

Until docs-and-gaps/19 it settled it on **three numbers in a sentence**,
hedged — exemplarily — as *measured once on one machine, 2026-08-10; nothing
in the repository regenerates it*. That hedge was the most honest thing on the
page and it did not help: the wheel went 2.9 MB → 4.45, our Python 276 KiB →
1,037, and the browser's share of the download fell from 93% to 62%. The
argument is a ratio, and the ratio inverted while every word around it stayed
defensible.

This map's `17` is about numbers stated as if they could fail. This one
**declared** that it could not be checked, and then drifted exactly as
declared — which is why the fix was not a better hedge. The figures come out of
`scripts/measure_wheel_footprint.py` now, land in `docs/wheel-footprint.json`,
and are rendered into the page between its `wheel-footprint` markers.

What this module holds:

1. The committed measurement describes the version this repository ships. A
   footprint for a wheel three release candidates ago is the old defect with a
   filename.
2. The page carries exactly what the renderer renders from that file — so an
   edit to the block, or a re-measure that never reached the page, goes red.
3. The partition is a partition. Every byte of the wheel is in exactly one
   group, so the shares can be read as shares.
4. `README.md`'s shorter version of the same claim agrees with it.

It deliberately does **not** build a wheel. Building needs Node and ~30 s, and
a gate that expensive gets skipped; the check that matters is whether the
committed measurement and the prose have come apart.
"""

from __future__ import annotations

import importlib.util
import json
import re
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
FOOTPRINT = REPO / "docs" / "wheel-footprint.json"
PAGE = REPO / "docs" / "what-is-this.md"
README = REPO / "README.md"
INSTRUMENT = REPO / "scripts" / "measure_wheel_footprint.py"

BLOCK = re.compile(
    r"<!-- wheel-footprint:begin.*?-->\n```\n(.*?)```\n<!-- wheel-footprint:end -->",
    re.DOTALL,
)


def measurement() -> dict[str, Any]:
    return json.loads(FOOTPRINT.read_text())


def renderer():
    spec = importlib.util.spec_from_file_location("measure_wheel_footprint", INSTRUMENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheMeasurementDescribesThisRepository:
    def test_it_is_the_shipped_version(self) -> None:
        shipped = tomllib.loads((REPO / "backend" / "pyproject.toml").read_text())
        assert measurement()["version"] == shipped["project"]["version"], (
            "the committed wheel footprint measures a version this repository "
            "no longer ships. Rebuild and re-measure:\n"
            "  npm run build && python3 -m build backend --wheel\n"
            "  && python3 scripts/measure_wheel_footprint.py --write"
        )

    def test_the_groups_partition_the_wheel(self) -> None:
        """A share is only a share if nothing fell outside the buckets.

        Compression means the parts do not sum to the file exactly — a zip's
        central directory is not in any entry — so this asserts the accounted
        bytes reach the whole wheel bar a small constant, which is what a
        missing group of any consequence would break.
        """
        data = measurement()
        accounted = sum(group["bytes"] for group in data["groups"].values())
        assert accounted <= data["total_bytes"]
        assert data["total_bytes"] - accounted < 100_000, (
            f"{data['total_bytes'] - accounted} bytes of the wheel are in no "
            "group, so the percentages below are not shares of anything"
        )

    def test_the_browser_share_is_the_three_asset_groups(self) -> None:
        data = measurement()
        groups = data["groups"]
        browser = groups["editor"]["bytes"] + groups["mermaid"]["bytes"] + groups["static_other"]["bytes"]
        assert browser == data["browser_bytes"]
        assert data["browser_share_percent"] == round(100 * browser / data["total_bytes"])


class TestThePageCarriesWhatWasMeasured:
    def test_the_block_is_present(self) -> None:
        assert BLOCK.search(PAGE.read_text()), (
            "the generated wheel-footprint block has left docs/what-is-this.md, "
            "which puts the package-split argument back on unregenerable prose"
        )

    def test_the_block_matches_the_measurement(self) -> None:
        found = BLOCK.search(PAGE.read_text())
        assert found
        assert found.group(1).rstrip("\n") == renderer().render(measurement()), (
            "docs/what-is-this.md and docs/wheel-footprint.json disagree. "
            "Re-render:\n"
            "  python3 scripts/measure_wheel_footprint.py --write"
        )

    def test_the_page_names_the_reason_the_ratio_does_not_decide_it(self) -> None:
        """The figures moved; the conclusion did not, and the page must say why.

        A reader who watches the browser's share fall from 93% to 62% is owed
        the sentence that makes the change irrelevant — pip extras add
        dependencies and cannot *remove* package data — or they are being asked
        to accept a conclusion whose stated grounds have shifted under it.
        """
        text = PAGE.read_text()
        assert "cannot remove package data" in text
        assert "two distributions" in text


class TestTheShortVersionAgrees:
    def test_the_readme_quotes_the_same_figures(self) -> None:
        """The stale figures were repeated out of the page once already."""
        data = measurement()
        editor = data["groups"]["editor"]
        text = README.read_text().replace("\n", " ")
        for fragment in (
            f"{editor['files']} files",
            f"{data['total_bytes'] / 1_000_000:.2f} MB wheel",
            f"{data['browser_share_percent']}% of the download",
        ):
            assert fragment in text, (
                f"README.md no longer agrees with docs/wheel-footprint.json: "
                f"expected {fragment!r}"
            )
