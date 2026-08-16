"""`openstategraph.yaml` — versioned config a human or a coding agent edits.

Ticket 03. What belongs here: which providers exist, what their models are,
which is the default, and — since scale-and-adopt ticket 02 — where the
workflow packages live (`workflows_dir:`). What can never be here: a
credential. The file **may** name the environment variable that holds one,
which is the useful half of a secret without being a secret.

**Why YAML, given the lean-core rule.** The rule is about *distributions*, and
YAML costs none: `PyYAML` is already a transitive dependency of
`langchain-core`, one of the four dependencies the lean core is made of
(`pip show langchain-core` → `Requires: … pyyaml …`). So the honest comparison
is not "a dependency versus none" but "comments versus no comments", and this
is a file whose entire purpose is to be read and edited by a human or an agent:
it needs to say *why* a provider is pinned and *which* env var holds its key,
next to the line it applies to. JSON cannot carry a comment, so every "why"
would have to live somewhere else and rot separately. `openstategraph.json` is
accepted all the same — `json` is stdlib, and nobody should be forced into YAML
to use this.

**Two carriers, one reader.** The dedicated file is the canonical one;
`pyproject.toml [tool.openstategraph]` carries the same schema for a project
that would rather not add a file. They are found by one upward walk from the
working directory to the git root — see `find_config_file` — and parsed by one
`load_config`, so there is no second reader anywhere and no second precedence
rule to disagree with this one.

**Secrets are excluded by construction, not by convention.** Two independent
rules, because either alone is insufficient:

- a *field name* on the secret denylist is refused (`api_key`, `token`, …),
  which stops the obvious mistake;
- a *value* shaped like a credential is refused wherever it appears, which
  stops the subtle one — `api_key_env: sk-ant-…` has an innocent field name and
  a live secret in it.

Both errors name `.env` as the place it belongs, because a rejection that does
not say where to put it instead just gets worked around.

**Precedence**, lowest to highest, and each adjacent pair is pinned in
`tests/test_config_file.py::TestPrecedence`:

    instance default  <  this file  <  workflow settings.model  <  node's own
    model  <  caller's `model=` argument

**The environment is not one rung of that ladder, and that is the subtlety.**
It enters in two different roles, which used to be conflated:

- A **credential** (`ANTHROPIC_API_KEY`) is a fact about what this machine
  has. It feeds the *instance default* — `ProviderCatalogue.elected_default`
  elects among the integrations that are installed — and it sits at the
  bottom, below `default_model:` here. Until install-experience T4 it sat
  above, so exporting a key for an unrelated tool silently moved every run off
  the model this file names. A credential is not a request.
- A **direction** (`OPENSTATEGRAPH_WORKFLOWS_ROOT`,
  `OPENSTATEGRAPH_<PROVIDER>_MODEL`) says what to do, and still beats this
  file, for the reason it always did: the file is committed and shared, while
  the environment is the machine in front of you. A colleague's committed
  default must never silently outrank a choice you made for your own run.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

#: Accepted names, in search order. YAML first — see the module docstring.
#:
#: `pyproject.toml` is deliberately **not** in this tuple, and is consulted
#: after it — see `PYPROJECT_FILENAME`.
CONFIG_FILENAMES = ("openstategraph.yaml", "openstategraph.yml", "openstategraph.json")

#: `pyproject.toml [tool.openstategraph]` — a first-class carrier, and the
#: *last* one consulted in a directory. The full order is
#: `CLI flag > environment > openstategraph.yaml > pyproject.toml`: a project
#: with both should get the dedicated file, and the `[tool.…]` table is for a
#: project that would rather not add one.
#:
#: It is not another entry in `CONFIG_FILENAMES` because it is not another
#: name for the same thing — the table has to be *found inside* the file, and a
#: `pyproject.toml` with no `[tool.openstategraph]` in it is not a config file
#: at all. Treating it as one would give every Python project an empty config
#: that shadows the real one an ancestor directory holds.
PYPROJECT_FILENAME = "pyproject.toml"

#: The table this project owns inside `pyproject.toml`.
PYPROJECT_TABLE = "openstategraph"

#: Points at a config file directly, wherever it lives.
CONFIG_ENV_VAR = "OPENSTATEGRAPH_CONFIG"

#: The only schema version this release understands.
SUPPORTED_VERSION = 1

#: Field names that may never appear, whatever their value. Matched **exactly**,
#: never as a substring: `api_key_env` contains "key" and is the one spelling
#: this file exists to encourage.
SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "api_secret",
        "access_key",
        "secret_key",
        "key",
        "keys",
        "token",
        "auth_token",
        "access_token",
        "secret",
        "password",
        "passwd",
        "credential",
        "credentials",
    }
)

#: Value prefixes that are unambiguously credentials. Deliberately a
#: prefix list rather than an entropy heuristic: a model id is long and opaque
#: too (`nvidia:meta/llama-3.3-70b-instruct`), and a false positive here means
#: refusing to load a legitimate file, which is worse than the narrower net.
SECRET_VALUE_PREFIXES = (
    "sk-",
    "sk_",
    "pk-",
    "ghp_",
    "gho_",
    "github_pat_",
    "gsk_",
    "xai-",
    "hf_",
    "r8_",
    "AIza",
    "ya29.",
    "Bearer ",
    "AKIA",
)


class ConfigError(Exception):
    """A config file that cannot be trusted, explained well enough to fix.

    Always names the file. Names the field path where the schema knows one, and
    the line where the parser knows one — a message that says only "invalid
    config" makes a human open the file and guess.
    """


def looks_like_a_secret(value: object) -> bool:
    """Whether a value is recognisably a credential.

    Public because `.env.example` is checked with it too: a file whose whole
    job is to list variable *names* must be provably free of variable *values*.
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    return any(text.startswith(prefix) for prefix in SECRET_VALUE_PREFIXES)


