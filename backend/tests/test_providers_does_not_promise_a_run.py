"""`openstategraph providers` may report only what it checked.

**The defect, in one sentence.** The command printed `ready` and a header
saying *"3 integrations installed and configured"* for three providers on the
strength of `is_configured()` alone — which asks whether *a credential is
present*, never whether a request would succeed. A supervisor session read
that word, concluded the credentials were live, and sent a correction into a
running ticket session instructing it to call a model
(`providers-and-credentials/12`).

**The states are five, and only three of them are knowable without a network
call:**

| State | Knowable offline |
| --- | --- |
| the extra is installed | yes — `find_spec` |
| a credential is present | yes — the environment |
| which variable supplied it | yes — the environment |
| the endpoint is reachable | **no** |
| a request will be answered | **no** |

So the row's word is `configured`, which is the repo's own word for the thing
that was actually measured (`ProviderEnvironment.is_configured`), and the only
route to the last two states is `--check`, which makes one real, billable
request per configured provider. `CLAUDE.md`'s law cuts both ways here: a
status that cannot be certain must not sound certain.

**Everything below drives the real CLI**, because the defect was a word a
person read on a terminal, and a unit test of `is_configured` would have
stayed green through all of it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

#: Every variable that could make this machine's own setup an input to a test.
_AMBIENT = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_API_KEY",
    "OLLAMA_HOST",
    "OLLAMA_ENDPOINT",
    "OPENSTATEGRAPH_ANTHROPIC_MODEL",
    "OPENSTATEGRAPH_OPENAI_MODEL",
    "OPENSTATEGRAPH_OLLAMA_MODEL",
)

_BACKEND = Path(__file__).resolve().parents[1]


def _cli(tmp_path: Path, *args: str, **credentials: str) -> subprocess.CompletedProcess[str]:
    """The installed command, in a stated environment, from an empty directory.

    `cwd=tmp_path` is load-bearing twice over: `find_config_file` and
    `find_env_file` both walk *up* from the working directory, so running here
    keeps this repository's own `openstategraph.yaml` and — much more
    importantly — the developer's real `.env` out of the measurement. The
    author's own first reading of this ticket was confounded by exactly that:
    the CLI reads `.env` and a bare `python3 -c` does not, so the two halves of
    the original report were taken in two different environments.
    """
    environment = {
        # `HOME` is the real one on purpose: this project's dependencies are
        # installed user-level, so a fabricated home takes `pydantic` off the
        # path and every row becomes an ImportError. Nothing under `HOME` is
        # an input to the states below — `.env` and `openstategraph.yaml` are
        # both found by walking *up from the working directory*, which is why
        # `cwd` is the empty one and `HOME` need not be.
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(_BACKEND),
    }
    environment.update(credentials)
    return subprocess.run(
        [sys.executable, "-m", "openstategraph.cli", "providers", *args],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


class TestTheWordOnTheRow:
    """`ready` is a promise; `configured` is a measurement."""

    def test_no_row_ever_says_ready(self, tmp_path: Path) -> None:
        """Not with a credential, not without one. The word is gone."""
        bare = _cli(tmp_path)
        keyed = _cli(tmp_path, ANTHROPIC_API_KEY="sk-test-value", OPENAI_API_KEY="sk-other")
        for result in (bare, keyed):
            assert "ready" not in result.stdout.lower(), result.stdout

    def test_a_credential_present_reads_as_configured(self, tmp_path: Path) -> None:
        result = _cli(tmp_path, ANTHROPIC_API_KEY="sk-test-value")
        row = _row(result.stdout, "anthropic")
        assert "configured" in row, result.stdout

    def test_no_credential_still_reads_as_needing_a_key(self, tmp_path: Path) -> None:
        """The inverse. A working row must not be the only distinguishable one."""
        result = _cli(tmp_path)
        assert "needs a key" in _row(result.stdout, "anthropic"), result.stdout

    def test_configured_and_unconfigured_are_different_words(self, tmp_path: Path) -> None:
        """The whole ticket: an unusable provider must not read like a usable one.

        On the **state column alone**. Comparing whole rows passed against a
        mutant that reported every installed provider as configured, because
        the credential line underneath still differed — a test that agrees
        with itself. The column is where a reader's eye goes and it is the
        thing that must move.
        """
        keyed = _state(_cli(tmp_path, OPENAI_API_KEY="sk-x").stdout, "openai")
        bare = _state(_cli(tmp_path).stdout, "openai")
        assert keyed == "configured"
        assert bare == "needs a key"


class TestTheHeader:
    """*"3 integrations installed and configured"* while none could run."""

    def test_it_does_not_call_a_keyless_install_configured(self, tmp_path: Path) -> None:
        result = _cli(tmp_path)
        assert "and configured" not in result.stdout, result.stdout
        assert "none configured" in result.stdout, result.stdout

    def test_it_counts_the_configured_ones_honestly(self, tmp_path: Path) -> None:
        result = _cli(tmp_path, ANTHROPIC_API_KEY="sk-a", OPENAI_API_KEY="sk-b")
        assert "2 of 4" in result.stdout, result.stdout


class TestWhatSuppliedTheCredential:
    """The state a reader could not see, and the one that settles Ollama."""

    def test_the_row_names_the_variable_that_supplied_it(self, tmp_path: Path) -> None:
        result = _cli(tmp_path, ANTHROPIC_API_KEY="sk-test-value")
        assert "ANTHROPIC_API_KEY" in _row(result.stdout, "anthropic")

    def test_a_secret_is_masked_and_never_printed_whole(self, tmp_path: Path) -> None:
        result = _cli(tmp_path, ANTHROPIC_API_KEY="sk-supersecret-do-not-print")
        assert "sk****" in result.stdout, result.stdout
        assert "supersecret" not in result.stdout

    def test_the_ollama_daemon_setup_is_configured_and_says_which_variable(
        self, tmp_path: Path
    ) -> None:
        """`CLAUDE.md`'s two setups, both still supported and now distinguishable.

        `OLLAMA_HOST` alone is a daemon the developer runs, which needs no key
        of ours. `is_configured` takes **any** of `env_vars` deliberately, and
        this pins that it still does — while the row now says *which* of the
        two answered, which is the thing a reader could not previously see.
        """
        daemon = _cli(tmp_path, OLLAMA_HOST="http://localhost:11434")
        row = _row(daemon.stdout, "ollama")
        assert "configured" in row
        # `OLLAMA_HOST is set`, not merely the name somewhere in the row — the
        # `reads` list names both variables whatever is set, so asserting on
        # the bare name passed against a mutant that had stopped saying which
        # of the two answered, which is the only thing this row adds.
        assert "OLLAMA_HOST is set" in row, row
        assert "OLLAMA_API_KEY is set" not in row, row
        assert "http://localhost:11434" in row, "an address is not a secret and is shown whole"

        cloud = _cli(tmp_path, OLLAMA_API_KEY="ok-abcdef")
        cloud_row = _row(cloud.stdout, "ollama")
        assert "configured" in cloud_row
        assert "OLLAMA_API_KEY is set" in cloud_row, cloud_row


class TestItSaysNothingWasCalled:
    def test_the_status_admits_it_made_no_request(self, tmp_path: Path) -> None:
        out = _cli(tmp_path, ANTHROPIC_API_KEY="sk-a").stdout
        assert "no provider was called" in out.lower(), out
        assert "--check" in out, out

    def test_status_exits_ok_even_with_nothing_configured(self, tmp_path: Path) -> None:
        """A status command succeeds when it can report.

        `providers` is the command you run *because* something is wrong, so a
        non-zero exit would make it useless inside `set -e`. The assertion
        belongs to `--check`, below, which is a different question.
        """
        assert _cli(tmp_path).returncode == 0


class TestItNamesTheEnvironmentItRead:
    """`providers-and-credentials/13` — the CLI names its `.env`, so a reader
    can tell whether a server started some other way has the same keys.

    `_cli` already runs from an empty `tmp_path` with no `.env` in it (that
    is what keeps the developer's real file out of every other test in this
    module) — exactly the sandbox this class needs to test the *absence*
    case, and it writes its own `.env` into that same directory to test the
    *presence* case.
    """

    def test_no_env_file_says_so_plainly(self, tmp_path: Path) -> None:
        out = _cli(tmp_path).stdout
        assert "No .env file was found" in out, out

    def test_a_found_env_file_is_named_and_marked_read(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-a\n")
        out = _cli(tmp_path, ANTHROPIC_API_KEY="sk-a").stdout
        assert str(tmp_path / ".env") in out, out
        assert "(read)" in out, out

    def test_it_warns_a_server_started_another_way_does_not_read_it(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-a\n")
        out = _cli(tmp_path, ANTHROPIC_API_KEY="sk-a").stdout
        assert "does not read it automatically" in out, out


class TestTheOptInCheck:
    """The only certain answer, priced and opt-in.

    Driven in-process with a stubbed `build_chat_model`, because a test suite
    must not spend money — but through the real `main()`, so the exit code and
    the printed text are the shipped ones.
    """

    def _providers(self, monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]) -> int:
        from openstategraph import chat_model

        def fake(model_name: str) -> Any:
            outcome = answers[model_name.split(":", 1)[0]]
            if isinstance(outcome, Exception):
                raise outcome

            class _Model:
                def invoke(self, _prompt: str) -> Any:
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome

            return _Model()

        monkeypatch.setattr(chat_model, "build_chat_model", fake)
        from openstategraph.cli import main

        return main(["providers", "--check"])

    @pytest.fixture(autouse=True)
    def _stated_machine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in _AMBIENT:
            monkeypatch.delenv(name, raising=False)

    def test_every_provider_answering_exits_ok(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        code = self._providers(monkeypatch, {"anthropic": "hello"})
        out = capsys.readouterr().out
        assert "answered" in out, out
        assert code == 0

    def test_a_provider_that_cannot_answer_exits_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-bad")
        code = self._providers(monkeypatch, {"anthropic": RuntimeError("401 Unauthorized")})
        out = capsys.readouterr().out
        assert "did not answer" in out, out
        assert code == 1

    def test_nothing_configured_is_a_failed_check(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--check` asks "can I run"; with no credential the answer is no."""
        code = self._providers(monkeypatch, {})
        assert code == 1
        assert "nothing to check" in capsys.readouterr().out.lower()

    def test_the_check_warns_it_costs_money_before_spending_it(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-a")
        self._providers(monkeypatch, {"anthropic": "hello"})
        out = capsys.readouterr().out.lower()
        assert "billable" in out or "costs" in out, out


class TestWhatMustNotHaveChanged:
    def test_the_missing_key_sentence_is_untouched(self) -> None:
        """`d622879`'s sibling work made this good; the defect was upstream."""
        from openstategraph.providers import provider_catalogue

        spec = provider_catalogue().get("anthropic")
        assert spec is not None
        message = spec.missing_key_message()
        assert "ANTHROPIC_API_KEY" in message
        assert ".env" in message
        assert "openstategraph env-example" in message

    def test_the_unreachable_vocabulary_was_not_duplicated(self) -> None:
        """`ProviderUnreachable` already owns "configured but not listening"."""
        source = (_BACKEND / "openstategraph" / "cli.py").read_text(encoding="utf-8")
        assert "unreachable" not in source.lower().split("def cmd_providers")[1][:4000]

    def test_the_status_endpoint_contract_still_carries_its_fields(self) -> None:
        from openstategraph.api.schemas import ProviderStatusResponse

        fields = set(ProviderStatusResponse.model_fields)
        assert {"name", "key_hint", "configured", "configured_by"} <= fields, json.dumps(sorted(fields))


def _state(stdout: str, provider: str) -> str:
    """The state column of one provider's row, and nothing else."""
    line = _row(stdout, provider).splitlines()[0]
    return line[12:24].strip()


def _row(stdout: str, provider: str) -> str:
    """The two printed lines belonging to one provider, joined."""
    lines = stdout.splitlines()
    for index, line in enumerate(lines):
        if line.startswith(provider):
            return "\n".join(lines[index : index + 2])
    raise AssertionError(f"no row for {provider!r} in:\n{stdout}")
