"""The README named a builder the wheel does not carry (launch-readiness/19).

Found by the `launch-readiness/12` stranger run: a `pip install` user reads
the README naming `concierge` and `workflow-architect` as the
build-me-a-workflow flow, searches the editor for a "describe what you want"
surface, and finds none — because both workflows live in this checkout's
`workflows/`, entirely outside `backend/`, so no packaging rule could ever
ship them even if one tried.

Two things are pinned so a future edit cannot silently reopen the gap:

1. The structural claim — `concierge` and `workflow-architect` are outside
   the packaged distribution — so if either is ever moved *into* `backend/`
   this test fails and says so, rather than the README quietly going stale
   the other direction (claiming "checkout-only" for something the wheel now
   ships).
2. The README, at the paragraph naming both workflows, actually says they are
   checkout-only and actually points a wheel reader at the working
   alternative (`docs/mcp.md` §2).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class TestConciergeAndArchitectAreStructurallyCheckoutOnly:
    def test_they_live_outside_the_packaged_backend(self) -> None:
        assert (REPO / "workflows" / "concierge").is_dir()
        assert (REPO / "workflows" / "workflow-architect").is_dir()

        # The packaged distribution is backend/openstategraph/**. Neither
        # infrastructure workflow has ever lived there — they live at the
        # repo-root workflows/, which `hatch_build.py` never touches. This is
        # not a naming convention that could rot; it fails the day either
        # directory is moved under backend/, which is exactly the day the
        # README's "checkout-only" claim would go stale.
        assert not (REPO / "backend" / "openstategraph" / "workflows" / "concierge").exists()
        assert not (
            REPO / "backend" / "openstategraph" / "workflows" / "workflow-architect"
        ).exists()
        assert not (REPO / "backend" / "workflows").exists()


class TestTheReadmeSaysSoWhereItNamesThem:
    def test_the_paragraph_naming_both_workflows_calls_out_checkout_only(self) -> None:
        readme = (REPO / "README.md").read_text()
        idx = readme.index(
            "Two hidden infrastructure workflows (`concierge`, `workflow-architect`)"
        )
        paragraph = readme[idx : idx + 700]

        assert "checkout" in paragraph
        assert "wheel" in paragraph
        assert "docs/mcp.md" in paragraph, (
            "a wheel reader needs the working alternative named right where "
            "the checkout-only workflows are, not left to find it themselves"
        )
