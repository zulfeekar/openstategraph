"""The committed reverse-proxy examples are checked against the real app.

A proxy config in a README is a config that stops matching the routes it
proxies, and the way you find out is a customer whose approval expired at 60
seconds. `deploy/Caddyfile` and `deploy/nginx.conf` are the **supported**
deployment path for anything reachable from more than one machine, so they are
treated as code:

- every Server-Sent Event endpoint the app actually serves must be named in the
  streaming block of both files (this is the drift a fourth SSE endpoint would
  otherwise introduce silently);
- the directives that make SSE work through a proxy must still be there,
  because each of them is a real failure that testing without a proxy cannot
  reproduce;
- neither file may leave the app both unauthenticated and reachable.

What is deliberately NOT tested here: that Caddy and nginx parse these files.
That needs both binaries in CI to prove something their own parsers already
prove. What is ours is the correspondence between these files and our routes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CADDYFILE = REPO / "deploy" / "Caddyfile"
NGINX = REPO / "deploy" / "nginx.conf"

#: The endpoints that return `text/event-stream`. Derived from the app below,
#: not trusted as a literal — this list is the thing most likely to grow.
EXPECTED_SSE = {"/api/events", "/api/runs/stream", "/api/runs/resume"}


def sse_paths_of_the_app() -> set[str]:
    """Every route whose handler frames Server-Sent Events.

    Read out of the source rather than by calling each endpoint: two of the
    three need a real workflow and a model to reach their response, and the
    question here is only *which paths stream*.
    """
    import ast

    main = REPO / "backend" / "openstategraph" / "api" / "main.py"
    tree = ast.parse(main.read_text())
    streaming: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        source = ast.get_source_segment(main.read_text(), node) or ""
        if "text/event-stream" not in source:
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and decorator.args:
                first = decorator.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    streaming.add(first.value)
    return streaming


def _streaming_block_matches(config: Path, path: str) -> bool:
    """Whether `config` routes `path` through its no-buffering block.

    Caddy: a `@sse path a b c` matcher, matched literally. nginx: a
    `location ~ <regex>`, compiled and matched — the only way to tell a live
    pattern from one that has quietly stopped covering a route.
    """
    import re

    text = config.read_text()
    caddy = re.search(r"^\s*@sse\s+path\s+(.+)$", text, re.MULTILINE)
    if caddy is not None:
        return path in caddy.group(1).split()
    nginx = re.search(r"^\s*location\s+~\s+(\S+)\s*\{", text, re.MULTILINE)
    assert nginx is not None, f"{config.name} has no streaming block at all"
    return re.search(nginx.group(1), path) is not None


class TestTheStreamListIsCurrent:
    def test_the_app_streams_exactly_what_we_think(self) -> None:
        """If this fails, an SSE endpoint was added or moved — add it to both
        proxy files and to `EXPECTED_SSE`, in that order."""
        assert sse_paths_of_the_app() == EXPECTED_SSE


@pytest.mark.parametrize("config", [CADDYFILE, NGINX], ids=["caddy", "nginx"])
class TestBothProxiesCoverTheStreams:
    def test_the_file_is_committed(self, config: Path) -> None:
        assert config.exists(), f"{config} is the supported deployment path"

    @pytest.mark.parametrize("path", sorted(EXPECTED_SSE))
    def test_each_stream_is_routed_to_the_streaming_block(
        self, config: Path, path: str
    ) -> None:
        """Caddy names the paths literally; nginx spells them as one regex, so
        the regex is compiled and matched rather than string-searched. A test
        that only looked for the substring would pass on a `location` that no
        longer matches — which is the drift most likely to happen."""
        assert _streaming_block_matches(config, path), (
            f"{path} streams Server-Sent Events but {config.name} does not route "
            "it through the no-buffering block"
        )

    def test_a_normal_route_is_not_swept_into_the_streaming_block(
        self, config: Path
    ) -> None:
        """The mirror of the above: an over-broad pattern would put every JSON
        response on a 24-hour timeout and disable compression site-wide."""
        assert not _streaming_block_matches(config, "/api/workflows")

    def test_buffering_is_turned_off(self, config: Path) -> None:
        """The failure this prevents: frames accumulate in the proxy and the
        editor's live node highlighting arrives in one lump at the end."""
        text = config.read_text()
        assert "flush_interval -1" in text or "proxy_buffering off" in text

    def test_the_timeout_outlasts_a_human_approval(self, config: Path) -> None:
        """60 seconds is the nginx default and is shorter than a person."""
        text = config.read_text()
        assert "read_timeout 24h" in text or "proxy_read_timeout 24h" in text

    def test_the_app_is_told_to_bind_loopback(self, config: Path) -> None:
        """A proxy in front of a process listening on 0.0.0.0 is a decoration:
        the port is reachable around it."""
        assert "127.0.0.1" in config.read_text()

    def test_authentication_is_not_silently_absent(self, config: Path) -> None:
        """Both files ship with the credential block commented out, which is
        correct — the deployer picks one — but the file must say so rather than
        leaving an unauthenticated proxy that looks finished."""
        text = config.read_text()
        assert "OPENSTATEGRAPH_API_TOKEN" in text
        assert "do not leave" in text.lower()

    def test_no_log_line_can_carry_the_token(self, config: Path) -> None:
        """The token arrives in `Authorization` and in the session cookie.
        Caddy's JSON log records every header unless told not to, so it says
        `delete`; nginx's default formats record neither, so the only way it
        could leak is by naming the variables — and it must not."""
        text = config.read_text()
        assert "$http_authorization" not in text
        assert "$http_cookie" not in text
        if config is CADDYFILE:
            assert "request>headers>Authorization delete" in text
            assert "request>headers>Cookie delete" in text


class TestTheDeployingGuide:
    """The threat model has to be written down where a deployer will read it."""

    def test_it_exists(self) -> None:
        assert (REPO / "docs" / "deploying.md").exists()

    @pytest.mark.parametrize(
        "claim",
        [
            "run arbitrary workflows",
            "read every workflow file",
            "spend",
            "write drafts",
        ],
    )
    def test_it_names_what_an_open_deployment_exposes(self, claim: str) -> None:
        # Whitespace-normalised: a claim must survive being re-wrapped, or the
        # test is really about the line width of a paragraph.
        prose = " ".join((REPO / "docs" / "deploying.md").read_text().lower().split())
        assert claim in prose

    def test_it_names_both_supported_answers(self) -> None:
        text = (REPO / "docs" / "deploying.md").read_text()
        assert "deploy/Caddyfile" in text
        assert "OPENSTATEGRAPH_API_TOKEN" in text

    def test_it_states_the_worker_ceiling_as_enforced(self) -> None:
        """Not "we recommend one worker" — the guide has to say it is refused,
        because that is what the code now does."""
        text = (REPO / "docs" / "deploying.md").read_text().lower()
        assert "refuse" in text
