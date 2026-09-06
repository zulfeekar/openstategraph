"""The package's half of the keyless report door — `team-board-and-gap-reports/09`.

`gap_report.py` builds a report and deliberately has no transport in it, so
that no call path can assemble one and dispatch it in the same breath. This
module is the transport, and it is a separate module for exactly that reason:
importing it is a decision somebody made.

Three properties are the whole design, and each one is a rule this repository
already keeps:

- **The endpoint is a variable, and unset means the door does not exist.**
  `OPENSTATEGRAPH_REPORT_ENDPOINT` names it; there is no default URL in this
  module, in this package, or in any build. That is `CLAUDE.md`'s Ollama rule
  — *never reach a vendor without naming a variable someone can set, see and
  revoke* — applied to the one place in this package that reaches anything of
  ours at all. `ReportDoorClosed` is what an unset variable produces, and it is
  an ordinary state of affairs rather than an error: most installs will never
  set it.

- **No key, and no vendor.** The door is public by design (its own
  `config.toml` says so and argues for it), so there is nothing here to
  authenticate with and nothing to rotate. From this side the door is a URL.

- **Nothing is sent that a person has not read.** `send` takes the rendered
  text as an argument and refuses to post if it is not what this report
  renders. That is opt-in per send expressed structurally: a caller cannot
  send without having produced the block a user reads, and cannot show one
  report and send another.

`urllib` rather than a client library, so the four-package core floor is
untouched — the same reason `08`'s door shells out to `gh` instead of adding a
dependency.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from openstategraph.gap_report import GapReport

__all__ = [
    "Accepted",
    "ENDPOINT_ENV",
    "Refused",
    "ReportDoorClosed",
    "Response",
    "Transport",
    "endpoint",
    "send",
]

#: The one variable that decides whether this door exists on an install.
ENDPOINT_ENV = "OPENSTATEGRAPH_REPORT_ENDPOINT"

#: How long to wait, in seconds. Short on purpose: a report is a courtesy, and
#: a courtesy that hangs a user's terminal is a defect.
TIMEOUT_SECONDS = 10.0


class ReportDoorClosed(RuntimeError):
    """No endpoint is configured, so there is nothing to send to.

    Raised rather than returned, because it is not an answer from a door — it
    is the absence of one, and a caller that treats it as a refusal would print
    a rejection nobody issued.
    """


@dataclass(frozen=True)
class Accepted:
    """The door took it. `count` is how many times this exact finding has now
    been reported from this install — one card, a count, which is what the
    dedup at the far end is for."""

    outcome: str
    count: int


@dataclass(frozen=True)
class Refused:
    """The door said no, in its own words.

    `reason` is one of the door's fixed reason strings (`rate-limited`,
    `too-large`, `not-json`, …), never prose and never anything derived from
    the report — the far side chose it from a closed set. `status` is the HTTP
    status, kept because `429` and `503` are two different conversations to
    have with a user.
    """

    status: int
    reason: str


Response = Accepted | Refused


class Transport(Protocol):
    """How the bytes leave. A protocol so a test can watch exactly what was
    posted without a network, and so nothing here has to be monkey-patched."""

    def __call__(
        self, url: str, body: bytes, headers: Mapping[str, str]
    ) -> tuple[int, bytes]: ...


def endpoint(environ: Mapping[str, str] | None = None) -> str | None:
    """The configured door, or `None` when there is none.

    Whitespace-only is `None` too: an environment variable set to the empty
    string is how a shell says *unset* by accident, and a door that treated it
    as a URL would fail in `urllib` instead of saying what is missing.
    """
    source = os.environ if environ is None else environ
    value = source.get(ENDPOINT_ENV, "").strip()
    return value or None


def _urllib_transport(
    url: str, body: bytes, headers: Mapping[str, str]
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as answer:
            return int(answer.status), answer.read()
    except urllib.error.HTTPError as refusal:
        # A refusal is an answer, and its body carries the reason string this
        # module's `Refused` is made of. `urllib` raises on 4xx/5xx, so the
        # answer has to be taken out of the exception or it is lost.
        return int(refusal.code), refusal.read()


def send(
    report: GapReport,
    url: str,
    *,
    shown: str,
    transport: Transport | Callable[..., tuple[int, bytes]] | None = None,
) -> Response:
    """Post one report, once, to the door at `url`.

    `shown` is the text the caller printed. It must be exactly
    `report.render()`, and the check is not ceremony: the failure it prevents
    is a door that renders one report for a person to read and posts another,
    which is the only way the promise in `docs/reporting-a-platform-gap.md`
    could be broken without anybody editing the model.

    What goes on the wire is the model's own dump — the same fields `render()`
    laid out, in the schema `docs/gap-report.schema.json` publishes, and
    nothing else.
    """
    if shown != report.render():
        raise ValueError(
            "a report is sent only after it has been shown — pass the exact text "
            "of report.render(), which is what the person read"
        )
    if not url.strip():
        raise ReportDoorClosed(
            f"no report endpoint is configured — set {ENDPOINT_ENV} to one, or "
            "file the report by hand"
        )

    post = transport or _urllib_transport
    body = json.dumps(report.model_dump(mode="json")).encode("utf-8")
    status, answer = post(
        url,
        body,
        {"content-type": "application/json", "content-length": str(len(body))},
    )
    return _read(status, answer)


def _read(status: int, answer: bytes) -> Response:
    """The door's answer, tolerantly.

    Tolerant in reading and strict in trusting, the same as everywhere else
    here: a body that is not JSON, or is JSON of an unexpected shape, becomes a
    `Refused` naming the status rather than an exception — a door that changed
    its answer shape should not turn a courtesy into a traceback. Nothing is
    acted on that was not recognised: only a 200 carrying an `outcome` this
    side knows is an `Accepted`.
    """
    try:
        payload = json.loads(answer.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    outcome = str(payload.get("outcome", ""))
    if status == 200 and outcome in ("filed", "counted"):
        try:
            count = int(payload.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        return Accepted(outcome=outcome, count=count)
    reason = str(payload.get("reason", "")) or (outcome or "unrecognised-answer")
    return Refused(status=status, reason=reason)
