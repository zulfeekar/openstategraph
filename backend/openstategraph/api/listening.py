"""Which port `openstategraph serve` listens on, and what it says about it.

**Tier 3, internal.** The *behaviour* is the contract (`docs/adoption.md`);
this module is where it lives so `cli.py` stays argument handling plus a call.

Three cases, deliberately different, because they answer three different
questions an adopter is actually asking:

| what you typed | what it means |
| --- | --- |
| nothing | "give me the editor" — 8000 if free, otherwise the next free port |
| `--port N` | "it must be N" — something else is pointed at N |
| `--port 0` | "I don't care, tell me where" |

The socket is bound **here** and handed to uvicorn (`Server.run(sockets=…)`)
rather than passing a number and hoping. That is what makes `--port 0` able to
print the URL it landed on *before* the server starts, and it removes the
window a probe-then-rebind implementation leaves between finding a free port
and taking it.

Nothing here imports uvicorn or FastAPI — it is `socket` from the standard
library, so it is testable without the `[server]` extra installed.
"""

from __future__ import annotations

import socket

#: What every document, Docker file and bookmark already says.
DEFAULT_PORT = 8000

#: How far to walk upward from the default before giving up and asking the OS.
#: Sixty-four is far past "a few editors open" and short of a scan that looks
#: like a probe to anything watching.
SCAN_LIMIT = 64

#: Bind addresses that are not somewhere a browser can go.
_WILDCARD = {"0.0.0.0", "::", "", "*"}


class PortUnavailable(RuntimeError):
    """An explicitly requested port is taken. Carries the message verbatim."""


def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    # Lets a restart reuse a port still in TIME_WAIT. It does NOT let two live
    # listeners share one, which is the whole reason bind() can still fail
    # below — and must, or `--port N` would stop meaning N.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    sock.listen(2048)
    sock.set_inheritable(True)
    return sock


def bind_listener(host: str, port: int | None) -> socket.socket:
    """A listening socket for `serve`, following the table above.

    `port=None` is "no flag". `port=0` is the OS's choice. Anything else is
    exact or `PortUnavailable`.
    """
    if port is not None:
        try:
            return _bind(host, port)
        except OSError as exc:
            if port == 0:  # pragma: no cover — the OS has no free ports at all
                raise
            raise PortUnavailable(
                f"port {port} is in use — try `openstategraph serve --port 0` "
                f"to pick a free one, or stop whatever is listening on {port}"
            ) from exc

    for candidate in range(DEFAULT_PORT, DEFAULT_PORT + SCAN_LIMIT):
        try:
            return _bind(host, candidate)
        except OSError:
            continue
    # Every port in the window is taken. The OS still has one somewhere, and
    # the caller prints whatever it gets, so this is a working answer rather
    # than a failure.
    return _bind(host, 0)


def listen_urls(host: str, port: int) -> dict[str, str]:
    """The three URLs worth printing, in the order a person reads them.

    A wildcard bind is reported as `localhost`, because `http://0.0.0.0:8000/`
    is not an address a browser opens — it is what the server *accepts on*.
    """
    displayed = "localhost" if host in _WILDCARD else host
    if ":" in displayed:  # a literal IPv6 address needs brackets in a URL
        displayed = f"[{displayed}]"
    origin = f"http://{displayed}:{port}"
    return {"editor": f"{origin}/", "chat": f"{origin}/chat", "api": f"{origin}/api/health"}

# No `__all__` here on purpose: everything under `openstategraph/api/` is Tier 3
# — internal, no stability guarantee — and `__all__` reads as a promise. The
# promises are `openstategraph.__all__` and `openstategraph.abc`.
