"""Optional first-party authentication — one shared token, off by default.

**The decision (scale-and-adopt ticket 06).** Until now the answer to "who can
call this API?" was "whoever the deployer's reverse proxy lets through", and
the proxy was not shipped. Two things are wrong with that as a 1.0 answer:

1. The commonest deployment is **an MCP server or `openstategraph serve` on a
   laptop or a team VM with no proxy at all**. "Configure a proxy" is advice,
   not a product, and advice is not what a `--host 0.0.0.0` typed at 6pm obeys.
2. The proxy is still the right answer for anything public — TLS, rate
   limiting, IP allow-lists and OIDC all belong there, and reimplementing them
   here would be a worse version of Caddy.

So both ship, with different jobs. `deploy/Caddyfile` and `deploy/nginx.conf`
are the **supported** path for anything reachable from more than one machine.
This module is the floor underneath it: a single shared bearer token that turns
"no authentication at all" into "one secret", in one environment variable, for
the case where there is no proxy and never will be.

## What it is, precisely

- **A shared secret, not identity.** Every holder of the token is the same
  principal with the same capabilities. It answers "is this stranger allowed
  in", never "who is this" — see `docs/deploying.md` for the threat model, and
  do not build per-user authorization on top of it.
- **Environment only.** `OPENSTATEGRAPH_API_TOKEN`, never the config file: a
  DSN or a token is a credential, and `config_file._reject_secrets` already
  refuses to let this project's committed YAML carry one. That rule is what
  makes it safe to `git add openstategraph.yaml`, so the token has to live
  where the provider keys live.
- **Off by default, and loud about it.** Unset means no gate, exactly as
  today — a first run must not need a secret. `exposure_warning` is what
  keeps that honest: binding a keyless-but-unauthenticated process to a
  non-loopback address prints what it just exposed.
- **Two ways to present it, one secret.** `Authorization: Bearer <token>` for
  machines (curl, the SDK, an MCP client) and a session cookie for browsers,
  set by a minimal `/login` form. Without the cookie half, turning the token on
  would break the editor and the chat page, and a security control that breaks
  the product is a security control that gets turned off.

## Why a pure-ASGI middleware

`BaseHTTPMiddleware` buffers through an anyio task group and is the classic way
to break exactly the three endpoints this app cares most about — `/api/events`,
`/api/runs/stream` and `/api/runs/resume` are long-lived `text/event-stream`
responses whose cancellation semantics `streaming.stop_when_client_leaves`
depends on. A plain ASGI callable adds one dict lookup and touches neither the
response nor the disconnect. It also means the same class gates the MCP
transport's Starlette app, which is not a FastAPI app at all.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import os
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)

#: The one place the shared token is configured. A name, in the environment,
#: like every other credential this project touches.
API_TOKEN_ENV = "OPENSTATEGRAPH_API_TOKEN"

#: The browser half of the same secret. `osg_` prefixed so it is obvious in a
#: cookie jar which product put it there.
SESSION_COOKIE = "osg_session"

#: Paths served without a token even when the gate is on.
#:
#: `/api/health` because a health check is what a load balancer and a container
#: orchestrator call before anything has credentials, and a liveness probe that
#: 401s is an outage. It answers a fixed literal and reads no state, so it
#: leaks nothing beyond "something is listening" — which the open TCP port
#: already said. `/login` because that is where you go to get in.
OPEN_PATHS: frozenset[str] = frozenset({"/api/health", "/login"})

#: How long a browser session lasts. Long enough that the editor is not a
#: login form, short enough that a borrowed laptop is not permanent.
SESSION_MAX_AGE = 30 * 24 * 60 * 60

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def configured_token() -> str | None:
    """The shared token, or None when this deployment has no gate.

    Whitespace-only is None rather than a token nobody can type: an
    `OPENSTATEGRAPH_API_TOKEN=` left in a `.env` is somebody turning it off,
    and honouring it as an empty secret would gate the app behind a string no
    client can send.
    """
    raw = os.environ.get(API_TOKEN_ENV, "").strip()
    return raw or None


def matches(presented: str | None, expected: str) -> bool:
    """Constant-time comparison, because the alternative leaks the token.

    `==` on a secret is a timing oracle: an attacker who can measure the
    response can recover the token one character at a time. `compare_digest` is
    stdlib and costs nothing.
    """
    if not presented:
        return False
    return hmac.compare_digest(presented, expected)


def presented_credential(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    """The token this request carries, from either accepted place.

    The header wins over the cookie, so a machine client that sends both is not
    silently authenticated as whatever a stale browser session said.
    """
    cookie_header = b""
    for name, value in headers:
        lowered = name.lower()
        if lowered == b"authorization":
            text = value.decode("latin-1").strip()
            if text.lower().startswith("bearer "):
                return text[7:].strip()
        elif lowered == b"cookie":
            cookie_header = value
    if cookie_header:
        for pair in cookie_header.decode("latin-1").split(";"):
            key, _, cookie_value = pair.partition("=")
            if key.strip() == SESSION_COOKIE:
                return cookie_value.strip()
    return None


class TokenGate:
    """Refuses every request that does not carry the shared token.

    Three collaborators' worth of behaviour and no more: what the secret is,
    which paths are open, and where a browser should be sent instead of a bare
    401. `login_path=None` makes it machine-only, which is what the MCP
    transport wants — an MCP client cannot fill in a form.
    """

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        token: str,
        *,
        open_paths: Iterable[str] = OPEN_PATHS,
        login_path: str | None = "/login",
    ) -> None:
        self.app = app
        self._token = token
        self._open = frozenset(open_paths)
        self._login_path = login_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # `lifespan` carries no credential and never can — gating it would stop
        # the app from starting rather than stop an attacker.
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path in self._open:
            await self.app(scope, receive, send)
            return
        if matches(presented_credential(scope.get("headers") or []), self._token):
            await self.app(scope, receive, send)
            return
        await self._refuse(scope, send)

    async def _refuse(self, scope: Scope, send: Send) -> None:
        """401 for a machine; a redirect to the form for a browser.

        The distinction is `Accept: text/html`, not the path: the editor's own
        `fetch` calls ask for JSON and must get a status their error handling
        can read, while a person who typed the URL should land on the form
        rather than on the word "unauthorized".
        """
        if self._login_path and _wants_html(scope.get("headers") or []):
            await _respond(
                send,
                303,
                b"",
                [(b"location", self._login_path.encode("ascii"))],
            )
            return
        await _respond(
            send,
            401,
            b'{"detail":"a bearer token is required - see docs/deploying.md"}',
            [
                (b"content-type", b"application/json"),
                # Named in the challenge because a client that does not know
                # *how* to authenticate retries the same way forever.
                (b"www-authenticate", b'Bearer realm="openstategraph"'),
            ],
        )


def _wants_html(headers: Iterable[tuple[bytes, bytes]]) -> bool:
    for name, value in headers:
        if name.lower() == b"accept":
            return b"text/html" in value.lower()
    return False


async def _respond(
    send: Send, status: int, body: bytes, headers: list[tuple[bytes, bytes]]
) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [*headers, (b"content-length", str(len(body)).encode("ascii"))],
        }
    )
    await send({"type": "http.response.body", "body": body})


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenStateGraph — sign in</title>
<style>
 body{font:16px/1.5 system-ui,sans-serif;margin:0;display:grid;place-items:center;
      min-height:100vh;background:#0d1117;color:#e6edf3}
 form{display:grid;gap:12px;width:min(360px,90vw)}
 h1{font-size:18px;margin:0}
 p{margin:0;color:#8b949e;font-size:14px}
 input,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #30363d}
 input{background:#161b22;color:inherit}
 button{background:#238636;color:#fff;border-color:#238636;cursor:pointer}
 .bad{color:#f85149}
</style></head><body>
<form method="post" action="/login">
  <h1>OpenStateGraph</h1>
  <p>This deployment requires the shared access token.</p>
  __ERROR__
  <input type="password" name="token" placeholder="access token" autofocus
         autocomplete="current-password" required>
  <button type="submit">Sign in</button>
</form></body></html>
"""


