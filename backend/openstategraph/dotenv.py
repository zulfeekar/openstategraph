"""Read a `.env` file into the environment — for programs we launch, only.

`README.md` has always told a developer to put their keys in `.env`. Nothing
read it. So the natural thing produced the worst possible answer:

    $ openstategraph run ./workflows/demo "hi" --model anthropic:claude-opus-5
    MissingProviderKey: Provider "anthropic" has no credential —
      set ANTHROPIC_API_KEY in .env (see .env.example).

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
from pathlib import Path

#: The file name, and the one `README.md` and `.env.example` already name.
ENV_FILE_NAME = ".env"

#: How far up the tree to look. A developer runs the CLI from the project root
#: or from a subdirectory of it; beyond a few levels we would be reading a file
#: that belongs to something else entirely.
_MAX_PARENTS = 4


def find_env_file(start: Path | str | None = None) -> Path | None:
    """The nearest `.env` at or above `start`, or None.

    Walks up rather than requiring the exact directory, because `openstategraph
    run ./workflows/demo` is as likely to be typed from a subdirectory as from
    the root.
    """
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *list(here.parents)[:_MAX_PARENTS]):
        candidate = directory / ENV_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


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


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=value` lines, minus comments, blanks and shell decoration.

    Deliberately small. `export FOO=bar` is accepted because people paste it
    from a shell; surrounding quotes are stripped because people copy them from
    documentation; a trailing `# note` is dropped because people annotate their
    own files. Anything more elaborate — variable interpolation, multi-line
    values, escape sequences — is a sign the file wants a real parser, and at
    that point `python-dotenv` is the honest answer rather than growing this
    one.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = _strip_inline_comment(value.strip()).rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(start: Path | str | None = None) -> Path | None:
    """Populate `os.environ` from the nearest `.env`; return the file used.

    Never overwrites a variable that is already set — see the module docstring:
    the real environment is the authority and this is the fallback.

    Returns `None` when there is no file, which is the common case and is not a
    problem: a deployment that exports its variables properly needs no `.env`
    at all.
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
    for key, value in parse_env_file(text).items():
        os.environ.setdefault(key, value)
    return path


__all__ = ["ENV_FILE_NAME", "find_env_file", "load_env_file", "parse_env_file"]
