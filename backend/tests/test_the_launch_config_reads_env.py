"""`.claude/launch.json` must start the backend through an entry point that reads `.env`.

**The defect this exists to stop, found live on 2026-08-18.** The owner reported
that Ollama "was broken for a reason I don't know why" while the backend was
running on 8000. It was not broken. The backend had been started by
`preview_start {name: "backend"}`, which ran the checked-in launch config:

    python3 -m uvicorn openstategraph.api.main:app --port 8000

That path never reaches `cli.console_main`, which is the **only** place
`load_env_file()` is called — deliberately, because `main()` is a function this
project's own tests call in-process, and a function that rewrites `os.environ`
from disk poisons every test after it. The split is right; the launcher was on
the wrong side of it.

**The symptom is not an error.** Every provider reports `configured: false`,
the editor says "no provider is configured on this server", and workflows run
against mock data — so a wiring bug and a missing credential produce the same
symptom, which is precisely what `CLAUDE.md`'s standing Ollama instruction
exists to prevent. Measured on the day, same machine, same `.env`:

| started with | ANTHROPIC | OPENAI | OLLAMA |
| --- | --- | --- | --- |
| `python3 -m uvicorn ...` | False | False | False |
| `python3 -m openstategraph.cli serve` | True | True | True |

`scripts/dev.sh` has always known: it loads `.env` into the shell itself before
launching uvicorn, in a block whose comment explains why. The launch config had
no equivalent, and nothing compared the two.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _backend() -> dict:
    path = REPO / ".claude" / "launch.json"
    assert path.is_file(), "no .claude/launch.json in this checkout"
    entries = [
        c
        for c in json.loads(path.read_text(encoding="utf-8"))["configurations"]
        if c.get("name") == "backend"
    ]
    assert entries, "launch.json has no `backend` configuration"
    return entries[0]


class TestTheBackendEntryPointLoadsDotEnv:
    def test_it_does_not_invoke_uvicorn_directly(self) -> None:
        argv = " ".join(_backend().get("runtimeArgs", []))
        assert "uvicorn" not in argv, (
            "`python -m uvicorn openstategraph.api.main:app` never calls "
            "`console_main`, so `.env` is never read and every provider silently "
            "reports `configured: false`. Use `-m openstategraph.cli serve`, or "
            "export the file first the way scripts/dev.sh does."
        )

    def test_it_goes_through_the_cli(self) -> None:
        argv = _backend().get("runtimeArgs", [])
        assert "openstategraph.cli" in argv or "openstategraph" in argv
        assert "serve" in argv

    def test_the_cli_module_entry_point_still_reads_the_file(self) -> None:
        # The other half of the pair. If `cli.py`'s `__main__` guard ever goes
        # back to calling `main()`, this launch config is silently broken again
        # while still passing the two assertions above.
        import inspect

        from openstategraph import cli

        after = inspect.getsource(cli).split('if __name__ == "__main__"')[-1]
        guard = "\n".join(
            line
            for line in after.splitlines()[1:]
            if line.startswith((" ", "\t")) or not line.strip()
        )
        assert "console_main()" in guard


class TestTheDevStackAndTheLaunchConfigAgree:
    def test_dev_sh_still_exports_the_file_before_uvicorn(self) -> None:
        """`scripts/dev.sh` may keep using uvicorn — it loads `.env` itself.

        Pinned so that block cannot be tidied away as redundant: it is the only
        thing making the supervised stack see credentials, and deleting it would
        reproduce the same invisible failure one launcher over.
        """
        dev = (REPO / "scripts" / "dev.sh").read_text(encoding="utf-8")
        assert "parse_env_file" in dev
        assert dev.index("parse_env_file") < dev.index(
            "uvicorn openstategraph.api.main:app --port"
        )