def login_page_html(*, failed: bool = False) -> str:
    """The whole browser half of the token, in one self-contained page.

    Self-contained on purpose: it is served *before* authentication, so it must
    not pull the editor bundle, and it must work when the editor is not
    installed at all.
    """
    error = '<p class="bad">That token was not accepted.</p>' if failed else ""
    return LOGIN_PAGE.replace("__ERROR__", error)


def install(app: Any) -> bool:
    """Gate `app` and give it a login form, if a token is configured.

    Returns whether the gate went on, so the caller can log one honest line
    either way. Called from `create_app`; separate from it because "is there a
    token" is not a question about the API's routes.
    """
    from starlette.responses import HTMLResponse, RedirectResponse
    from starlette.routing import Route

    token = configured_token()
    if token is None:
        return False

    async def login_form(_request: Any) -> Any:
        return HTMLResponse(login_page_html())

    async def login_submit(request: Any) -> Any:
        form = await request.form()
        presented = str(form.get("token") or "")
        if not matches(presented, token):
            # 401 with the form again, not a redirect: the status code is what
            # a script or a password manager reads, and re-rendering keeps the
            # token out of the URL and therefore out of every access log.
            return HTMLResponse(login_page_html(failed=True), status_code=401)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_MAX_AGE,
            httponly=True,  # no XSS in the editor can read it out
            samesite="strict",  # and no other origin can ride on it (CSRF)
            secure=request.url.scheme == "https",
            path="/",
        )
        return response

    # Plain Starlette `Route`s rather than `@app.get`/`@app.post`, for two
    # reasons that both matter. FastAPI resolves a handler's annotations at
    # registration time and this module uses `from __future__ import
    # annotations`, so a locally-imported `Request` type is a string it cannot
    # resolve — the endpoint silently becomes a *query parameter* called
    # `request` and every POST is a 422. And a non-`APIRoute` is invisible to
    # the OpenAPI generator, which is right: the login form is not part of the
    # published API contract (`docs/openapi.json`).
    app.router.routes.append(Route("/login", login_form, methods=["GET"]))
    app.router.routes.append(Route("/login", login_submit, methods=["POST"]))

    app.add_middleware(TokenGate, token=token)
    return True


