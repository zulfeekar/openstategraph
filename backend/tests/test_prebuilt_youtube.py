"""The YouTube transcript atom, offline.

Every byte of YouTube in this file is a **copy of something observed live** on
2026-08-14 (`.scratch/workflow-gallery/research/01-youtube.md`), because the
two defects this atom exists to avoid are both invisible to an imagined
double:

1. **The client ladder.** `IOS` answered `OK` with six caption tracks on the
   same video that `ANDROID_VR` refused with `LOGIN_REQUIRED` / "Sign in to
   confirm you're not a bot", seconds apart — per-request bot gating, not a
   per-video property. A single hardcoded client is a tool that works on
   Tuesday.
2. **The empty 200.** Every `baseUrl` harvested from the *web* client returns
   HTTP 200 and **zero bytes**, for ASR and manual tracks alike. A tool that
   reports that as an empty transcript has told the agent the video has
   nothing to say — which is the defect class this project keeps closing
   (ticket 26's "no results" for a blocked search). It must read as broken,
   because it is.

The suite therefore asserts the *distinguishability* of the failures as
directly as it asserts the happy path: `test_every_failure_says_something
_different` is the one that would fail if someone collapsed two of them into
a shared sentence.

**Nothing here touches the network.** The transport is injected; the live
proof is a one-off recorded in the ticket's resolution.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import pytest

from openstategraph.prebuilt_youtube import (
    PLAYER_URL,
    YouTubeTranscriptTool,
    _video_id,
)

#: The legacy shape, from `YH9VdFvHiO8` via `IOS` (1 547 bytes live).
#: Note `&amp;#39;` — this endpoint escapes twice, so a single unescape leaves
#: `&#39;` sitting in the model's context.
LEGACY_XML = (
    '<?xml version="1.0" encoding="utf-8" ?><transcript>'
    '<text start="3.7" dur="4.9">How can it be possible that you do not know me?</text>'
    '<text start="8.6" dur="2.0">I&amp;#39;m the one.</text>'
    "</transcript>"
)

#: The other shape, from `dQw4w9WgXcQ` via `ANDROID_VR` (4 123 bytes live).
#: `<p>` rather than `<text>`, `t`/`d` rather than `start`/`dur`, and inner
#: `<s>` segment elements a tag-blind parser would emit as markup.
TIMEDTEXT_XML = (
    '<timedtext format="3"><body>'
    '<p t="1360" d="1680">[♪♪♪]</p>'
    '<p t="3040" d="2000">We&#39;re no <s>strangers</s> to love</p>'
    "</body></timedtext>"
)

LEGACY_TEXT = "How can it be possible that you do not know me? I'm the one."
TIMEDTEXT_TEXT = "[♪♪♪] We're no strangers to love"

CAPTION_URL = "https://www.youtube.com/api/timedtext?v=dQw4w9WgXcQ&lang=en&signature=x"


def track(language: str = "en", *, asr: bool = False, url: str = CAPTION_URL) -> dict[str, Any]:
    return {
        "baseUrl": url,
        "languageCode": language,
        "name": {"simpleText": language},
        **({"kind": "asr"} if asr else {}),
    }


def player_ok(*tracks: dict[str, Any]) -> dict[str, Any]:
    return {
        "playabilityStatus": {"status": "OK"},
        "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": list(tracks)}},
    }


#: What `ANDROID_VR` actually said, verbatim.
BOT_CHECK = {
    "playabilityStatus": {
        "status": "LOGIN_REQUIRED",
        "reason": "Sign in to confirm you're not a bot",
    }
}

UNPLAYABLE = {"playabilityStatus": {"status": "UNPLAYABLE", "reason": "Video unavailable"}}

Transport = Callable[..., tuple[int, str]]


def fake(
    *,
    players: dict[str, dict[str, Any]] | None = None,
    caption: tuple[int, str] = (200, LEGACY_XML),
    clients: list[str] | None = None,
) -> Transport:
    """A transport over a table of `clientName -> player response`.

    An unfaked client answers `ERROR`, which is what the ladder must walk
    past; `clients` records the order it was walked in, so a test can assert
    the fallthrough happened rather than inferring it from the answer.
    """
    table = players or {}

    def transport(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
        if payload is None:
            return caption
        assert url == PLAYER_URL
        name = payload["context"]["client"]["clientName"]
        if clients is not None:
            clients.append(name)
        return 200, json.dumps(table.get(name, {"playabilityStatus": {"status": "ERROR"}}))

    return transport


def tool(**kwargs: Any) -> YouTubeTranscriptTool:
    return YouTubeTranscriptTool(transport=fake(players={"IOS": player_ok(track())}), **kwargs)


class TestTheHappyPath:
    @pytest.mark.parametrize(
        "xml,expected",
        [(LEGACY_XML, LEGACY_TEXT), (TIMEDTEXT_XML, TIMEDTEXT_TEXT)],
        ids=["legacy-transcript", "timedtext-format-3"],
    )
    def test_both_observed_xml_shapes_parse_to_the_same_plain_text(
        self, xml: str, expected: str
    ) -> None:
        """Both shapes came back within one minute of each other, live.

        A parser that handles only one silently yields an empty transcript —
        which is the empty-200 defect arriving by a different door.
        """
        transport = fake(players={"IOS": player_ok(track())}, caption=(200, xml))
        result = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ")
        assert result.error is None
        assert result.content == expected

    def test_a_watch_url_is_accepted_as_readily_as_an_id(self) -> None:
        result = tool().run(video="https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s")
        assert result.error is None
        assert result.content == LEGACY_TEXT

    @pytest.mark.parametrize(
        "video",
        [
            "dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "https://www.youtube.com/live/dQw4w9WgXcQ",
            "youtube.com/watch?v=dQw4w9WgXcQ",
        ],
    )
    def test_every_shape_a_user_pastes_normalises_to_the_id(self, video: str) -> None:
        assert _video_id(video) == "dQw4w9WgXcQ"

    def test_no_timestamps_reach_the_model(self) -> None:
        """The description promises plain text; `start`/`dur` are ours to drop."""
        content = tool().run(video="dQw4w9WgXcQ").content
        assert "start=" not in content and "3.7" not in content


class TestTheClientLadder:
    """`IOS` → `ANDROID_VR` → `WEB`, and it is the whole point of the atom."""

    def test_it_walks_past_a_bot_checked_client_to_one_that_answers(self) -> None:
        seen: list[str] = []
        transport = fake(
            players={"IOS": BOT_CHECK, "ANDROID_VR": player_ok(track())}, clients=seen
        )
        result = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ")
        assert result.error is None
        assert result.content == LEGACY_TEXT
        assert seen == ["IOS", "ANDROID_VR"]

    def test_it_stops_at_the_first_client_that_answers(self) -> None:
        seen: list[str] = []
        transport = fake(players={"IOS": player_ok(track())}, clients=seen)
        YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ")
        assert seen == ["IOS"]

    def test_a_client_that_answers_ok_with_no_tracks_is_not_the_end_of_the_ladder(self) -> None:
        """`OK` and *zero* captions is still a rung, not an answer.

        The observed gating is per request, so the next client is free to
        return six tracks for the video the last one had none for.
        """
        seen: list[str] = []
        transport = fake(
            players={"IOS": player_ok(), "ANDROID_VR": player_ok(track())}, clients=seen
        )
        assert YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ").error is None
        assert seen == ["IOS", "ANDROID_VR"]

    def test_a_client_that_raises_does_not_abort_the_ladder(self) -> None:
        def transport(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
            if payload is None:
                return 200, LEGACY_XML
            name = payload["context"]["client"]["clientName"]
            if name == "IOS":
                raise TimeoutError("timed out")
            return 200, json.dumps(player_ok(track()))

        assert YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ").error is None


class TestConfiguration:
    def test_the_requested_language_is_preferred_over_the_first_track(self) -> None:
        transport = fake(
            players={
                "IOS": player_ok(
                    track("en", url="https://www.youtube.com/api/timedtext?lang=en"),
                    track("fr", url="https://www.youtube.com/api/timedtext?lang=fr"),
                )
            },
            caption=(200, TIMEDTEXT_XML),
        )
        asked: list[str] = []

        def spy(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
            if payload is None:
                asked.append(url)
            return transport(url, payload)

        YouTubeTranscriptTool(language="fr", transport=spy).run(video="dQw4w9WgXcQ")
        assert asked == ["https://www.youtube.com/api/timedtext?lang=fr"]

    def test_a_regional_variant_satisfies_a_bare_language(self) -> None:
        """`es-419` is Spanish; a request for `es` should not fall through to
        whatever happens to be first."""
        asked: list[str] = []
        table = fake(
            players={
                "IOS": player_ok(
                    track("de-DE", url="https://x.test/de"),
                    track("es-419", url="https://x.test/es"),
                )
            }
        )

        def spy(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
            if payload is None:
                asked.append(url)
            return table(url, payload)

        YouTubeTranscriptTool(language="es", transport=spy).run(video="dQw4w9WgXcQ")
        assert asked == ["https://x.test/es"]

    def test_auto_captions_are_skipped_when_the_node_says_so(self) -> None:
        asked: list[str] = []
        table = fake(
            players={
                "IOS": player_ok(
                    track("en", asr=True, url="https://x.test/asr"),
                    track("en", url="https://x.test/manual"),
                )
            }
        )

        def spy(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
            if payload is None:
                asked.append(url)
            return table(url, payload)

        YouTubeTranscriptTool(allow_auto_captions=False, transport=spy).run(video="dQw4w9WgXcQ")
        assert asked == ["https://x.test/manual"]

    def test_max_chars_truncates_and_says_that_it_did(self) -> None:
        long = '<transcript><text start="0">' + ("word " * 4_000) + "</text></transcript>"
        transport = fake(players={"IOS": player_ok(track())}, caption=(200, long))
        result = YouTubeTranscriptTool(max_chars=1_000, transport=transport).run(
            video="dQw4w9WgXcQ"
        )
        assert result.error is None
        assert result.content.endswith(" …(truncated)")
        assert len(result.content) == 1_000 + len(" …(truncated)")

    def test_configure_reads_the_three_declared_keys(self) -> None:
        configured = tool().configure(
            {"language": "de", "allowAutoCaptions": False, "maxChars": 2_000}
        )
        assert isinstance(configured, YouTubeTranscriptTool)
        assert (configured.language, configured.allow_auto_captions, configured.max_chars) == (
            "de",
            False,
            2_000,
        )

    def test_configure_returns_a_fresh_instance(self) -> None:
        """Two nodes of this type in one document must not clobber each other."""
        base = tool()
        assert base.configure({"language": "de"}) is not base
        assert base.language == "en"

    def test_configure_keeps_the_defaults_it_was_given_nothing_about(self) -> None:
        assert tool(max_chars=3_000).configure({"language": "de"}).max_chars == 3_000

    def test_an_out_of_range_max_chars_is_clamped_not_obeyed(self) -> None:
        assert tool().configure({"maxChars": 10**9}).max_chars == 20_000
        assert tool().configure({"maxChars": 1}).max_chars == 1_000


class TestFailuresAreData:
    """Seven conditions, seven sentences. That is the atom's real value.

    An agent can act on the difference — retry a bot check, give up on a video
    with no captions, and never claim a transcript it did not read.
    """

    def test_invalid_arguments_come_back_as_data(self) -> None:
        result = YouTubeTranscriptTool().run(nonsense=1)
        assert not result.ok
        assert "Invalid arguments" in (result.error or "")

    def test_an_unparseable_video_names_what_it_could_not_read(self) -> None:
        result = tool().run(video="https://vimeo.com/12345")
        assert not result.ok
        assert "is not a YouTube video id or watch URL" in (result.error or "")

    def test_a_bot_check_is_never_reported_as_a_missing_transcript(self) -> None:
        """The ticket-26 lesson, transplanted: a refusal is not an answer."""
        transport = fake(players=dict.fromkeys(("IOS", "ANDROID_VR", "WEB"), BOT_CHECK))
        error = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ").error or ""
        assert "bot check" in error
        assert "no captions" not in error
        assert "no transcript" not in error.lower()

    def test_an_unplayable_video_names_its_status(self) -> None:
        transport = fake(players=dict.fromkeys(("IOS", "ANDROID_VR", "WEB"), UNPLAYABLE))
        error = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ").error or ""
        assert "unavailable" in error
        assert "UNPLAYABLE" in error

    def test_a_video_with_no_captions_says_exactly_that(self) -> None:
        transport = fake(players=dict.fromkeys(("IOS", "ANDROID_VR", "WEB"), player_ok()))
        error = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ").error or ""
        assert "no captions in any language" in error

    def test_asr_only_under_a_manual_only_node_says_which_wall_was_hit(self) -> None:
        transport = fake(players={"IOS": player_ok(track("en", asr=True))})
        error = (
            YouTubeTranscriptTool(allow_auto_captions=False, transport=transport)
            .run(video="dQw4w9WgXcQ")
            .error
            or ""
        )
        assert "only auto-generated" in error
        assert "'en'" in error

    def test_an_empty_200_on_the_caption_url_is_the_load_bearing_case(self) -> None:
        """HTTP 200, zero bytes — measured on every web-client `baseUrl`.

        The captions demonstrably exist: the player just listed them. What
        failed is the download, and an agent told "no transcript" would go on
        to summarise the title and present it as the video's content.
        """
        transport = fake(players={"IOS": player_ok(track())}, caption=(200, ""))
        result = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ")
        assert not result.ok
        error = result.error or ""
        assert "This is not an empty transcript" in error
        assert "no captions" not in error
        assert "no transcript" not in error.lower()

    def test_a_caption_url_that_answers_with_markup_we_cannot_read_is_also_not_silence(
        self,
    ) -> None:
        transport = fake(players={"IOS": player_ok(track())}, caption=(200, "<html>nope</html>"))
        error = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ").error or ""
        assert "This is not an empty transcript" in error

    def test_a_non_200_on_the_caption_url_names_the_status(self) -> None:
        transport = fake(players={"IOS": player_ok(track())}, caption=(429, ""))
        error = YouTubeTranscriptTool(transport=transport).run(video="dQw4w9WgXcQ").error or ""
        assert "429" in error
        assert "This is not an empty transcript" in error

    def test_a_transport_failure_is_reported_as_one(self) -> None:
        def boom(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
            raise ConnectionError("nope")

        error = YouTubeTranscriptTool(transport=boom).run(video="dQw4w9WgXcQ").error or ""
        assert "Transcript fetch failed" in error
        assert "nope" in error

    def test_every_failure_says_something_different(self) -> None:
        """The test that fails if two of them are ever collapsed into one."""
        every = fake(players=dict.fromkeys(("IOS", "ANDROID_VR", "WEB"), BOT_CHECK))

        def boom(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
            raise ConnectionError("nope")

        errors = [
            tool().run(video="https://vimeo.com/12345").error,
            YouTubeTranscriptTool(transport=every).run(video="dQw4w9WgXcQ").error,
            YouTubeTranscriptTool(
                transport=fake(players=dict.fromkeys(("IOS", "ANDROID_VR", "WEB"), UNPLAYABLE))
            )
            .run(video="dQw4w9WgXcQ")
            .error,
            YouTubeTranscriptTool(
                transport=fake(players=dict.fromkeys(("IOS", "ANDROID_VR", "WEB"), player_ok()))
            )
            .run(video="dQw4w9WgXcQ")
            .error,
            YouTubeTranscriptTool(
                allow_auto_captions=False,
                transport=fake(players={"IOS": player_ok(track("en", asr=True))}),
            )
            .run(video="dQw4w9WgXcQ")
            .error,
            YouTubeTranscriptTool(
                transport=fake(players={"IOS": player_ok(track())}, caption=(200, ""))
            )
            .run(video="dQw4w9WgXcQ")
            .error,
            YouTubeTranscriptTool(transport=boom).run(video="dQw4w9WgXcQ").error,
        ]
        assert all(errors)
        assert len(set(errors)) == 7


class TestTheSeam:
    def test_it_answers_to_the_node_type_the_card_declares(self) -> None:
        assert YouTubeTranscriptTool.node_type == "tool.youtube-transcript"
        assert YouTubeTranscriptTool.name == "youtube_transcript"

    def test_the_description_tells_the_model_not_to_invent_a_transcript(self) -> None:
        assert "do not invent" in YouTubeTranscriptTool.description.lower()

    def test_the_registry_binds_it(self) -> None:
        from openstategraph.api.registries import process_tool_layer

        builtin, _ = process_tool_layer()
        assert isinstance(builtin["tool.youtube-transcript"], YouTubeTranscriptTool)
