"""The YouTube transcript atom — a POST, a ladder, and two XML shapes.

`web_fetch` cannot do this, and the reason is structural rather than a
missing feature. Probed live on 2026-08-14 (the full record is
`.scratch/workflow-gallery/research/01-youtube.md`):

- A watch page still carries `captionTracks` in plain HTML, but **every
  `baseUrl` harvested from the web client answers HTTP 200 with zero bytes** —
  ASR and manually authored, VOD and livestream, with or without `&fmt=`.
- The only route that returns caption text is a **POST** to InnerTube's
  `/youtubei/v1/player` with a non-web client identity, followed by a GET of
  the `baseUrl` *that* response issues. A POST with a JSON body is not
  expressible as a `url` argument, which is why this is an atom and not a
  prompt.

Three facts from those probes shape everything below, and each of them is a
silent wrong answer if ignored:

1. **The client is not stable, so it is a ladder.** On one video, seconds
   apart: `ANDROID_VR` → `LOGIN_REQUIRED` / "Sign in to confirm you're not a
   bot", `IOS` → `OK` with six tracks, `MWEB` → `UNPLAYABLE`. The gating is
   per request, not per video. `IOS` → `ANDROID_VR` → `WEB`.
2. **Two XML shapes exist** — `<transcript><text start dur>` and
   `<timedtext format="3"><body><p t d>` — returned within a minute of each
   other. A parser that knows one yields an empty transcript for the other.
3. **`fmt` is ignored.** `json3`, `srv3` and `vtt` all returned byte-identical
   XML. Nothing here depends on it.

**The failure that decides the design.** Every condition below gets its own
sentence, because the agent's next move differs: retry a bot check, abandon a
video with no captions, and *never* summarise a video whose captions were
listed and then withheld. That last one — HTTP 200, zero bytes — is the
observed silent failure, and reporting it as "no transcript" is how an agent
ends up describing a video from its title with complete confidence. It is the
same defect ticket 26 closed for `web_search`, arriving through a different
door.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.prebuilt_web import _request
from openstategraph.progress import report_progress

#: InnerTube's player endpoint. The POST `web_fetch` cannot make.
PLAYER_URL = "https://www.youtube.com/youtubei/v1/player"

#: `(clientName, clientVersion)`, in the order they are tried. Each rung was
#: seen answering `OK` with tracks for some video and refusing another; the
#: order puts the two that answered most often first, and keeps `WEB` last
#: because its issued `baseUrl` is the one measured returning zero bytes.
CLIENT_LADDER: tuple[tuple[str, str], ...] = (
    ("IOS", "20.10.4"),
    ("ANDROID_VR", "1.61.48"),
    ("WEB", "2.20240304.00.00"),
)

#: Mirrors `prebuilt_web.MAX_FETCH_CHARS`: a transcript is a briefing, not an
#: archive, and the slider on the card moves this between 1 000 and 20 000.
MAX_TRANSCRIPT_CHARS = 8_000
MIN_TRANSCRIPT_CHARS = 1_000
MAX_TRANSCRIPT_CHARS_CEILING = 20_000

#: A video id is exactly eleven of these.
_ID = re.compile(r"[A-Za-z0-9_-]{11}")

#: The hosts a watch URL can be spelled with. Anything else is not ours to
#: guess at — a Vimeo URL comes back as a readable refusal, not a 404.
_HOSTS = frozenset(
    {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "youtu.be"}
)

#: `/shorts/<id>`, `/embed/<id>`, `/live/<id>`, `/v/<id>` — every path form
#: that carries the id as a segment rather than as `?v=`.
_SEGMENT_PATHS = ("/shorts/", "/embed/", "/live/", "/v/")

#: Both observed cue elements in one expression, because they are one concept
#: (a caption line) with two spellings. `<p>` cues may wrap words in `<s>`
#: segment elements, so the inner markup is stripped afterwards rather than
#: assumed away.
_CUE = re.compile(r"<(text|p)\b[^>]*>(.*?)</\1>", re.S)
_TAG = re.compile(r"<[^>]+>")


def _transport(url: str, payload: dict[str, Any] | None = None) -> tuple[int, str]:
    """`(status, body)` for one call: a GET, or a JSON POST when given a payload.

    One function rather than two so the tool has a single injection seam, and
    `prebuilt_web._request` underneath so the SSRF guard, the redirect
    re-validation, the certifi context and the 15-second timeout are the ones
    already written and tested — not a second copy that drifts.

    An HTTP error is returned as a status rather than raised, because this
    tool's entire thesis is that a refusal and an absence are different
    answers, and an exception erases the difference.
    """
    import urllib.error

    try:
        if payload is None:
            return _request(url)
        return _request(
            url, data=json.dumps(payload).encode(), content_type="application/json"
        )
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(600_000).decode("utf-8", errors="replace")


def _video_id(video: str) -> str:
    """An 11-character id, or `""` for anything this cannot read as one."""
    raw = video.strip()
    if _ID.fullmatch(raw):
        return raw
    parsed = urllib.parse.urlparse(raw if "//" in raw else f"https://{raw}")
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _HOSTS:
        return ""
    if host == "youtu.be":
        found = parsed.path.lstrip("/").split("/")[0]
    elif parsed.path in ("/watch", "/watch/"):
        found = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
    else:
        found = ""
        for prefix in _SEGMENT_PATHS:
            if parsed.path.startswith(prefix):
                found = parsed.path[len(prefix) :].split("/")[0]
                break
    return found if _ID.fullmatch(found) else ""


def _plain_text(xml: str) -> str:
    """Both cue shapes, unescaped, joined — or `""` if neither is present.

    `html.unescape` runs **twice** on purpose: this endpoint escapes its
    payload twice (`I&amp;#39;m` was measured on the legacy shape), so one
    pass leaves `&#39;` sitting in the model's context.
    """
    cues = [_TAG.sub("", match.group(2)) for match in _CUE.finditer(xml)]
    lines = [line for line in (html.unescape(html.unescape(cue)).strip() for cue in cues) if line]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


@dataclass
class _Resolution:
    """What the ladder learned, so the failure can name the real reason.

    A resolution carries every rung's outcome rather than only the last,
    because "all three were bot-checked" and "one answered and had no
    captions" are different findings and the agent acts on them differently.
    """

    client: str = ""
    tracks: list[dict[str, Any]] = field(default_factory=list)
    #: The `reason` text of a `LOGIN_REQUIRED`-style refusal.
    bot_check: str = ""
    #: The `playabilityStatus.status` of an `ERROR`/`UNPLAYABLE` rung.
    unavailable: str = ""
    #: A rung that answered `OK` and listed nothing. Authoritative, unlike a
    #: refusal — the player told us, rather than declining to.
    no_captions: bool = False
    transport_error: str = ""


class TranscriptArgs(BaseModel):
    model_config = {"extra": "forbid"}
    video: str = Field(description="A YouTube video id or a watch URL.")


class YouTubeTranscriptTool(BaseTool):
    """Read one YouTube video's captions as plain text."""

    name = "youtube_transcript"
    #: Reads only — `launch-readiness` 121. Running it twice changes nothing.
    side_effecting = False
    node_type = "tool.youtube-transcript"
    description = (
        "Fetch the spoken-word transcript of a YouTube video. Takes a video id or a "
        "watch URL. Returns plain text with no timestamps. Use after finding a video "
        "with web_search. Returns a clear failure if the video has no captions — do "
        "not invent one."
    )
    Args = TranscriptArgs

    def __init__(
        self,
        *,
        language: str = "en",
        allow_auto_captions: bool = True,
        max_chars: int = MAX_TRANSCRIPT_CHARS,
        transport: Callable[..., tuple[int, str]] | None = None,
    ) -> None:
        self.language = language or "en"
        self.allow_auto_captions = allow_auto_captions
        self.max_chars = max(MIN_TRANSCRIPT_CHARS, min(MAX_TRANSCRIPT_CHARS_CEILING, max_chars))
        #: Injectable for offline tests: `(url, payload) -> (status, body)`.
        #: The status is half the point — see `_transport`.
        self._transport = transport or _transport

    def configure(self, data: dict[str, Any]) -> "YouTubeTranscriptTool":
        """The card's three fields, delivered to a fresh instance.

        Fresh always, never a mutation: two transcript nodes in one document
        with different languages must not clobber each other's config through
        the registry's shared instance. The keys are string literals at the
        point of use — the data-key contract's convention.
        """
        language = str(data.get("language") or "").strip() or self.language
        auto = data.get("allowAutoCaptions")
        limit = data.get("maxChars")
        return type(self)(
            language=language,
            allow_auto_captions=bool(auto) if isinstance(auto, bool) else self.allow_auto_captions,
            max_chars=int(limit) if isinstance(limit, (int, float)) else self.max_chars,
            transport=self._transport,
        )

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, TranscriptArgs)
        video_id = _video_id(args.video)
        if not video_id:
            return ToolResult.failure(
                f"'{args.video.strip()}' is not a YouTube video id or watch URL."
            )

        # After the id is understood and before the client ladder walks: the
        # ladder is several fetches, and the caption fetch after it is one
        # more. Nothing is reported for an argument that is not a video,
        # because that answer comes back without touching the network.
        report_progress(f"Reading captions for {video_id}")

        resolution = self.resolve(video_id)
        if not resolution.tracks:
            return ToolResult.failure(self._explain(resolution))

        track = self._pick(resolution.tracks)
        if track is None:
            return ToolResult.failure(
                f"No manually authored '{self.language}' captions; only auto-generated "
                "ones exist. Turn on auto captions for this node to read them."
            )

        try:
            status, body = self._transport(str(track.get("baseUrl") or ""))
        except Exception as exc:
            return ToolResult.failure(f"Transcript fetch failed: {exc}")

        text = _plain_text(body) if status == 200 else ""
        if not text:
            return ToolResult.failure(self._withheld(status, body))
        suffix = " …(truncated)" if len(text) > self.max_chars else ""
        return ToolResult(content=text[: self.max_chars] + suffix)

    # -- the ladder --------------------------------------------------------

    def resolve(self, video_id: str) -> _Resolution:
        """Walk the client ladder until one client answers with caption tracks.

        Public because the live smoke needs to record *which* client answered,
        and inferring that from the transcript is guesswork. A rung that
        raises, refuses, or answers `OK` with nothing is a rung, not the end:
        the gating is per request, so the next client is free to succeed on a
        video the last one had nothing for.
        """
        found = _Resolution()
        for name, version in CLIENT_LADDER:
            try:
                status, body = self._transport(PLAYER_URL, self._payload(video_id, name, version))
            except Exception as exc:
                found.transport_error = f"{type(exc).__name__}: {exc}"
                continue
            if status != 200:
                found.transport_error = f"the player endpoint answered HTTP {status}"
                continue
            try:
                player = json.loads(body)
            except ValueError:
                found.transport_error = "the player endpoint did not answer with JSON"
                continue

            playability = player.get("playabilityStatus") or {}
            state = str(playability.get("status") or "")
            reason = str(playability.get("reason") or "")
            if state != "OK":
                if state == "LOGIN_REQUIRED" or "bot" in reason.lower():
                    found.bot_check = reason or state
                else:
                    found.unavailable = state or "no status"
                continue

            tracks = (
                ((player.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {}).get(
                    "captionTracks"
                )
                or []
            )
            if not tracks:
                found.no_captions = True
                continue
            found.client = name
            found.tracks = list(tracks)
            return found
        return found

    @staticmethod
    def _payload(video_id: str, client: str, version: str) -> dict[str, Any]:
        """The smallest body the endpoint was observed accepting.

        No API key: the endpoint answered a keyless POST for all three clients.
        `contentCheckOk`/`racyCheckOk` are what keep an age-gated video from
        coming back as `CONTENT_CHECK_REQUIRED`, which is a refusal we would
        otherwise have to spell as a failure the caller can do nothing about.
        """
        return {
            "context": {"client": {"clientName": client, "clientVersion": version, "hl": "en"}},
            "videoId": video_id,
            "contentCheckOk": True,
            "racyCheckOk": True,
        }

    # -- choosing and explaining -------------------------------------------

    def _pick(self, tracks: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Exact language, else the same language family, else the first.

        `None` means the node forbids auto captions and nothing else was on
        offer — the one case where a track exists and is still not usable.
        """
        usable = [
            track
            for track in tracks
            if self.allow_auto_captions or str(track.get("kind") or "") != "asr"
        ]
        if not usable:
            return None
        wanted = self.language.lower()
        family = wanted.split("-")[0]
        for match in (
            lambda code: code == wanted,
            lambda code: code.split("-")[0] == family,
        ):
            for track in usable:
                if match(str(track.get("languageCode") or "").lower()):
                    return track
        return usable[0]

    @staticmethod
    def _explain(resolution: _Resolution) -> str:
        """Why the ladder came back empty — in the caller's terms, not ours.

        Order is deliberate. An `OK` rung that listed nothing is the only
        *authoritative* finding here: the player answered and told us. A
        refusal is evidence about us, not about the video, so it never gets to
        speak as if it were.
        """
        if resolution.no_captions:
            return "That video has no captions in any language."
        if resolution.bot_check:
            return (
                f"YouTube declined the request on every client (bot check: "
                f"{resolution.bot_check!r}). The captions may well exist — this is a "
                "refusal, not an absence. Retry, or tell the user the captions could "
                "not be fetched."
            )
        if resolution.unavailable:
            return f"That video is unavailable ({resolution.unavailable})."
        if resolution.transport_error:
            return f"Transcript fetch failed: {resolution.transport_error}"
        return "Transcript fetch failed: the player endpoint answered nothing usable."

    @staticmethod
    def _withheld(status: int, body: str) -> str:
        """The load-bearing sentence: captions were listed, then not delivered.

        HTTP 200 with zero bytes is what every web-client `baseUrl` returned in
        the probes, and it is indistinguishable from success to anything that
        only checks for an exception. The wording is chosen so that an agent
        cannot read it as "the video has no transcript": it says what happened
        and what is still unknown.
        """
        detail = (
            f"HTTP {status}, {len(body)} bytes"
            if body.strip()
            else f"HTTP {status}, empty response"
        )
        return (
            f"YouTube listed the captions and then would not hand them over ({detail}). "
            "This is not an empty transcript and it is not a video without captions: the "
            "download failed. Retry, or tell the user the transcript could not be read."
        )


YOUTUBE_TOOLS = [YouTubeTranscriptTool()]