def exposure_warning(host: str) -> str | None:
    """What this bind exposes, said before it is exposed — or None if it is not.

    Only for a **non-loopback** bind with no token: `127.0.0.1` with no token is
    a developer on their own machine and warning them every run is how a
    warning becomes wallpaper. Deliberately not a refusal — `--host 0.0.0.0`
    behind a proxy is a correct, supported deployment, and this module cannot
    see the proxy.
    """
    if configured_token() is not None:
        return None
    if _is_loopback(host):
        return None
    return (
        f"WARNING: binding to {host} with no authentication.\n"
        "  Anyone who can reach this port can run your workflows, read every\n"
        "  workflow file, spend your model budget and write drafts to disk.\n"
        f"  Set {API_TOKEN_ENV} to require a shared token, or put this behind\n"
        "  the reverse proxy in deploy/Caddyfile. See docs/deploying.md."
    )


def shared_deployment_reason(request: Any) -> str | None:
    """Why this request is **not** from a single-user machine — or `None`.

    Asked once per request, by every door that accepts `credentials` in its
    body (`the-boundary-nobody-checked/03`). A key a browser pastes goes into
    `os.environ`, which is process-global: on a server the operator left
    unconfigured, the first request to arrive *becomes* the configuration and
    every later caller's prompts then bill to — and are logged by — that one
    person's vendor account. `apply_credentials` cannot see the difference
    between the laptop where that is the whole point of the dialog and the team
    VM where it is a boundary crossing. This is what can.

    Three signals, any of which means somebody other than the operator can
    reach this process, and none of which needs a new variable to set:

    - **A shared token is configured.** A deployment turns the gate on because
      more than one person calls it; that is what the gate is *for*.
    - **The proxy said so.** `PROXY_ASSERTION_HEADER` is set by every config in
      `deploy/` (ticket 01), so a request carrying it arrived over a network
      and the loopback address below belongs to the proxy, not to the caller.
    - **The caller is not on this machine.** Anything that is not provably a
      loopback literal is treated as remote, the same direction `_is_loopback`
      already fails in: the safe answer to "is this exposed?" is yes.

    Returns the sentence a log line and an operator need, never a value, and
    never a refusal of the *request* — a shared deployment still runs the
    workflow, on the operator's own credentials, and says the missing-key
    message that names the variable to set when there are none.

    **What it does not cover, said plainly.** A loopback bind with no token
    forwarded over an SSH tunnel presents as local, because at the socket it
    *is* local. That deployment has no authentication of any kind, so a
    borrowed key is not the boundary it is missing first; `exposure_warning`
    and `docs/deploying.md` §1 are where it is addressed.
    """
    from openstategraph.principal import PROXY_ASSERTION_HEADER

    if configured_token() is not None:
        return (
            f"this deployment sets {API_TOKEN_ENV}, so more than one person can reach it"
        )
    headers = getattr(request, "headers", None)
    if headers is not None and PROXY_ASSERTION_HEADER.lower() in headers:
        return f"this request arrived through a reverse proxy ({PROXY_ASSERTION_HEADER})"
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if not host or not _is_loopback(host):
        return f"this request came from {host or 'an unknown address'}, not from this machine"
    return None


def _is_loopback(host: str) -> bool:
    text = (host or "").strip().strip("[]")
    if text in {"localhost", ""}:
        return True
    try:
        return ipaddress.ip_address(text).is_loopback
    except ValueError:
        # A hostname we cannot resolve to a literal is not provably local, and
        # the safe answer to "is this exposed?" is yes.
        return False


# No `__all__` here on purpose: `openstategraph.api` is Tier 3 (internal), and
# `tests/test_public_api.py` enforces that a private module never writes one —
# an export list reads as a stability promise this package does not make.
