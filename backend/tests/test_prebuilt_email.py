"""The email atom's two safety properties.

1. The recipient is wiring, not a model argument — `Args` has no `to`, and
   `configure` returns a fresh instance (never mutates the registry one).
2. Without SMTP configuration nothing leaves the machine: the dry run writes
   a complete RFC-5322 message to the outbox and says so in the result.
"""

from __future__ import annotations

from openstategraph.prebuilt_email import EmailArgs, EmailSendTool


class TestRecipientIsWiring:
    def test_args_do_not_include_a_recipient(self) -> None:
        assert "to" not in EmailArgs.model_fields

    def test_configure_returns_a_fresh_instance(self) -> None:
        shared = EmailSendTool()
        bound = shared.configure({"to": "me@zulfeekar.com"})
        assert bound is not shared
        assert shared._to == ""

    def test_no_recipient_is_a_readable_failure(self, tmp_path) -> None:
        result = EmailSendTool(outbox=tmp_path).run(subject="s", body="b")
        assert not result.ok
        assert "recipient" in result.error.lower()

    def test_a_malformed_recipient_is_refused(self, tmp_path) -> None:
        result = EmailSendTool(to="not-an-address", outbox=tmp_path).run(subject="s", body="b")
        assert not result.ok


class TestDryRun:
    def test_writes_a_complete_eml_and_says_dry_run(self, tmp_path, monkeypatch) -> None:
        monkeypatch.delenv("OPENSTATEGRAPH_SMTP_HOST", raising=False)
        tool = EmailSendTool(to="me@zulfeekar.com", outbox=tmp_path)
        result = tool.run(subject="Weekly analytics", body="Views up 12%.")
        assert result.ok
        assert "DRY RUN" in result.content
        files = list(tmp_path.glob("*.eml"))
        assert len(files) == 1
        raw = files[0].read_text()
        assert "To: me@zulfeekar.com" in raw
        assert "Subject: Weekly analytics" in raw
        assert "Views up 12%." in raw

    def test_extra_arguments_are_rejected_not_silently_dropped(self, tmp_path) -> None:
        tool = EmailSendTool(to="me@zulfeekar.com", outbox=tmp_path)
        result = tool.run(subject="s", body="b", to="attacker@example.com")
        assert not result.ok
        assert "Invalid arguments" in result.error
