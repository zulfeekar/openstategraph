#!/usr/bin/env python3
"""Nine cases a QA can actually run (providers-and-credentials/03).

Three providers — anthropic, openai, ollama — times three states — absent,
wrong, valid — is nine cells. Six of them need no vendor account at all:

- **absent** needs an empty environment. No network call: `build_chat_model`
  returns an `UnconfiguredProvider` and the message comes from
  `provider_readiness` the moment something touches it.
- **wrong** needs any non-empty string in the credential variable, and a real
  network call that will come back 401/403. `credential_error_from` is what
  turns that vendor exception into ours.

**valid** is the one this script cannot run for you — it needs a real key,
and only for the provider you are checking. Run it yourself:

    ANTHROPIC_API_KEY=sk-... python3 scripts/nine_provider_cases.py --valid anthropic
    OPENAI_API_KEY=sk-...    python3 scripts/nine_provider_cases.py --valid openai
    OLLAMA_API_KEY=...       python3 scripts/nine_provider_cases.py --valid ollama
    # or, for a daemon you run yourself:
    OLLAMA_HOST=http://localhost:11434 python3 scripts/nine_provider_cases.py --valid ollama

Ollama has a real fourth shape (`CLAUDE.md`, "Ollama means Ollama cloud"):
`OLLAMA_HOST` alone is a legitimate keyless configuration — a daemon you run.
"Absent" for Ollama means *neither* `OLLAMA_API_KEY` nor `OLLAMA_HOST` nor
`OLLAMA_ENDPOINT` is set, not just that the key is missing.

Usage
-----

    python3 scripts/nine_provider_cases.py            # 3 absent cases, no network
    python3 scripts/nine_provider_cases.py --live      # + 3 wrong-key cases, 1 call each
    python3 scripts/nine_provider_cases.py --live --provider anthropic

**Network calls are opt-in, on purpose.** The three "wrong" cases are cheap
(one call each, to a vendor that immediately 401s — no tokens, no retries) but
they are still real outbound network calls to three different vendors, on
every run, which is a different thing from a script a QA runs unattended.
`--live` says so explicitly rather than happening by default.

This script does not assert against exact message text — that freezes the
copy `providers-and-credentials/04` is meant to be free to improve. It checks
*properties*: the message names a variable someone can set, does not leak a
vendor traceback, and (for `--live`) that the vendor's own text is not
echoed back verbatim (`chat_model.credential_error_from` drops it deliberately).
The verbatim message is printed so a human can read it and judge the copy.
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from openstategraph.chat_model import build_chat_model, credential_error_from  # noqa: E402
from openstategraph.providers import provider_catalogue  # noqa: E402

#: Every variable any built-in provider reads, credential or endpoint. All of
#: them are cleared for "absent" and restored afterwards — an ambient
#: `OLLAMA_HOST` from the developer's own shell is exactly the hazard
#: `providers-and-credentials/05` found the proof script carrying.
ISOLATED_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OLLAMA_API_KEY",
    "OLLAMA_HOST",
    "OLLAMA_ENDPOINT",
)

#: `provider:model` used to drive each case. The model name is irrelevant to
#: the absent case (the credential gate fires before any model is named to a
#: vendor) and to the wrong-key case (the vendor rejects the credential before
#: it looks at the model).
PROBE_MODEL = {
    "anthropic": "anthropic:claude-haiku-4-5",
    "openai": "openai:gpt-4.1-mini",
    "ollama": "ollama:gpt-oss:120b-cloud",
}

#: A garbage credential for the "wrong" case. Non-empty, so `is_configured()`
#: is true and `build_chat_model` returns a real model instead of
#: `UnconfiguredProvider` — and shaped so no vendor mistakes it for a
#: differently-formatted valid key.
WRONG_KEY = "sk-not-a-real-key-0000000000000000000000"


@contextmanager
def isolated_environment(overrides: dict[str, str] | None = None):
    """The process environment with every provider variable cleared, then the
    given overrides applied. Restores exactly what it found, every exit path.
    """
    saved = {name: os.environ.get(name) for name in ISOLATED_VARS}
    try:
        for name in ISOLATED_VARS:
            os.environ.pop(name, None)
        for name, value in (overrides or {}).items():
            os.environ[name] = value
        yield
    finally:
        for name in ISOLATED_VARS:
            os.environ.pop(name, None)
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


@dataclass
class CaseResult:
    provider: str
    state: str
    ok: bool
    message: str
    notes: list[str]


def _check_properties(message: str, expected_vars: tuple[str, ...]) -> list[str]:
    """Property checks, not exact-text checks — see the module docstring."""
    problems = []
    if not any(var in message for var in expected_vars):
        problems.append(f"does not name any of {expected_vars!r}")
    if "Traceback" in message or ".py\", line" in message:
        problems.append("leaks a stack trace")
    if not message.strip():
        problems.append("is empty")
    return problems


def absent_case(provider: str) -> CaseResult:
    """No credential at all. No network call — the gate fires on first use."""
    spec = provider_catalogue().get(provider)
    assert spec is not None, f"provider {provider!r} is not registered"
    with isolated_environment():
        model = build_chat_model(PROBE_MODEL[provider])
        try:
            model.invoke("hi")
        except Exception as exc:  # noqa: BLE001 - the message under test
            message = str(exc)
        else:
            return CaseResult(provider, "absent", False, "", ["invoke succeeded with no credential"])
    problems = _check_properties(message, spec.env_vars)
    return CaseResult(provider, "absent", not problems, message, problems)


def wrong_case(provider: str) -> CaseResult:
    """A non-empty, invalid credential. One real network call, expected to 401/403."""
    spec = provider_catalogue().get(provider)
    assert spec is not None, f"provider {provider!r} is not registered"
    overrides = {spec.env_vars[0]: WRONG_KEY}
    with isolated_environment(overrides):
        model = build_chat_model(PROBE_MODEL[provider])
        try:
            model.invoke("hi")
        except Exception as exc:  # noqa: BLE001 - the vendor's own refusal
            translated = credential_error_from(exc)
            if translated is None:
                return CaseResult(
                    provider,
                    "wrong",
                    False,
                    str(exc),
                    [f"credential_error_from did not recognise this as a refusal: {type(exc).__name__}"],
                )
            message = str(translated)
        else:
            return CaseResult(provider, "wrong", False, "", ["invoke succeeded with a fake credential"])
    problems = _check_properties(message, spec.env_vars)
    if WRONG_KEY in message:
        problems.append("echoes the credential value back")
    return CaseResult(provider, "wrong", not problems, message, problems)


def valid_case(provider: str) -> CaseResult:
    """Whatever credential is already in the environment, taken at face value.

    Not credential-free — this is the cell the ticket hands to a human with a
    key. Run with the real variable already exported; nothing here clears it.
    """
    spec = provider_catalogue().get(provider)
    assert spec is not None, f"provider {provider!r} is not registered"
    model = build_chat_model(PROBE_MODEL[provider])
    try:
        response = model.invoke("Reply with the single word: ok")
    except Exception as exc:  # noqa: BLE001
        return CaseResult(provider, "valid", False, str(exc), ["invoke raised with a live credential"])
    text = getattr(response, "content", str(response))
    return CaseResult(provider, "valid", True, str(text)[:120], [])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="also run the 3 wrong-key cases (real network calls)")
    parser.add_argument("--valid", metavar="PROVIDER", help="run the valid-key case for one provider (needs a real key already exported)")
    parser.add_argument("--provider", choices=("anthropic", "openai", "ollama"), help="restrict to one provider")
    args = parser.parse_args()

    if args.valid:
        result = valid_case(args.valid)
        _report(result)
        return 0 if result.ok else 1

    providers = [args.provider] if args.provider else ["anthropic", "openai", "ollama"]
    results = [absent_case(p) for p in providers]
    if args.live:
        results += [wrong_case(p) for p in providers]

    for result in results:
        _report(result)

    failed = [r for r in results if not r.ok]
    print()
    print(f"{len(results)} case(s) run, {len(failed)} failed.")
    if not args.live:
        print("(--live not passed: the 3 wrong-key cases did not run)")
    return 1 if failed else 0


def _report(result: CaseResult) -> None:
    status = "ok" if result.ok else "FAIL"
    print(f"[{status}] {result.provider} / {result.state}")
    print(f"    {result.message}")
    for problem in result.notes:
        print(f"    ! {problem}")


if __name__ == "__main__":
    raise SystemExit(main())