def _reject_secrets(node: Any, path: str, source: Path) -> None:
    """Walks the parsed document refusing anything that carries a secret.

    Runs on the **raw** structure, before schema validation, so the message is
    about the secret rather than about an unknown field — "remove `api_key`"
    is actionable; "extra inputs are not permitted" is not.
    """
    if isinstance(node, dict):
        for raw_key, value in node.items():
            key = str(raw_key)
            where = f"{path}.{key}" if path else key
            if key.strip().lower() in SECRET_FIELD_NAMES:
                raise ConfigError(
                    f"{source}: field {where!r} must not exist — this file is committed, "
                    f"so it can never hold a credential. Put the value in .env and name "
                    f"the variable here instead (for example: api_key_env: MY_API_KEY). "
                    f"See .env.example."
                )
            _reject_secrets(value, where, source)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_secrets(value, f"{path}.{index}", source)
    elif looks_like_a_secret(node):
        raise ConfigError(
            f"{source}: the value of {path!r} looks like a credential. This file is "
            f"committed and must never contain one — move it to .env and name the "
            f"variable here instead. See .env.example."
        )


class ProviderConfig(BaseModel):
    """One provider, as a config file may declare it.

    A superset of what a built-in needs and a subset of `ProviderSpec`: the
    file can introduce a provider outright or adjust one that already exists,
    and every field it omits is inherited rather than blanked.
    """

    model_config = ConfigDict(extra="forbid")

    #: The `init_chat_model` prefix — the `anthropic` in `anthropic:claude-…`.
    name: str
    #: Bare model id used when this provider is chosen with nothing more
    #: specific asked for.
    default_model: str | None = None
    #: The `pip install 'openstategraph[…]'` extra supplying its integration.
    extra: str | None = None
    #: The environment variable holding this provider's key. **The name, never
    #: the value** — that is the entire point of this field.
    api_key_env: str | None = None
    #: Human-facing name for messages and the credentials dialog.
    label: str | None = None


class McpAuthConfig(BaseModel):
    """How one MCP server is authenticated, as a committed file may say it.

    `token_env` is a variable **name**. Nothing here can hold a value: the
    raw-document walk above refuses a key-shaped field name and a key-shaped
    value before this schema is ever reached, and `config_mcp_servers` refuses
    a `token_env` that is not a plain environment-variable name — which is the
    shape a pasted credential takes.
    """

    model_config = ConfigDict(extra="forbid")

    #: `none` · `bearer` · `header`. OAuth is deliberately absent: `httpx.Auth`
    #: is a Python object, and portability guardrail 1 forbids host-language
    #: code in a document. It is a fourth value later, with no format change.
    kind: str = "none"
    #: `header` only — the vendor's own header, e.g. `LANGSMITH-API-KEY`.
    header_name: str | None = None
    #: **The name, never the value.** That is the entire point of this field.
    token_env: str | None = None


