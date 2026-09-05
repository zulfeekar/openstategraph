"""Read a `.env` file into the environment — for programs we launch, only.

`README.md` has always told a developer to put their keys in `.env`. Nothing
read it. So the natural thing produced the worst possible answer:

    $ openstategraph run ./workflows/demo "hi" --model anthropic:claude-opus-5
    MissingProviderKey: Provider "anthropic" has no credential —
      set ANTHROPIC_API_KEY in .env (see `openstategraph env-example`).

A closed loop: the error names the action the user has already taken. Good copy
pointing at a mechanism that did not exist.

**Where this is called, and where it deliberately is not.** Environment
variables are the mechanism; a `.env` file is a convenience that *populates*
them, and someone has to do the populating. It happens in exactly one place:
`cli.console_main`, the `[project.scripts]` entry point — a **process** the
user launched.

`create_app` and `cli.main` were both tried and both reverted, because a
*function* anyone may call must not rewrite the process it is called in:
`create_app` mutated the environment on every app construction including the
hundreds in the test suite, and `main` is called in-process by tests, which
poisoned every test that ran after it. `load_workflow` is the same objection at
library scope — importing a library must not reach into the host application's
process and rewrite its environment from a file on disk. That is the split
LangChain and LangGraph draw: the libraries read `os.environ` and never load a
file; their CLI does.

**The real environment always wins.** A variable already set is never
overwritten, so `ANTHROPIC_API_KEY=… openstategraph run …` beats the file, a
container's injected secret beats a stale `.env` left in the image, and CI
never has to delete a file to override it. `.env` is the fallback, not the
authority.

**No new dependency.** `python-dotenv` is the obvious reach, and the format we
need is `KEY=value` — a dozen lines. The core is four packages and that is an
advertised property of this distribution; spending it here would buy quoting
edge cases nobody has asked for.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

#: The file name, and the one `README.md` and `.env.example` already name.
ENV_FILE_NAME = ".env"


def find_env_file(start: Path | str | None = None) -> Path | None:
    """The nearest `.env` in the project holding `start`, or None.

    **The same directories `openstategraph.yaml` is looked for in**, asked of
    `config_file.project_search_path` rather than walked again here: nearest
    first, stopping at the git root, which is what "my project" means.

    Until `osg-agent-experience/47` this walked four parents of the working
    directory and no further, so the two walks disagreed for any project
    deeper than that — `workflows/<slug>/tools/` is already three — and the
    disagreement is silent in the worst direction: the config is found, the
    `.env` beside it is not, and every provider reports "needs a key" while
    the key sits in the file the error names.
    """
    from openstategraph.config_file import project_search_path

    for directory in project_search_path(start):
        candidate = directory / ENV_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class ScannedEnv:
    """What one `.env` file says, and which of its lines said nothing.

    `malformed` holds **line numbers, never text**. A line in a credentials
    file is a credential until proven otherwise, and a warning is the one
    thing here that gets pasted into a support thread.
    """

    values: dict[str, str]
    malformed: tuple[int, ...]


def _strip_inline_comment(value: str) -> str:
    """Drop a trailing `# note`, leaving `#` that is part of the value alone.

    Two rules, and each earns its place against a line someone really wrote:

    - **A quoted value ends at its closing quote.** Everything after it is
      commentary. This is what makes `KEY = "https://…"  # adjust` work, and
      it is also what protects a `#` *inside* the quotes.
    - **Unquoted, a comment must be preceded by whitespace.** A credential may
      legitimately contain a `#`, so cutting at every one of them would corrupt
      far more values than it would tidy.
    """
    if value[:1] in ('"', "'"):
        closing = value.find(value[0], 1)
        if closing != -1:
            return value[: closing + 1]
        # An unbalanced quote is a typo we cannot repair; leave it whole so the
        # value looks wrong rather than quietly becoming something shorter.
        return value
    for index in range(1, len(value)):
        if value[index] == "#" and value[index - 1].isspace():
            return value[:index]
    return value


def scan_env_file(text: str) -> ScannedEnv:
    """`KEY=value` lines, minus comments, blanks and shell decoration — plus
    the numbers of the lines that were none of those.

    Deliberately small. `export FOO=bar` is accepted because people paste it
    from a shell; surrounding quotes are stripped because people copy them from
    documentation; a trailing `# note` is dropped because people annotate their
    own files. Anything more elaborate — variable interpolation, multi-line
    values, escape sequences — is a sign the file wants a real parser, and at
    that point `python-dotenv` is the honest answer rather than growing this
    one. `osg-agent-experience/47` re-priced that dependency against
    `docs/wheel-footprint.json` and kept the parser: the base wheel advertises
    four dependencies, and a fifth buys quoting edge cases nobody has asked
    for.

    **A value is taken exactly as it stands.** `DSN=host=db;user=a{b}c` is a
    line a shell's `source` chokes on, which is how a developer arrives here
    believing their file is broken; it is not, and nothing about it is
    rewritten.

    A line with no `=` at all is the only thing skipped, and it is counted so
    the caller can say which line — see `ScannedEnv`.
    """
    values: dict[str, str] = {}
    malformed: list[int] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            malformed.append(number)
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            malformed.append(number)
            continue
        value = _strip_inline_comment(value.strip()).rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return ScannedEnv(values, tuple(malformed))


def parse_env_file(text: str) -> dict[str, str]:
    """The values alone. See `scan_env_file`, which is the one implementation."""
    return scan_env_file(text).values


def load_env_file(start: Path | str | None = None) -> Path | None:
    """Populate `os.environ` from the nearest `.env`; return the file used.

    Never overwrites a variable that is already set — see the module docstring:
    the real environment is the authority and this is the fallback.

    Returns `None` when there is no file, which is the common case and is not a
    problem: a deployment that exports its variables properly needs no `.env`
    at all.

    A line that is not `KEY=value` is skipped **and said out loud**, on stderr,
    **by number only** (`osg-agent-experience/47`). Silence there is how a
    typo'd key becomes a provider that reports "needs a key" for the rest of
    the project's life; the content of the line stays unprinted because this is
    the file that holds the credentials.
    """
    path = find_env_file(start)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        # An unreadable `.env` must not stop a run that may not need it. The
        # missing credential will say so itself, in its own words.
        return None
    scanned = scan_env_file(text)
    for key, value in scanned.values.items():
        os.environ.setdefault(key, value)
    for number in scanned.malformed:
        print(
            f"warning: {path} line {number} is not KEY=value — skipped.",
            file=sys.stderr,
        )
    return path


def environment_line(start: Path | str | None = None) -> str:
    """One line for `startup_facts()`: whether a `.env` was read, and how many.

    **The count, never the names.** A variable name out of a credentials file
    is already half of what nobody should paste into an issue, and the number
    answers the question a reader actually has — *did my key reach this
    process* — which nothing at startup answered before.

    Derived on the spot rather than recorded at load time, and that is the
    honest shape here rather than a shortcut: `startup_facts()` has exactly one
    production caller, `cmd_serve`, reached only through `cli.console_main`,
    which loaded this same file moments earlier by this same walk. A recorded
    fact would be process-global mutable state — the thing `workflows_root`
    refuses in as many words — bought for nothing.

    An unreadable file reports `no .env` for the same reason `load_env_file`
    returns `None` for one: nothing from it reached this process.
    """
    path = find_env_file(start)
    if path is None:
        return "no .env"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "no .env"
    count = len(scan_env_file(text).values)
    return f".env: read, {count} variable{'' if count == 1 else 's'}"


def environment_source_note(*, loaded: bool, start: Path | str | None = None) -> str:
    """One sentence naming the `.env` nearest this process — the fact
    `providers-and-credentials/13` found two surfaces answering without.

    `openstategraph providers` (`loaded=True`) actually populated
    `os.environ` from this file, via `cli.console_main` before this command
    ran. `/api/providers` (`loaded=False`) never does — `create_app` does not
    call `load_env_file`, for the reason this module's own docstring gives —
    so a nearby file may or may not be the source of this process's
    environment; that depends entirely on how the server was *started*
    (`openstategraph serve` loads it the same way the CLI does; a bare
    `uvicorn` line does not, unless something else exported the variables
    first).

    Both callers name the same file so a reader can tell whether the two
    answers describe one environment or two.
    """
    path = find_env_file(start)
    if path is None:
        return "No .env file was found near this process."
    if loaded:
        return (
            f".env: {path} (read) — a server started outside `openstategraph providers` "
            "or `openstategraph serve` does not read it automatically."
        )
    return (
        f".env: {path} — found nearby, but this server does not read it itself. It only "
        "reaches this process if something loaded it before startup, such as "
        "`openstategraph serve` or `scripts/dev.sh`; a bare `uvicorn` line does not."
    )


__all__ = [
    "ENV_FILE_NAME",
    "ScannedEnv",
    "environment_line",
    "environment_source_note",
    "find_env_file",
    "load_env_file",
    "parse_env_file",
    "scan_env_file",
]
