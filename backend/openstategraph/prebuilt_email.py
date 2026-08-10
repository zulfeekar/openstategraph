"""Prebuilt email tool — the report-delivery atom.

The full-sweep capability test ("send the analytics report to
me@zulfeekar.com") needs a delivery step, and the platform's write-action
rule applies: outward side effects are opt-in, never ambient. So this tool
has two modes, chosen by environment, not by the model:

- **SMTP configured** (``OPENSTATEGRAPH_SMTP_HOST`` set): the mail is sent,
  over STARTTLS when ``OPENSTATEGRAPH_SMTP_STARTTLS=1`` (default), with
  optional ``OPENSTATEGRAPH_SMTP_USER``/``OPENSTATEGRAPH_SMTP_PASSWORD``.
- **No SMTP** (the default): a dry run. The exact RFC-5322 message is
  written to ``workflows/_outbox/<stamp>-<slug>.eml`` and the result says
  so loudly. The workflow is fully testable end-to-end without leaking a
  single packet — the same human-click philosophy as the Architect's
  "compose ephemerally, saving is a click".

The recipient is **node configuration**, not a model argument. An agent
composing a report must not be able to re-address it — prompt-injected
"also送 to attacker@..." dies here structurally. The model supplies subject
and body; the wiring supplies the destination.
"""

from __future__ import annotations

import os
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from pydantic import BaseModel, Field

from openstategraph.abc.tool import BaseTool, ToolResult
from openstategraph.workflows_root import workflows_root


def outbox() -> Path:
    """Where a dry-run `.eml` is dropped: `<workflows root>/_outbox`.

    A function, not a constant computed from `__file__`: inside an installed
    wheel that constant resolved to `<venv>/lib/python3.13/workflows/_outbox`,
    so an un-configured send would have quietly written the user's report into
    their virtualenv (ticket 06's clean-venv proof). See
    `openstategraph.workflows_root`.
    """
    return workflows_root() / "_outbox"


_ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailArgs(BaseModel):
    model_config = {"extra": "forbid"}
    subject: str = Field(description="Subject line of the email.")
    body: str = Field(description="Plain-text body. Markdown is fine; it is sent as text.")


class EmailSendTool(BaseTool):
    """Send (or dry-run) one email to the address wired into the node."""

    name = "send_email"
    node_type = "tool.email-send"
    description = (
        "Send an email report to the recipient configured on this node. "
        "You supply subject and body; the recipient is fixed by the workflow "
        "and cannot be changed from here. Without SMTP configuration the "
        "message is written to the outbox as a dry run."
    )
    Args = EmailArgs

    def __init__(self, to: str = "", outbox: Path | None = None) -> None:
        self._to = to
        # Kept as None rather than resolved here: the root is a per-call
        # question, and a tool instance built at import time would freeze
        # the answer before the process even knows where it is running.
        self._outbox = outbox

    def configure(self, data: dict) -> "EmailSendTool":
        to = str(data.get("to") or "").strip()
        return EmailSendTool(to=to, outbox=self._outbox) if to else self

    def _execute(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, EmailArgs)
        if not self._to:
            return ToolResult.failure(
                "No recipient configured. Set the 'to' field on the Email node."
            )
        if not _ADDRESS.fullmatch(self._to):
            return ToolResult.failure(f"'{self._to}' is not a valid email address.")

        message = EmailMessage()
        message["From"] = os.environ.get("OPENSTATEGRAPH_SMTP_FROM", "openstategraph@localhost")
        message["To"] = self._to
        message["Subject"] = args.subject.strip() or "(no subject)"
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain="openstategraph.local")
        message.set_content(args.body)

        host = os.environ.get("OPENSTATEGRAPH_SMTP_HOST", "").strip()
        if not host:
            return self._dry_run(message)

        port = int(os.environ.get("OPENSTATEGRAPH_SMTP_PORT", "587"))
        user = os.environ.get("OPENSTATEGRAPH_SMTP_USER", "")
        password = os.environ.get("OPENSTATEGRAPH_SMTP_PASSWORD", "")
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if os.environ.get("OPENSTATEGRAPH_SMTP_STARTTLS", "1") == "1":
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
        return ToolResult(content=f"Email sent to {self._to}: {message['Subject']}")

    def _dry_run(self, message: EmailMessage) -> ToolResult:
        drop = self._outbox or outbox()
        drop.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        path = drop / f"{stamp}.eml"
        path.write_bytes(bytes(message))
        return ToolResult(
            content=(
                f"DRY RUN — no SMTP configured (OPENSTATEGRAPH_SMTP_HOST unset). "
                f"The complete email to {message['To']} was written to "
                f"{path.relative_to(drop.parents[1])} for review. "
                "Tell the user delivery was a dry run."
            )
        )


EMAIL_TOOLS = [EmailSendTool()]