class McpServerConfig(BaseModel):
    """One MCP server this project can bind, by name, from any workflow.

    The definition lives here rather than in `workflow.json` so a document
    stays shareable: a document **names** a server, and the project says what
    that name reaches. Copy a package to a colleague and they supply their own
    URL and their own credential without editing the canvas.
    """

    model_config = ConfigDict(extra="forbid")

    #: What a `tool.mcp` card names. Also how a project shadows a built-in
    #: default — same name, project wins.
    name: str
    url: str
    #: `streamable_http` (the default) or `sse`. WebSocket cannot carry a
    #: header and stdio names an executable; neither is offered.
    transport: str = "streamable_http"
    auth: McpAuthConfig = McpAuthConfig()
    #: `false` removes the server this entry names — including a built-in
    #: default, which no file declares and which therefore cannot be removed
    #: by deleting a line. A tombstone rather than a hidden Delete button: the
    #: decision is recorded where a colleague reading the file can see it, and
    #: undoing it is deleting one line.
    enabled: bool = True


class OpenStateGraphConfig(BaseModel):
    """The file's whole schema. `extra="forbid"` is the anti-typo rule.

    A config key that is silently ignored is worse than one that is rejected:
    the developer believes they configured something, and the behaviour they
    get is the default, with nothing anywhere to tell them otherwise.
    """

    model_config = ConfigDict(extra="forbid")

    #: Schema version. Present so a future change can migrate rather than guess.
    version: int = SUPPORTED_VERSION
    #: The fallback `provider:model` when the environment names no provider.
    default_model: str | None = None
    #: Where `<slug>/workflow.json` packages live, when it is not `./workflows`.
    #: **Relative to this file**, never to the working directory — see
    #: `configured_workflows_dir`.
    workflows_dir: str | None = None
    providers: list[ProviderConfig] = []
    #: MCP servers a `tool.mcp` node may name. Layered **over** the two
    #: built-in defaults by name, never instead of them: a project that adds
    #: one server has not asked to lose the LangChain documentation.
    mcp_servers: list[McpServerConfig] = []


def _pyproject_table(source: Path) -> Any | None:
    """`[tool.openstategraph]` out of a `pyproject.toml`, or `None`.

    `None` for a file that does not declare us **and** for a file that cannot
    be parsed: discovery has to read the file to know whether it is a carrier
    at all, and an ancestor's broken `pyproject.toml` is not ours to refuse to
    start over. Once the file *is* chosen, `load_config` parses it again and a
    syntax error there is reported normally — the difference is whether we were
    ever asked.
    """
    try:
        import tomllib

        with source.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tool = data.get("tool")
    if not isinstance(tool, dict) or PYPROJECT_TABLE not in tool:
        return None
    return tool[PYPROJECT_TABLE]


def _carrier_in(directory: Path) -> Path | None:
    """The config file this one directory holds, dedicated name first."""
    for name in CONFIG_FILENAMES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    pyproject = directory / PYPROJECT_FILENAME
    if pyproject.is_file() and _pyproject_table(pyproject) is not None:
        return pyproject
    return None


def _search_path(base: Path) -> list[Path]:
    """`base` and each parent, stopping **at** the git root — inclusive.

    The git root is what "my project" means, and it is the bound that cannot
    pick up a stray `openstategraph.yaml` in `$HOME` and apply it to every
    project on the machine (design collision C6). In a directory that is not a
    git repository the walk runs to the filesystem root, which is the only
    other honest answer: there is nothing else to ask.
    """
    directories: list[Path] = []
    for directory in (base, *base.parents):
        directories.append(directory)
        if (directory / ".git").exists():
            break
    return directories


