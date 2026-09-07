"""The landing page drew its own logo, and it was not the product's.

`site/` is uploaded whole by `pages.yml` and nothing outside it is, so the
lockup the README uses (`docs/assets/logo.svg`) cannot be referenced across the
directory boundary — it has to be copied in. A copy is a second place one fact
can live, which this repository's own rules say is the defect rather than the
fix, so the copy is pinned here: byte-identical, or a red test naming both
paths.

What was there before was not a stale copy. It was a **different drawing** —
three dots and two curves inside a rounded square, in the page's own theme
tokens, beside the word set in the page's body font. Nobody had drifted; the
page had simply never been given the mark. That is why this file asserts the
bytes rather than some visual property: a shape test would have passed on the
day the page showed somebody else's logo.

The reference is an `<img>` on purpose, and that is asserted too. The lockup
declares `--ink` on `:root` and flips it under `prefers-color-scheme` so the
ink follows the reader's theme while the accent does not. Inlined into the
page, that `:root` rule would set the variable on the *page*. An `<img>` has no
cascade, which is the isolation the drawing was written to rely on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "docs" / "assets" / "logo.svg"
PUBLISHED = REPO / "site" / "logo.svg"
PAGES = ("index.html", "gallery.html", "behind-the-scenes.html")


class TestTheCopyCannotDrift:
    def test_the_site_carries_the_lockup(self) -> None:
        assert PUBLISHED.is_file(), (
            f"{PUBLISHED} is missing. `pages.yml` uploads `site/` and nothing "
            "else, so the lockup has to be copied in beside the pages."
        )

    def test_it_is_byte_identical_to_the_one_the_readme_uses(self) -> None:
        assert PUBLISHED.read_bytes() == SOURCE.read_bytes(), (
            f"{PUBLISHED} and {SOURCE} have diverged. They are one mark. Copy "
            "the source over the published one rather than editing either in "
            "place, and if the mark itself changed, change it at the source."
        )


class TestEveryPageShowsIt:
    @pytest.mark.parametrize("name", PAGES)
    def test_the_brand_link_uses_the_lockup(self, name: str) -> None:
        text = (REPO / "site" / name).read_text(encoding="utf-8")
        assert 'src="logo.svg"' in text, (
            f"site/{name} does not reference the lockup. A page that draws its "
            "own mark is a second logo, which is how this test came to exist."
        )

    @pytest.mark.parametrize("name", PAGES)
    def test_the_lockup_is_not_inlined(self, name: str) -> None:
        text = (REPO / "site" / name).read_text(encoding="utf-8")
        # `--ink:` with the colon, because a *declaration* is what would leak.
        # The first version of this looked for the bare name and failed on the
        # comment beside the CSS rule that explains why the <img> is an <img>.
        assert "--ink:" not in text, (
            f"site/{name} appears to inline the lockup. It declares `--ink` on "
            "`:root`; inlined, that sets the variable on the page rather than "
            "on the drawing. Reference it with an <img>, which has no cascade."
        )
