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
them, and someone has to do the populating. We do it in the two places the user
launched a process of ours — the CLI, and `create_app` for a directly-run
server. We do **not** do it in `load_workflow`: importing a library must not
reach into the host application's process and rewrite its environment from a
file on disk. That is the same split LangChain and LangGraph draw — the
libraries read `os.environ` and never load a file; their CLI does.

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


def parse_env_file(text: str) -> dict[str, str]:
    """`KEY=value` lines, minus comments, blanks and shell decoration.

    Deliberately small. `export FOO=bar` is accepted because people paste it
    from a shell; surrounding quotes are stripped because people copy them from
    documentation. Anything more elaborate is a sign the file wants a real
    parser, and at that point `python-dotenv` is the honest answer rather than
    growing this one.
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
        value = value.strip()
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