def find_config_file(root: Path | str | None = None) -> Path | None:
    """The config file to use, or `None` — which is the normal case.

    `OPENSTATEGRAPH_CONFIG` wins over the search, so a deployment can point at
    a file outside the project without moving it.

    Otherwise the search **walks upward** from `root` (default: the working
    directory) to the git root, and the first directory holding any carrier
    wins — the dedicated file if that directory has one, else its
    `pyproject.toml [tool.openstategraph]`. One walk, so "nearest project wins"
    is one rule rather than two that can disagree: a nearer `pyproject.toml`
    beats a further `openstategraph.yaml`, because it is a nearer project.

    Before install-experience T7 this looked in `Path.cwd()` only, so after
    `init my_demo` a developer who did the obvious next thing — `cd
    my_demo/workflows/starter` — had their own config silently invisible.
    """
    explicit = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None

    base = Path(root).expanduser() if root is not None else Path.cwd()
    if not base.is_absolute():
        base = Path.cwd() / base
    for directory in _search_path(base):
        found = _carrier_in(directory)
        if found is not None:
            return found
    return None


def _parse(source: Path) -> Any:
    """Text to a plain structure, with a parse error that names file and line."""
    if source.suffix.lower() == ".toml":
        # A `pyproject.toml` belongs to the project, not to us: everything
        # outside `[tool.openstategraph]` is somebody else's, and the schema
        # below would refuse all of it as unknown fields. So the *table* is the
        # document, and the rest of this module never learns the difference.
        import tomllib

        try:
            with source.open("rb") as handle:
                data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{source}: invalid TOML: {exc}") from exc
        table = data.get("tool", {}).get(PYPROJECT_TABLE) if isinstance(data, dict) else None
        if table is None:
            raise ConfigError(
                f"{source}: no [tool.{PYPROJECT_TABLE}] table — that is the only part of a "
                f"pyproject.toml this project reads."
            )
        return table

    text = source.read_text()
    if source.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{source}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - PyYAML arrives with langchain-core
        raise ConfigError(
            f"{source}: reading a YAML config needs PyYAML — pip install pyyaml, "
            f"or rename the file to openstategraph.json."
        ) from exc

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise ConfigError(f"{source}: invalid YAML{where}: {problem}") from exc


def _describe(error: Mapping[str, Any]) -> str:
    """One pydantic error as a line naming the field path.

    `Mapping`, not `dict`: pydantic hands back `ErrorDetails`, a TypedDict,
    and only the read side is used here.
    """
    location = ".".join(str(part) for part in error.get("loc", ())) or "(root)"
    message = error.get("msg", "is invalid")
    if error.get("type") == "extra_forbidden":
        return f"{location}: unknown field — remove it or correct the spelling"
    return f"{location}: {message}"


def load_config(source: Path | str) -> OpenStateGraphConfig:
    """Parses and validates one config file, or raises `ConfigError`."""
    path = Path(source)
    raw = _parse(path)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: the top level must be a mapping, not a {type(raw).__name__}")

    # Before the schema: a secret must be reported as a secret, not as an
    # unknown field. `extra="forbid"` would otherwise catch `api_key` first and
    # give a message that entirely misses the point.
    _reject_secrets(raw, "", path)

    declared = raw.get("version", SUPPORTED_VERSION)
    if isinstance(declared, int) and declared != SUPPORTED_VERSION:
        raise ConfigError(
            f"{path}: version {declared} is not supported by this release, which "
            f"understands version {SUPPORTED_VERSION}."
        )

    try:
        return OpenStateGraphConfig.model_validate(raw)
    except ValidationError as exc:
        details = "; ".join(_describe(error) for error in exc.errors())
        raise ConfigError(f"{path}: {details}") from exc


# --------------------------------------------------------------------- #
# The ambient config
# --------------------------------------------------------------------- #

_ACTIVE: OpenStateGraphConfig | None = None
_LOADED = False


def active_config() -> OpenStateGraphConfig | None:
    """The config file in effect, loaded once.

    Memoised because `resolve_model` is on the path of every run. A malformed
    file raises here rather than being ignored: silently continuing with
    defaults is how a developer ends up debugging a model choice they believe
    they already made.
    """
    global _ACTIVE, _LOADED
    if not _LOADED:
        path = find_config_file()
        _ACTIVE = load_config(path) if path is not None else None
        _LOADED = True
    return _ACTIVE


def reset_active_config() -> None:
    """Drops the memoised config. For tests and for a reload."""
    global _ACTIVE, _LOADED
    _ACTIVE = None
    _LOADED = False


