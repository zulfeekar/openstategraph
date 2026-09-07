"""A fetch that deletes every URL is lying about what it read.

`workflow-gallery` 34, half 2. `web_fetch` stripped tags *with their
attributes*, so a page whose whole value is "these titles link there" came
back as titles and nothing else — measured, not supposed: the flagship
example fetched 8 013 characters of a YouTube ranking and could not recover a
single `watch?v=` id, which is why its third rung fell back onto a search
endpoint that was refusing every request.

The rule this is written to is `CLAUDE.md`'s *tolerant in reading, strict in
trusting*, and the strict half is the part that regresses. So the tests below
are half inverses: prose stays prose, a link farm does not drown the text, and
a `href` is only ever taken from an `<a>` tag that actually has one.
"""

from __future__ import annotations

from openstategraph.prebuilt_web import MAX_FETCH_LINKS, WebFetchTool

#: The shape the ticket describes: a ranking table whose titles are anchors,
#: the id living only in an attribute.
RANKING = """
<html><body><h1>Trending today</h1><table>
<tr><td>1</td><td><a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">Big Song</a></td>
    <td>Music</td><td>12,345,678</td></tr>
<tr><td>2</td><td><a href="/watch?v=aBcD_1234ef">Second Video</a></td>
    <td>Gaming</td><td>9,000,000</td></tr>
</table></body></html>
"""


def _fetch(page: str, url: str = "https://trends.example/youtube") -> str:
    result = WebFetchTool(fetcher=lambda _u: page).run(url=url)
    assert result.error is None, result.error
    return result.content


class TestTheLinkSurvives:
    def test_an_id_that_lives_only_in_an_attribute_reaches_the_model(self) -> None:
        assert "dQw4w9WgXcQ" in _fetch(RANKING)

    def test_the_link_stays_beside_the_text_it_belongs_to(self) -> None:
        """Appending an index at the end was rejected: the 8 000-character
        truncation cuts the tail first, so the index is the half that dies."""
        content = _fetch(RANKING)
        assert "Big Song (https://www.youtube.com/watch?v=dQw4w9WgXcQ)" in content

    def test_a_relative_href_is_resolved_against_the_page(self) -> None:
        assert "https://trends.example/watch?v=aBcD_1234ef" in _fetch(RANKING)

    def test_the_readable_text_is_still_all_there(self) -> None:
        content = _fetch(RANKING)
        for expected in ("Trending today", "Second Video", "Music", "12,345,678"):
            assert expected in content


class TestItStaysNarrow:
    def test_prose_with_no_links_is_untouched(self) -> None:
        page = "<p>Revenue grew to $4.2m (up 18%) — see the note at http://x.test.</p>"
        content = _fetch(page)
        assert content == "Revenue grew to $4.2m (up 18%) — see the note at http://x.test."

    def test_a_url_shaped_string_in_prose_is_not_made_into_a_link(self) -> None:
        content = _fetch("<p>Visit example.com/watch?v=NOTALINK for more.</p>")
        assert "(" not in content

    def test_an_anchor_with_no_href_is_just_its_text(self) -> None:
        assert _fetch('<p><a name="top">Top</a> of the page.</p>') == "Top of the page."

    def test_a_non_http_href_is_dropped(self) -> None:
        content = _fetch('<p><a href="javascript:steal()">Click</a></p>')
        assert content == "Click"
        content = _fetch('<p><a href="mailto:a@b.test">Mail us</a></p>')
        assert content == "Mail us"

    def test_a_link_farm_does_not_drown_the_text(self) -> None:
        farm = "".join(
            f'<a href="https://ads.test/t?utm_source=a&id={n}">ad {n}</a>'
            for n in range(400)
        )
        content = _fetch(f"<html><body>{farm}<p>The sentence that matters.</p></body></html>")
        assert "The sentence that matters." in content
        assert content.count("https://ads.test/") <= MAX_FETCH_LINKS

    def test_the_same_url_is_only_spelled_out_once(self) -> None:
        page = (
            '<a href="https://a.test/p">One</a> and '
            '<a href="https://a.test/p">One again</a>'
        )
        assert _fetch(page).count("https://a.test/p") == 1
