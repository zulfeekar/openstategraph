"""`openstategraph.yaml` — versioned config a human or a coding agent edits.

Ticket 03. What belongs here: which providers exist, what their models are,
which is the default, and — since scale-and-adopt ticket 02 — where the
workflow packages live (`workflows_dir:`). What can never be here: a
credential. The file **may** name the environment variable that holds one,
which is the useful half of a secret without being a secret.

**Why YAML, given the lean-core rule.** The rule is about *distributions*, and
YAML costs none: `PyYAML` is already a transitive dependency of
`langchain-core`, one of the four packages the lean core is made of
(`pip show langchain-core` → `Requires: … pyyaml …`). So the honest comparison
is not "a dependency versus none" but "comments versus no comments", and this
is a file whose entire purpose is to be read and edited by a human or an agent:
it needs to say *why* a provider is pinned and *which* env var holds its key,
next to the line it applies to. JSON cannot carry a comment, so every "why"
would have to live somewhere else and rot separately. `openstategraph.json` is
accepted all the same — `json` is stdlib, and nobody should be forced into YAML
to use this.

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

    config file  <  environment  <  workflow settings.model  <  node's own
    model  <  caller's `model=` argument

The reasoning behind the one that surprises people: **environment beats the
file** because the file is committed and shared, while the environment is the
machine in front of you. A colleague's committed default must never silently
outrank the key you set for your own run.
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
CONFIG_FILENAMES = ("openstategraph.yaml", "openstategraph.yml", "openstategraph.json")

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


def find_config_file(root: Path | str | None = None) -> Path | None:
    """The config file to use, or `None` — which is the normal case.

    `OPENSTATEGRAPH_CONFIG` wins over the search, so a deployment can point at
    a file outside the project without moving it.
    """
    explicit = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None

    base = Path(root).expanduser() if root is not None else Path.cwd()
    for name in CONFIG_FILENAMES:
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def _parse(source: Path) -> Any:
    """Text to a plain structure, with a parse error that names file and line."""
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
                label=entry.label or (base.label if base else ""),
            )
        )
    return specs


__all__ = [
    "CONFIG_ENV_VAR",
    "CONFIG_FILENAMES",
    "SECRET_FIELD_NAMES",
    "SECRET_VALUE_PREFIXES",
    "SUPPORTED_VERSION",
    "ConfigError",
    "OpenStateGraphConfig",
    "ProviderConfig",
    "active_config",
    "config_provider_specs",
    "configured_workflows_dir",
    "find_config_file",
    "load_config",
    "looks_like_a_secret",
    "reset_active_config",
]
