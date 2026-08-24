"""`scripts/lib/pip_retry.sh` — bounded polling for index propagation delay.

launch-readiness ticket 37: a version published minutes earlier was reported
as nonexistent by `pip`, because the release train's rehearsal
(`scripts/clean_install_proof.sh`, `OSG_SOURCE=index`) failed on the first
miss instead of tolerating normal index propagation delay. `pip download`
already polled; the two subsequent `pip install` calls (the `[ollama]` and
`[server]` extras) did not, and that is where the real release run failed.

These tests exercise the extracted `pip_retry` bash function directly,
without touching a real index: a fake `pip` on PATH fails a fixed number of
times before succeeding (propagation catches up) or never succeeds at all
(a genuinely unpublished version). `OSG_INDEX_RETRY_DELAY=0` keeps the
never-succeeds case fast without weakening what is proved.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "lib" / "pip_retry.sh"


def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestPipRetryToleratesPropagationDelay:
    def test_it_retries_and_succeeds_once_the_index_catches_up(self, tmp_path: Path) -> None:
        """A command that fails twice, then succeeds, must still exit 0."""
        counter = tmp_path / "attempts"
        counter.write_text("0")
        fake_cmd = tmp_path / "flaky_pip.sh"
        fake_cmd.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                n=$(cat "{counter}")
                n=$((n + 1))
                echo "$n" > "{counter}"
                if [ "$n" -lt 3 ]; then
                  echo "ERROR: Could not find a version that satisfies the requirement" >&2
                  exit 1
                fi
                echo "Successfully installed openstategraph"
                exit 0
                """
            )
        )
        fake_cmd.chmod(0o755)

        result = _run_bash(
            f'source "{LIB}"; '
            f'OSG_INDEX_RETRIES=5 OSG_INDEX_RETRY_DELAY=0 '
            f'pip_retry "openstategraph==0.3.0rc5" "{fake_cmd}"'
        )

        assert result.returncode == 0, result.stderr
        assert counter.read_text().strip() == "3"
        assert "not visible yet" in result.stdout

    def test_removing_the_retry_would_fail_this_case(self, tmp_path: Path) -> None:
        """Guard against a no-op `pip_retry` (e.g. one that runs the command
        once and returns its exit code). Calling the flaky command directly,
        with no retry, must fail on the first attempt — proving the retry in
        the first test is doing real work rather than the fake happening to
        succeed anyway.
        """
        counter = tmp_path / "attempts"
        counter.write_text("0")
        fake_cmd = tmp_path / "flaky_pip.sh"
        fake_cmd.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                n=$(cat "{counter}")
                n=$((n + 1))
                echo "$n" > "{counter}"
                if [ "$n" -lt 3 ]; then
                  exit 1
                fi
                exit 0
                """
            )
        )
        fake_cmd.chmod(0o755)

        result = subprocess.run(
            [str(fake_cmd)], capture_output=True, text=True, timeout=10
        )
        assert result.returncode != 0


class TestPipRetryStillFailsForAGenuinelyUnpublishedVersion:
    def test_a_version_that_never_appears_fails_loudly_after_the_ceiling(
        self, tmp_path: Path
    ) -> None:
        """The retry must not become 'skip if missing' — a command that never
        succeeds must still return non-zero, with a clear message naming the
        thing that was never found."""
        fake_cmd = tmp_path / "always_fails_pip.sh"
        fake_cmd.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                echo "ERROR: Could not find a version that satisfies the requirement" >&2
                exit 1
                """
            )
        )
        fake_cmd.chmod(0o755)

        result = _run_bash(
            f'source "{LIB}"; '
            f'OSG_INDEX_RETRIES=3 OSG_INDEX_RETRY_DELAY=0 '
            f'pip_retry "openstategraph==9.9.9-never-published" "{fake_cmd}"'
        )

        assert result.returncode != 0
        assert "openstategraph==9.9.9-never-published" in result.stderr
        assert "never became available" in result.stderr
        assert "giving up" in result.stderr

    def test_it_gives_up_within_the_stated_attempt_ceiling(self, tmp_path: Path) -> None:
        """Bounded, not infinite: exactly `OSG_INDEX_RETRIES` attempts."""
        counter = tmp_path / "attempts"
        counter.write_text("0")
        fake_cmd = tmp_path / "always_fails_pip.sh"
        fake_cmd.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                n=$(cat "{counter}")
                n=$((n + 1))
                echo "$n" > "{counter}"
                exit 1
                """
            )
        )
        fake_cmd.chmod(0o755)

        result = _run_bash(
            f'source "{LIB}"; '
            f'OSG_INDEX_RETRIES=4 OSG_INDEX_RETRY_DELAY=0 '
            f'pip_retry "never-there" "{fake_cmd}"'
        )

        assert result.returncode != 0
        assert counter.read_text().strip() == "4"


class TestCleanInstallProofUsesTheSharedRetry:
    """`scripts/clean_install_proof.sh` must route every index-mode pip call
    that can race propagation through `pip_retry`, and must not rely on pip's
    local cache surviving a fresh upload."""

    SCRIPT = (REPO_ROOT / "scripts" / "clean_install_proof.sh").read_text()

    def test_it_sources_the_shared_retry_library(self) -> None:
        assert "scripts/lib/pip_retry.sh" in self.SCRIPT

    def test_the_ollama_extra_install_goes_through_pip_retry(self) -> None:
        assert 'pip_retry "openstategraph[ollama]==$OSG_VERSION"' in self.SCRIPT

    def test_the_server_extra_install_goes_through_pip_retry(self) -> None:
        assert 'pip_retry "openstategraph[server]==$OSG_VERSION"' in self.SCRIPT

    def test_index_mode_pip_calls_disable_the_local_cache(self) -> None:
        assert "--no-cache-dir" in self.SCRIPT

    def test_the_syntax_is_still_valid_bash(self) -> None:
        result = subprocess.run(
            ["bash", "-n", str(REPO_ROOT / "scripts" / "clean_install_proof.sh")],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
