"""`osg-agent-experience/64` — one rule, three refusals, and one pass.

A domain's own vocabulary carries underscores. A YAML `resolvers:` map keyed
`north_yard` / `plant_outage_events` is a file the owner curates, and one
package per key therefore needs a transform, because a slug may not carry `_`.

**The rule is not relaxed, and this file is where that is recorded.** A slug is
the package's frozen identity: it is the directory name, the `?w=` value, the
prefix of every discovered tool's node type (`<slug>/tools.QueryTool`), and it
is published to third-party clients as `SLUG_PATTERN` in `docs/openapi.json`.
Admitting `_` would make `site_lens` and `site-lens` two addresses that
`slugify` collapses to one, which is a *second spelling* of an identity — the
exact defect the hyphen rule exists to prevent — in exchange for saving one
`.replace()` in a generator. The ticket says so itself: the refusal is
exemplary and was not asked to change.

What it cost is what this closes, and there were two costs:

1. **The correction was named at one refusal out of two.** `load_workflow`
   says *rename it to 'site-lens-north-yard'*; `openstategraph new site_lens`
   said only *must be lowercase letters, digits and hyphens*, at the exact
   moment a name is being chosen and the correction is cheapest. Both now come
   from one function, so a third site cannot invent a third sentence.
2. **Fifteen packages was fifteen runs.** `validate` reports one package;
   nothing reported a root. The pass that already reads every package —
   `review_workflows_root`, behind `openstategraph open` — listed
   `site_lens_north_yard` as a healthy three-node row, because
   `WorkflowStore.list` never asks whether a directory name is addressable. A
   package that cannot be loaded now says so in the one place every package is
   already looked at.

Never silently: nothing renames a directory. The correction is offered.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openstategraph.api.workflow_store import SLUG_PATTERN, is_slug, slug_refusal, slugify
from openstategraph.scaffold import ScaffoldError, new_package, review_lines, review_workflows_root


class TestTheRuleItselfIsUnchanged:
    def test_an_underscore_is_still_not_a_slug(self) -> None:
        assert not is_slug("site_lens")

    def test_the_published_pattern_still_refuses_it(self) -> None:
        assert SLUG_PATTERN.startswith("^[a-z0-9]")
        assert not __import__("re").fullmatch(SLUG_PATTERN, "site_lens")

    def test_the_correction_is_the_one_slugify_would_mint(self) -> None:
        assert slugify("site_lens_north_yard") == "site-lens-north-yard"


class TestOneSentenceForOneRule:
    def test_a_valid_slug_is_not_refused(self) -> None:
        assert slug_refusal("site-lens-north-yard") is None

    def test_the_refusal_names_the_name_the_correction_and_the_rule(self) -> None:
        message = slug_refusal("site_lens_north_yard")

        assert message is not None
        assert "site_lens_north_yard" in message
        assert "site-lens-north-yard" in message
        assert "lowercase letters, digits and hyphens" in message

    def test_the_loader_s_wording_is_preserved_verbatim(self) -> None:
        """`load_workflow`'s sentence was the exemplary one and is the one
        every door now says. Pinned so a later edit to the shared function
        cannot quietly downgrade it."""
        assert slug_refusal("site_lens", subject="workflow package directory") == (
            "workflow package directory 'site_lens' is not a valid slug; "
            "rename it to 'site-lens' (lowercase letters, digits and hyphens)"
        )

    @pytest.mark.parametrize("slug", ["site_lens", "SiteLens", "site lens", "site.lens"])
    def test_every_refusal_offers_something_addressable(self, slug: str) -> None:
        message = slug_refusal(slug)

        assert message is not None
        assert is_slug(slugify(slug))


class TestTheMintNamesTheCorrection:
    def test_new_package_refuses_an_underscore_with_the_correction(self, tmp_path: Path) -> None:
        with pytest.raises(ScaffoldError) as caught:
            new_package(tmp_path, "site_lens")

        assert "site-lens" in str(caught.value)

    def test_nothing_is_renamed_silently(self, tmp_path: Path) -> None:
        """The correction is offered, never applied — a directory minted under
        a name nobody typed is a second spelling arriving by surprise."""
        with pytest.raises(ScaffoldError):
            new_package(tmp_path, "site_lens")

        assert list(tmp_path.iterdir()) == []


class TestOnePassOverARoot:
    def _root(self, tmp_path: Path) -> Path:
        root = tmp_path / "workflows"
        root.mkdir()
        new_package(root, "site-lens-a")
        for bad in ("site_lens_north_yard", "site_lens_plant_outage"):
            import shutil

            shutil.copytree(root / "site-lens-a", root / bad)
        return root

    def test_the_review_reports_every_unaddressable_directory(self, tmp_path: Path) -> None:
        """The ticket's second done-when. Fifteen packages was fifteen
        `validate` runs to find fifteen instances of one mistake; the pass that
        already reads every package reports them all at once."""
        found = {row.slug: row for row in review_workflows_root(self._root(tmp_path))}

        assert found["site_lens_north_yard"].slug_error is not None
        assert found["site_lens_plant_outage"].slug_error is not None
        assert found["site-lens-a"].slug_error is None

    def test_the_lines_name_each_correction(self, tmp_path: Path) -> None:
        lines = "\n".join(review_lines(review_workflows_root(self._root(tmp_path))))

        assert "site-lens-north-yard" in lines
        assert "site-lens-plant-outage" in lines

    def test_a_healthy_package_still_reads_as_a_package(self, tmp_path: Path) -> None:
        lines = review_lines(review_workflows_root(self._root(tmp_path)))

        assert any("3 nodes" in line and "site-lens-a" in line for line in lines)

    def test_an_unaddressable_directory_is_not_called_a_parse_failure(
        self, tmp_path: Path
    ) -> None:
        """Its `workflow.json` parses perfectly. Reporting it as *will not
        parse* would send a reader to the document, which is the one thing not
        wrong with it."""
        lines = "\n".join(review_lines(review_workflows_root(self._root(tmp_path))))

        assert "site_lens_north_yard  will not parse" not in lines
