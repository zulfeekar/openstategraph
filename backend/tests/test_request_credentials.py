"""Per-request provider credentials (editor "Models and credentials").

No test here prints, logs or asserts on a credential *value* beyond the
minimum needed to prove the fallback rule; the helper itself only ever
returns key names.
"""

from __future__ import annotations

from openstategraph.api.model_resolution import ACCEPTED_CREDENTIAL_KEYS, apply_credentials
from openstategraph.api.schemas import ResumeRequest, RunRequest

DOC = {"nodes": [], "edges": []}


def test_run_request_accepts_and_round_trips_credentials() -> None:
    request = RunRequest(
        workflow=DOC,
        question="hi",
        credentials={"ANTHROPIC_API_KEY": "sk-test"},
    )
    assert request.credentials == {"ANTHROPIC_API_KEY": "sk-test"}
    assert RunRequest.model_validate(request.model_dump()).credentials == request.credentials


def test_run_request_credentials_are_optional() -> None:
    assert RunRequest(workflow=DOC, question="hi").credentials is None


def test_resume_request_accepts_credentials_too() -> None:
    """Both models forbid extras: a client that sends them on run sends them
    on resume, so a missing field here would 422 every approval."""
    request = ResumeRequest(
        thread_id="t-1",
        workflow=DOC,
        decision="approve",
        credentials={"OPENAI_API_KEY": "sk-test"},
    )
    assert ResumeRequest.model_validate(request.model_dump()).credentials == request.credentials


def test_absent_env_vars_are_filled() -> None:
    env: dict[str, str] = {}
    filled = apply_credentials({"ANTHROPIC_API_KEY": "sk-test"}, env, refused_because=None)
    assert filled == ["ANTHROPIC_API_KEY"]
    assert env["ANTHROPIC_API_KEY"] == "sk-test"


def test_present_env_vars_are_never_overridden() -> None:
    env = {"ANTHROPIC_API_KEY": "server-value"}
    assert apply_credentials({"ANTHROPIC_API_KEY": "browser-value"}, env, refused_because=None) == []
    assert env["ANTHROPIC_API_KEY"] == "server-value"


def test_unknown_and_blank_keys_are_ignored() -> None:
    env: dict[str, str] = {}
    filled = apply_credentials(
        {"PATH": "/evil", "AWS_SECRET_ACCESS_KEY": "x", "OPENAI_API_KEY": "   "},
        env,
        refused_because=None,
    )
    assert filled == []
    assert env == {}


def test_none_is_a_no_op() -> None:
    env: dict[str, str] = {}
    assert apply_credentials(None, env, refused_because=None) == []
    assert env == {}


def test_accepted_keys_cover_the_documented_providers() -> None:
    """Everything a run request may write into the process, and nothing else.

    Ollama contributes three: two that make it configured — `OLLAMA_API_KEY`
    for the cloud, `OLLAMA_HOST` for a daemon you run — and `OLLAMA_ENDPOINT`,
    which only says where the cloud is and has a working default.

    Azure contributes **one**, and the three it does not are the point
    (providers-and-credentials/18). `AZURE_OPENAI_ENDPOINT` is an address, and
    a request that could name the address could redirect the server's own key
    to it — the rule `_is_secret` already states for `endpoint_env`. The other
    two are deployment-level settings somebody sets once beside the key, not
    something a caller carries per run. A constructor argument is therefore
    server configuration, and does not join this list by declaring itself.
    """
    assert ACCEPTED_CREDENTIAL_KEYS == {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "OLLAMA_API_KEY",
        "OLLAMA_HOST",
        "OLLAMA_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
    }