def configured_workflows_dir() -> Path | None:
    """The file's `workflows_dir:`, resolved, or `None` — the normal case.

    **A relative value is relative to the config file, not to the working
    directory.** The file is committed and shared; the working directory is
    wherever the process happened to be started from. Resolving against the cwd
    would make one committed line mean a different directory per developer, and
    mean a *different* directory again when the same service is started from
    `/` by a supervisor — which is the class of bug `workflows_root` exists to
    have already fixed once.

    One layer of `openstategraph.workflows_root`'s precedence chain, and it
    lives here rather than there because the parsing, the validation and the
    "which file was it" answer are all this module's.
    """
    config = active_config()
    if config is None or not (config.workflows_dir or "").strip():
        return None
    source = find_config_file()
    base = source.parent if source is not None else Path.cwd()
    return (base / Path(config.workflows_dir or "").expanduser()).expanduser().resolve()


def render_config_file(
    *, workflows_dir: str = "workflows", default_model: str | None = None
) -> str:
    """The `openstategraph.yaml` `openstategraph init` writes (T6).

    **Commented, by the owner's decision.** The generated file is the first
    thing a person opens in a project they just made, and a bare `version: 1`
    teaches nothing about what may go in it — while a comment that sits beside
    the line it explains is the entire reason this file is YAML rather than
    JSON (see the module docstring).

    **`default_model:` is written commented out, and that is the substance
    rather than a formatting choice.** An uncommented pin would make the new
    project's first run depend on this machine's installed integration
    *forever*, which is exactly the inference-outranks-intent defect T4 removed
    one rung further up. Omitted, the project inherits the instance default —
    the provider integration you installed — which is what makes
    `pip install 'openstategraph[anthropic]'` mean "Anthropic is my default".
    The elected model is named in the comment so uncommenting it is one edit.

    **No credential can appear here**, and not by care: nothing in this
    function reads one. `default_model` is a model id and `workflows_dir` is a
    path. `tests/test_init_project.py` runs `looks_like_a_secret` over every
    line it produces.
    """
    example = default_model or "anthropic:claude-haiku-4-5"
    return f"""\
# OpenStateGraph — this project's committed configuration.
#
# ---------------------------------------------------------------------------
# NO SECRETS. EVER. This file is committed, so a key here is a leaked key.
# The loader does not merely discourage that — it REFUSES to load a file
# containing a key-shaped field name (api_key, token, secret, ...) or a
# key-shaped value (sk-..., ghp_..., AIza...).
#
# Name the variable, never the value:      api_key_env: ANTHROPIC_API_KEY
# Put the value in .env, which .gitignore already covers.
# `openstategraph env-example` prints every variable, names only.
# ---------------------------------------------------------------------------
#
# This file is found by walking UP from wherever you ran the command to the
# git root, so it still applies from inside {workflows_dir}/<slug>/.

version: 1

# The model used when nothing more specific asked for one.
#
# Left commented on purpose: with no line here the project inherits whatever
# provider integration is installed, which is what makes
# `pip install 'openstategraph[anthropic]'` mean "Anthropic is my default".
# Uncomment to pin this project to one model — a written statement outranks a
# credential that merely happens to be exported on somebody's machine.
#
# default_model: {example}

# Where <slug>/workflow.json packages live. Relative to THIS file, never to
# the directory you happen to be standing in.
workflows_dir: {workflows_dir}

# providers:
#   - name: anthropic
#     default_model: claude-haiku-4-5
#     api_key_env: ANTHROPIC_API_KEY
#
# See openstategraph.example.yaml in the repository for the full form,
# including declaring a provider this framework has never heard of.
"""


#: The ignore rules `init` writes. `.env` is first and is the reason the file
#: exists at all: `init` deliberately does **not** write a `.env` (a generator
#: that emits a credential file is a generator whose output someone commits),
#: so the ignore rule has to already be there when the user makes one by hand
#: from the printed instructions.
GITIGNORE_LINES = (
    "# OpenStateGraph",
    ".env",
    "workflows/.openstategraph/",
    "**/.openstategraph/",
    "__pycache__/",
)


def render_gitignore() -> str:
    """The `.gitignore` `openstategraph init` writes."""
    return "\n".join(GITIGNORE_LINES) + "\n"


