"""A credential failure judged as UX writing — ticket 04.

The findings this module pins, all read off a real run rather than inferred:

A run whose only agent could not reach a model returned **HTTP 200**, a blank
`answer`, and `developer.warnings == []`. The one accurate sentence in the
system — `MissingProviderKey`, carrying the variable and the fix — was wrapped
in `[a1 failed after retries: …]` and filed under `outputs`, which every
surface renders as *that node's output*.

So the message was not eaten by a 502. It was eaten by success. That is the
failure `MissingProviderKey`'s own docstring exists to prevent, one layer out:
it refuses to answer silently with a different model, and the transport then
answered silently with nothing.

**Message text is deliberately not asserted verbatim**, per the ticket: that
freezes the copy and makes improving it a test failure. These assert the
properties — reaches the developer channel, names the provider, names a
variable, offers an action — and one test prints the copy for a human.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from openstategraph.api.main import create_app

CREDENTIALS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OLLAMA_API_KEY", "OLLAMA_HOST")

DOCUMENT = {
    "version": 2,
    "name": "credential-ux",
    "nodes": [
        {"id": "in1", "type": "input.text", "position": {"x": 0, "y": 0}, "data": {"prompt": "hi"}},
        {
            "id": "a1",
            "type": "agent.llm",
            "position": {"x": 200, "y": 0},
            "data": {"rules": "Answer the question."},
        },
        {"id": "out1", "type": "output.formatted", "position": {"x": 400, "y": 0}, "data": {}},
    ],
    "edges": [
        {"source": {"nodeId": "in1", "portId": "text"}, "target": {"nodeId": "a1", "portId": "prompt"}},
        {"source": {"nodeId": "a1", "portId": "result"}, "target": {"nodeId": "out1", "portId": "result"}},
    ],
}


@pytest.fixture(autouse=True)
def _no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CREDENTIALS:
        monkeypatch.delenv(name, raising=False)


def _elected_variable() -> str:
    """The credential the *instance default* provider reads, on this machine.

    These tests assert the shape of a credential failure, never a vendor. Since
    install-experience T2 the instance default is **elected** from what is
    installed rather than falling through to a hard-coded Ollama literal, so
    naming `OLLAMA_API_KEY` here would pin a machine instead of a property —
    and on an install where Ollama is not a candidate it would go green for the
    wrong reason, which is the defect the class below already records once.
    """
    from openstategraph.providers import provider_catalogue

    spec = provider_catalogue().elected_default().spec
    assert spec is not None, "no provider integration is installed in this checkout"
    assert spec.primary_env_var is not None
    return spec.primary_env_var


def _run(audience: str = "developer") -> dict:
    response = TestClient(create_app()).post(
        "/api/runs",
        json={"workflow": DOCUMENT, "question": "what is 2+2?", "audience": audience},
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestTheDiagnosisReachesTheDeveloperChannel:
    def test_a_credential_failure_is_reported_at_all(self) -> None:
        """The whole ticket in one assertion. This was `[]`."""
        warnings = _run()["developer"]["warnings"]
        assert warnings, (
            "a run whose agent could not reach a model reported nothing on the "
            "developer channel — the diagnosis was only in outputs[a1]"
        )

    def test_it_names_the_provider_and_a_variable_to_set(self) -> None:
        variable = _elected_variable()
        text = " ".join(_run()["developer"]["warnings"])
        assert variable in text
        assert variable.split("_")[0].lower() in text.lower()

    def test_it_names_the_node_that_failed(self) -> None:
        """A workflow has many nodes; "something failed" is not actionable."""
        assert any("a1" in warning for warning in _run()["developer"]["warnings"])

    def test_it_carries_no_stack_trace(self) -> None:
        text = " ".join(_run()["developer"]["warnings"])
        assert "Traceback" not in text
        assert ".py" not in text

    def test_a_customer_does_not_receive_it(self) -> None:
        """Same boundary every other developer-channel finding observes.

        The wording is for whoever can set an environment variable, and that
        is not the person asking the question.
        """
        assert _run(audience="customer").get("developer") is None


class TestBothDoorsReportIt:
    """The two doors do not fail the *same way*, which is worth knowing.

    A credential failure completes on `/api/runs` — the node error handler
    absorbs it, the run reaches its terminal state, and the diagnosis arrives
    as a developer warning. On `/api/runs/stream` it escapes the fold and
    becomes an `error` frame instead, so the run never reaches `done` and
    there are no warnings to carry it.

    Both are defensible; what matters is that each carries our copy rather
    than a vendor's, and that neither hands it to a customer. An earlier
    version of this test asserted only that `OLLAMA_API_KEY` appeared
    somewhere in the stream, which passed against the raw
    `f"{type(exc).__name__}: {exc}"` detail — it was green for the wrong
    reason and proved nothing about the copy.
    """

    def test_the_streaming_endpoint_names_the_variable_for_a_developer(self) -> None:
        response = TestClient(create_app()).post(
            "/api/runs/stream",
            json={"workflow": DOCUMENT, "question": "what is 2+2?", "audience": "developer"},
        )
        assert response.status_code == 200
        assert _elected_variable() in response.text
        # Our copy, not the exception's repr.
        assert "MissingProviderKey:" not in response.text


class TestTheCopyItself:
    def test_print_it(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Not an assertion — the ticket asks for the copy to be *read*.

        Run with `-s` to see it.
        """
        body = _run()
        with capsys.disabled():
            print("\n  answer   :", repr(body["answer"]))
            for warning in body["developer"]["warnings"]:
                print("  warning  :", warning)


