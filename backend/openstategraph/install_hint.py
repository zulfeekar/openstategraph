"""The one place a missing extra becomes a command somebody can actually run.

`osg-agent-experience/79`. Every refusal that named a missing optional
dependency printed the same shape — *"Install the extra: pip install
'openstategraph[mssql]'"* — and on the installation it was measured against
(2026-09-06, the try project's `0.3.0rc15`) that line failed twice over:

- `openstategraph` is a **pre-release on TestPyPI**, so a bare `pip install`
  resolves nothing at all — `uvx --from 'openstategraph[mssql]==0.3.0rc15'`
  answered *"there is no version of openstategraph[mssql]==0.3.0rc15"*.
- the interpreter was a **`uv tool` install**, which `pip` does not manage.

And the obvious repair was worse than the message. `uv tool install --force
'openstategraph[mssql]'` **replaces** the tool environment with exactly what
the command names, so it dropped `[server]` and the next `openstategraph .`
refused to start for want of uvicorn. One missing extra became two.

So a runnable remedy needs three facts, none of which can be guessed from the
name of the extra:

1. **How this interpreter was installed** — a `uv` tools directory, a virtual
   environment, or neither. `detect_installation()`.
2. **Which extras are already present**, because a `--force` reinstall carries
   only what it is told. `installed_extras()`, probed with `find_spec` so
   nothing heavy is imported to answer a question about an error message.
   This one is read for the `uv tool` shape only, and that is a decision
   rather than an omission: `pip install` is additive — it uninstalls
   nothing — so a pip line naming nine extras to repair one would be a
   sentence implying all nine are needed.
3. **Whether the version is a pre-release**, which is the whole reason the
   TestPyPI index flags exist — and the reason they must disappear the day it
   is not. The README says the same thing in prose; the flags are pinned
   against that block by a test rather than copied beside it.

**This module owns the sentence, and it is the only one that may.** The defect
was two spellings of one install line drifting apart, so
`test_the_install_hint_can_be_carried_out.py` fails on any other module that
composes one.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "EXTRA_MARKERS",
    "Installation",
    "detect_installation",
    "documented_install_hint",
    "install_hint",
    "installed_extras",
    "is_pre_release",
]

#: One extra, and the modules whose presence proves it is installed. Probed,
#: never imported: `find_spec` reads metadata, so asking "is the ODBC driver
#: here" costs nothing and cannot itself raise the error we are explaining.
#:
#: **The single table.** The warehouse leaves' `DRIVER_MODULES` are rows of it
#: rather than second copies — two spellings of "what makes `[mssql]` present"
#: is the drift this module exists to end. Every key is an extra
#: `pyproject.toml` declares, asserted from the file.
EXTRA_MARKERS: dict[str, tuple[str, ...]] = {
    "anthropic": ("langchain_anthropic",),
    "openai": ("langchain_openai",),
    "ollama": ("langchain_ollama",),
    "deep": ("deepagents",),
    # `msal` rides the same extra as the driver (`73`) and both are lazy, so
    # either one absent means the extra is not fully here.
    "mssql": ("pyodbc", "msal"),
    "databricks": ("databricks.sql",),
    "sqlite": ("langgraph.checkpoint.sqlite",),
    "server": ("fastapi", "uvicorn"),
    "mcp": ("mcp", "langchain_mcp_adapters"),
    "postgres": ("langgraph.checkpoint.postgres", "psycopg"),
    "bastion": ("bastion_prompt_protection",),
}

#: TestPyPI, and the two indexes `uv` must be told it may mix. Rendered only
#: for a pre-release: they are the cost of one, not a property of the project,
#: and the README's install block says so in the same words.
_INDEX_FLAGS = (
    "--index-url https://test.pypi.org/simple/",
    "--extra-index-url https://pypi.org/simple/",
)

#: `uv`'s alone — `pip` has no such flag, so a pip line that carried it would
#: fail on the flag rather than on the resolve.
_UV_ONLY_FLAGS = ("--index-strategy unsafe-best-match",)

#: A PEP 440 pre-release tail: `0.3.0rc15`, `1.0.0b2`, `2.0.0.dev3`.
_PRE_RELEASE = re.compile(r"(?:a|b|rc|dev)\d*$", re.I)


def is_pre_release(version: str) -> bool:
    """True when pip and `uv` would skip this version unless it is named exactly."""
    return bool(_PRE_RELEASE.search((version or "").strip()))


@dataclass(frozen=True)
class Installation:
    """What this interpreter is, as far as an install command is concerned.

    A value rather than a lookup so the caller can be told: the tests drive
    every shape without needing three machines, and a future surface that
    knows better than we do (a container image, say) can say so.
    """

    #: `uv-tool`, `venv` or `pip-user`.
    shape: str
    version: str
    #: The extras already present, sorted.
    extras: tuple[str, ...] = ()


def detect_installation() -> Installation:
    """This interpreter's shape, version and extras — read, not configured.

    `uv tool install` puts the environment under its own `uv/tools` directory,
    which is the only durable signal it leaves in `sys.prefix`; a virtual
    environment is the standard `sys.prefix != sys.base_prefix`; anything else
    is the interpreter itself, where `--user` is the install that does not need
    a root password.
    """
    parts = Path(sys.prefix).parts
    if any(
        parts[index] == "uv" and parts[index + 1] == "tools"
        for index in range(len(parts) - 1)
    ):
        shape = "uv-tool"
    elif sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        shape = "venv"
    else:
        shape = "pip-user"
    return Installation(shape=shape, version=_version(), extras=installed_extras())


def installed_extras() -> tuple[str, ...]:
    """Every extra whose marker modules are all importable, sorted.

    `find_spec` rather than `import_module`: this is asked while composing an
    error message, and importing a provider SDK to discover it is absent is a
    cost paid on the unhappy path by every caller.
    """
    return tuple(
        sorted(
            extra
            for extra, markers in EXTRA_MARKERS.items()
            if all(_importable(module) for module in markers)
        )
    )


def _importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):  # a parent package that is itself absent
        return False


def _version() -> str:
    from openstategraph import __version__

    return str(__version__)


def install_hint(extra: str, *, installation: Installation | None = None) -> str:
    """The exact command that adds `extra` **without losing what is already here**.

    `extra` is a name (`mssql`) or the bracketed spelling a refusal already
    held (`openstategraph[mssql]`); both answer the same, because the constants
    that name a leaf's extra are public and were not worth renaming to fix a
    sentence.
    """
    name = _extra_name(extra)
    here = installation or detect_installation()
    pinned = is_pre_release(here.version)

    if here.shape == "uv-tool":
        # `uv tool install --force` **replaces** the tool environment with
        # exactly what the command names, which is how repairing `[mssql]` cost
        # the owner `[server]` and turned one missing extra into two. So this is
        # the one shape that must carry the union.
        wanted = ",".join(sorted({*here.extras, name} - {""}))
        command = ["uv", "tool", "install", "--force"]
        flags = [*_INDEX_FLAGS, *_UV_ONLY_FLAGS] if pinned else []
    else:
        # `pip install` is additive: it never uninstalls what it was not asked
        # about, so naming the union here would be noise at best and, at worst,
        # a sentence implying nine extras are required to fix one.
        wanted = name
        command = ["pip", "install"] + (["--user"] if here.shape == "pip-user" else [])
        flags = list(_INDEX_FLAGS) if pinned else []

    spec = f"openstategraph[{wanted}]" + (f"=={here.version}" if pinned else "")
    return " ".join([*command, *flags, f"'{spec}'"])


def _extra_name(extra: str) -> str:
    """`openstategraph[mssql]` and `mssql` both mean `mssql`."""
    match = re.search(r"\[([^\]]+)\]", extra or "")
    return (match.group(1) if match else (extra or "")).strip()


def documented_install_hint(extras: str) -> str:
    """The generic line, for a file somebody else reads on a machine we cannot see.

    **The distinction `install_hint` forces, stated rather than discovered.**
    That function answers *"how do I repair the interpreter I am standing
    in"*, and its answer is specific to this machine — a `uv tool` command, or
    a `--user` pip, with the flags a pre-release needs. Written into an
    exported package's README (`plugin_interop`), that answer would be a
    confident instruction about a computer we have never seen: the reader's
    install shape is not ours, and by the time they read it the version may
    not be either.

    So a document gets the plain, portable line, and the machine-specific one
    stays where the machine is known. `extras` is the comma-joined list the
    document actually needs — a README may honestly ask for several at once,
    where a refusal is always about the one thing that just failed.
    """
    return f"pip install 'openstategraph[{extras}]'"
