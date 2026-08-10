"""What `openstategraph serve --port` actually does.

Scale-and-adopt ticket 01. Port handling is one of those things every server
gets *almost* right, and the almost is what wastes the adopter's first five
minutes. So the three cases are specified rather than left to whatever the
server library happens to do:

| what you typed | what you get |
| --- | --- |
| nothing | 8000 if it is free, otherwise the next free port |
| `--port N` | exactly N, or a clear failure — never a silent neighbour |
| `--port 0` | whatever the OS hands out |

The listening socket is bound **here**, before uvicorn starts, and handed to
it. That is not decoration: it is the only way `--port 0` can print the URL it
ended up on, and it closes the race a "probe then re-bind" implementation
leaves open.
"""

from __future__ import annotations

import socket

import pytest

from openstategraph.api.listening import (
    DEFAULT_PORT,
    PortUnavailable,
    bind_listener,
    listen_urls,
)


def occupy(port: int = 0) -> socket.socket:
    """A real listener, because a port is only in use when something holds it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    return sock


class TestExplicitPort:
    def test_an_explicit_port_is_that_port(self) -> None:
        held = occupy()
        free = held.getsockname()[1]
        held.close()

        sock = bind_listener("127.0.0.1", free)
        try:
            assert sock.getsockname()[1] == free
        finally:
            sock.close()

    def test_an_explicit_port_that_is_taken_fails_and_says_what_to_do(self) -> None:
        """Never quietly move to another port: the person who typed `--port
        8000` has something else pointed at 8000."""
        held = occupy()
        taken = held.getsockname()[1]
        try:
            with pytest.raises(PortUnavailable) as excinfo:
                bind_listener("127.0.0.1", taken)
        finally:
            held.close()

        message = str(excinfo.value)
        assert f"port {taken} is in use" in message
        assert "--port 0" in message


class TestZero:
    def test_zero_lets_the_operating_system_choose(self) -> None:
        sock = bind_listener("127.0.0.1", 0)
        try:
            assert sock.getsockname()[1] > 0
        finally:
            sock.close()


class TestNoFlag:
    def test_no_flag_takes_the_default_port_when_it_is_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        held = occupy()
        free = held.getsockname()[1]
        held.close()
        monkeypatch.setattr("openstategraph.api.listening.DEFAULT_PORT", free)

        sock = bind_listener("127.0.0.1", None)
        try:
            assert sock.getsockname()[1] == free
        finally:
            sock.close()

    def test_no_flag_moves_to_the_next_free_port_rather_than_failing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two copies of the editor at once is a normal thing to want, and
        `[Errno 48] Address already in use` is not an answer to it."""
        held = occupy()
        taken = held.getsockname()[1]
        monkeypatch.setattr("openstategraph.api.listening.DEFAULT_PORT", taken)
        try:
            sock = bind_listener("127.0.0.1", None)
        finally:
            held.close()
        try:
            assert sock.getsockname()[1] != taken
        finally:
            sock.close()

    def test_the_default_port_is_the_one_every_document_names(self) -> None:
        assert DEFAULT_PORT == 8000


class TestTheUrlsItPrints:
    def test_it_names_the_editor_the_chat_and_the_api(self) -> None:
        urls = listen_urls("127.0.0.1", 51423)

        assert urls["editor"] == "http://127.0.0.1:51423/"
        assert urls["chat"] == "http://127.0.0.1:51423/chat"
        assert urls["api"] == "http://127.0.0.1:51423/api/health"

    def test_a_wildcard_bind_is_reported_as_a_reachable_address(self) -> None:
        """`http://0.0.0.0:8000/` is not a URL anybody can open."""
        assert listen_urls("0.0.0.0", 8000)["editor"] == "http://localhost:8000/"
        assert listen_urls("::", 8000)["editor"] == "http://localhost:8000/"