class TestWrongIsNotTheSameAsMissing:
    """The ticket's first question: does a wrong key say so?

    It did not. All three vendors raised their own error and the developer
    channel carried it verbatim — a raw dict, no variable named, and in
    OpenAI's case a fragment of the key itself:

        AuthenticationError: Error code: 401 - {'error': {'message':
        'Incorrect API key provided: sk-defin****************-key. …'}}

    *Not set* and *set but wrong* need opposite actions from the reader, and
    only the first had words of ours.
    """

    def _refused(self, module: str, name: str, message: str) -> BaseException:
        """An exception shaped like the real one, without a network call.

        Built from the three shapes observed live: the vendor SDKs identify
        themselves by module, which is what `_provider_of` matches on.
        """
        exc = type(name, (Exception,), {"__module__": module})(message)
        return exc

    def test_openai_refusal_names_the_variable(self) -> None:
        from openstategraph.chat_model import credential_error_from

        exc = self._refused(
            "openai",
            "AuthenticationError",
            "Error code: 401 - {'error': {'message': 'Incorrect API key provided: "
            "sk-defin****************-key.'}}",
        )
        error = credential_error_from(exc)
        assert error is not None
        assert "OPENAI_API_KEY" in error.developer_message()
        assert "wrong or expired" in error.developer_message()

    def test_the_key_fragment_is_dropped_not_forwarded(self) -> None:
        """`SECURITY.md`'s rule does not stop applying because a vendor sent it."""
        from openstategraph.chat_model import credential_error_from

        exc = self._refused(
            "openai", "AuthenticationError", "Incorrect API key provided: sk-defin****-key."
        )
        error = credential_error_from(exc)
        assert error is not None
        assert "sk-defin" not in error.developer_message()

    def test_ollama_refusal_names_both_of_its_variables(self) -> None:
        from openstategraph.chat_model import credential_error_from

        # The real one says only "Unauthorized (status code: 401)" — no
        # provider, no variable, no action.
        exc = self._refused("ollama", "ResponseError", "Unauthorized (status code: 401)")
        error = credential_error_from(exc)
        assert error is not None
        assert "OLLAMA_API_KEY or OLLAMA_HOST" in error.developer_message()

    def test_an_unrelated_failure_is_left_alone(self) -> None:
        """No guessing. A wrong "set MYSTERY_API_KEY" is worse than silence."""
        from openstategraph.chat_model import credential_error_from

        assert credential_error_from(ValueError("something else entirely")) is None
        assert credential_error_from(self._refused("httpx", "ConnectError", "refused")) is None

    def test_a_non_auth_vendor_error_is_left_alone(self) -> None:
        from openstategraph.chat_model import credential_error_from

        exc = self._refused("openai", "RateLimitError", "Error code: 429 - rate limited")
        assert credential_error_from(exc) is None