_ENV_VAR_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def config_provider_specs(config: OpenStateGraphConfig | None = None) -> list[Any]:
    """The file's providers, as `ProviderSpec`s ready to register.

    A field the file omits is inherited from whatever is already registered
    under that name, so declaring `default_model` for `anthropic` adjusts one
    string rather than silently blanking its env vars and aliases.
    """
    from openstategraph.providers import ProviderSpec, builtin_specs

    settings = config if config is not None else active_config()
    if settings is None:
        return []

    known = {spec.name: spec for spec in builtin_specs()}
    specs: list[Any] = []
    for entry in settings.providers:
        base = known.get(entry.name)
        env_vars: tuple[str, ...]
        if entry.api_key_env:
            if not _ENV_VAR_NAME.match(entry.api_key_env):
                raise ConfigError(
                    f"provider {entry.name!r}: api_key_env must be an environment variable "
                    f"NAME such as MY_API_KEY, not {entry.api_key_env!r}."
                )
            env_vars = (entry.api_key_env,)
        else:
            env_vars = base.env_vars if base else ()

        default_model = entry.default_model or (base.default_model if base else None)
        if not default_model:
            raise ConfigError(
                f"provider {entry.name!r}: default_model is required for a provider this "
                f"framework does not already know about."
            )

        specs.append(
            ProviderSpec(
                name=entry.name,
                default_model=default_model,
                extra=entry.extra or (base.extra if base else entry.name),
                env_vars=env_vars,
                aliases=base.aliases if base else (),
                # Inherited, and easy to forget: this rebuilds the spec field
                # by field, so anything added to `ProviderSpec` and not added
                # here is silently dropped. It happened — `endpoint_env` and
                # `default_endpoint` were missed, so a file containing nothing
                # but `- name: ollama` reverted the endpoint to `None` and sent
                # every call back to `127.0.0.1:11434`.
                # `tests/test_config_file.py` pins the full field list.
                endpoint_env=base.endpoint_env if base else (),
                default_endpoint=base.default_endpoint if base else "",
                label=entry.label or (base.label if base else ""),
                # Inherited and not declarable: a file adjusting a built-in
                # must keep its pre-flight check (workflow-gallery ticket 38),
                # while a provider the file invents has no integration module
                # we could name — and `""` is the supported answer for that,
                # meaning "let `init_chat_model` report the package it missed".
                integration_module=base.integration_module if base else "",
            )
        )
    return specs


def config_mcp_servers(config: OpenStateGraphConfig | None = None) -> list[Any]:
    """The file's `mcp_servers:`, as `McpServerDefinition`s ready to register.

    Refuses a `token_env` that is not an environment-variable name, using the
    same rule and the same message shape as `api_key_env` above. That check is
    not tidiness: the failure it catches is somebody pasting a live key into
    the field whose label says *name*, and the file it would land in is
    committed.
    """
    from openstategraph.prebuilt_mcp import McpAuth, McpServerDefinition

    settings = config if config is not None else active_config()
    if settings is None:
        return []

    servers: list[Any] = []
    for entry in settings.mcp_servers:
        token_env = (entry.auth.token_env or "").strip()
        if token_env and not _ENV_VAR_NAME.match(token_env):
            raise ConfigError(
                f"mcp_servers {entry.name!r}: auth.token_env must be an environment variable "
                f"NAME such as MY_MCP_TOKEN, not a credential."
            )
        servers.append(
            McpServerDefinition(
                name=entry.name,
                url=entry.url,
                transport=entry.transport,
                auth=McpAuth(
                    kind=entry.auth.kind,
                    header_name=(entry.auth.header_name or "").strip(),
                    token_env=token_env,
                ),
                origin="project",
                enabled=entry.enabled,
            )
        )
    return servers


__all__ = [
    "CONFIG_ENV_VAR",
    "CONFIG_FILENAMES",
    "GITIGNORE_LINES",
    "PYPROJECT_FILENAME",
    "PYPROJECT_TABLE",
    "SECRET_FIELD_NAMES",
    "SECRET_VALUE_PREFIXES",
    "SUPPORTED_VERSION",
    "ConfigError",
    "McpAuthConfig",
    "McpServerConfig",
    "OpenStateGraphConfig",
    "ProviderConfig",
    "active_config",
    "config_mcp_servers",
    "config_provider_specs",
    "configured_workflows_dir",
    "find_config_file",
    "load_config",
    "looks_like_a_secret",
    "render_config_file",
    "render_gitignore",
    "reset_active_config",
]