class TestWhatACustomerSees:
    """The other half of the boundary: what reaches someone who cannot fix it.

    Both were decided rather than defaulted. A blank answer with a 200 is
    indistinguishable from a broken client, and the failure marker names an
    environment variable and a file — developer guidance, on the surface
    `test_audience_boundary.py` exists to keep developer guidance off.
    """

    def test_a_customer_gets_a_sentence_not_a_blank(self) -> None:
        answer = _run(audience="customer")["answer"]
        assert answer.strip(), "a customer asked a question and got an empty string"
        assert "could not finish" in answer

    def test_that_sentence_names_no_variable_provider_or_file(self) -> None:
        answer = _run(audience="customer")["answer"]
        for leak in (_elected_variable(), "API_KEY", ".env", "MissingProviderKey"):
            assert leak not in answer

    def test_the_failure_marker_does_not_reach_a_customer_through_outputs(self) -> None:
        """`outputs` is rendered per node on every surface — same seam as `answer`."""
        outputs = _run(audience="customer")["outputs"]
        joined = " ".join(str(v) for v in outputs.values())
        assert _elected_variable() not in joined
        assert ".env" not in joined
        assert "failed after retries" not in joined

    def test_a_developer_still_gets_the_whole_thing(self) -> None:
        """Redaction is for the audience that cannot act, not for everyone."""
        outputs = _run(audience="developer")["outputs"]
        variable = _elected_variable()
        assert any(variable in str(v) for v in outputs.values())

    def test_the_streaming_door_agrees_on_both_counts(self) -> None:
        response = TestClient(create_app()).post(
            "/api/runs/stream",
            json={"workflow": DOCUMENT, "question": "what is 2+2?", "audience": "customer"},
        )
        assert _elected_variable() not in response.text
        assert "could not finish" in response.text

    def test_a_healthy_run_is_untouched(self) -> None:
        """The substitution must fire only when a step actually failed."""
        from conftest import RespondingModel
        import openstategraph.chat_model as chat_model_module

        client = TestClient(create_app())
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                chat_model_module,
                "build_chat_model",
                lambda _name: RespondingModel([], default="four"),
            )
            body = client.post(
                "/api/runs", json={"workflow": DOCUMENT, "question": "2+2?"}
            ).json()
        assert "could not finish" not in body["answer"]
        assert "This step did not complete." not in " ".join(
            str(v) for v in body["outputs"].values()
        )


class TestTheErrorKnowsHowItReads:
    """The OOP shape, rather than a type switch at each surface.

    `describe_failure` used to ask *what kind of error is this* and then ask a
    different module for a string. Two audiences × every error type is a
    matrix that grows by editing call sites — the shape this project's rules
    reject. The base class answers both questions now, and a vendor's error is
    translated into the hierarchy once, at the edge.

    There is deliberately no `IError` protocol above `OpenStateGraphError`:
    Python's `except` accepts only classes deriving from `BaseException`, so
    such an interface would be unbindable — see the base class docstring.
    """

    def test_a_protocol_could_not_have_been_caught(self) -> None:
        """The constraint that decides the design, asserted rather than claimed."""
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class IError(Protocol):
            def developer_message(self) -> str: ...

        with pytest.raises(TypeError, match="do not inherit from BaseException"):
            try:
                raise ValueError("x")
            except IError:  # type: ignore[misc]
                pass

    def test_every_error_answers_both_questions(self) -> None:
        """Inherited, so a new error type cannot forget to have an answer."""
        from openstategraph.errors import MissingProviderKey, OpenStateGraphError

        for error in (OpenStateGraphError("x"), MissingProviderKey("set FOO")):
            assert isinstance(error.developer_message(), str)
            assert isinstance(error.customer_message(), str)

    def test_the_customer_default_is_the_safe_direction(self) -> None:
        """A subclass opts *in* to saying more, so silence is the default.

        The alternative — inherit the developer text and override to redact —
        leaks by omission the first time someone adds an error type.
        """
        from openstategraph.errors import GENERIC_FAILURE_MESSAGE, MissingProviderKey

        error = MissingProviderKey("set ANTHROPIC_API_KEY in .env")
        assert "ANTHROPIC_API_KEY" in error.developer_message()
        assert error.customer_message() == GENERIC_FAILURE_MESSAGE

    def test_missing_and_refused_are_siblings_under_one_handler(self) -> None:
        """`except CredentialError` is the one handler for "a key problem"."""
        from openstategraph.errors import (
            CredentialError,
            MissingProviderKey,
            ProviderRefusedCredential,
        )

        assert issubclass(MissingProviderKey, CredentialError)
        assert issubclass(ProviderRefusedCredential, CredentialError)
        assert not issubclass(ProviderRefusedCredential, MissingProviderKey)

    def test_catching_the_builtin_still_works(self) -> None:
        """The compatibility promise in `errors.py`'s own docstring.

        `MissingProviderKey` was `OpenStateGraphError, RuntimeError`; moving it
        under `CredentialError` must not quietly drop the builtin it used to be.
        """
        from openstategraph.errors import MissingProviderKey

        with pytest.raises(RuntimeError):
            raise MissingProviderKey("x")

    def test_an_unknown_failure_still_tells_a_developer_its_type(self) -> None:
        from openstategraph.compile.workflow_compiler import (
            describe_failure,
            describe_failure_for_customer,
        )
        from openstategraph.errors import GENERIC_FAILURE_MESSAGE

        exc = RuntimeError("the checkpointer is gone")
        assert describe_failure(exc) == "RuntimeError: the checkpointer is gone"
        # …and tells a customer nothing about checkpointers.
        assert describe_failure_for_customer(exc) == GENERIC_FAILURE_MESSAGE
