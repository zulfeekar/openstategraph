"""Which model providers this server is configured for, and whether they work.

Two routes. Neither touches `WorkflowServices` at all — they read the provider
catalogue and the environment — so they moved out of `create_app` without
gaining a dependency (reviews-2026-08-14 ticket 15).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from openstategraph.api.schemas import ProviderStatusResponse, ProviderVerifyResponse

router = APIRouter()


@router.get(
    "/api/providers",
    response_model=list[ProviderStatusResponse],
    summary="Which providers this server is configured for",
    tags=["Operations"],
)
def provider_status() -> list[ProviderStatusResponse]:
    """What the **server** can use, so a client stops guessing.

    The editor's "Models and credentials" dialog could only read the
    *browser's* credential store, so it told a QA analyst the product
    "runs offline against mock data" on a server holding three working
    keys. `/api/health` answers one boolean for any provider, which is
    enough to light a dot and not enough to say which key is missing.

    **Names and booleans only — never key material, not even masked.** A
    mask leaks length, prefix and entropy, and `credential_error_from`
    already drops OpenAI's own masked fragment out of its 401 rather than
    forwarding it. What a person can act on is *which variable* did it.

    Presence, not validity: a key can be set, well-formed and rejected for
    want of credit, which is exactly what happened here the day this was
    written. Verifying costs a real model call and belongs behind a button
    somebody presses.
    """
    from openstategraph.providers import provider_catalogue

    return [
        ProviderStatusResponse(
            name=spec.name,
            label=spec.display,
            configured=spec.is_configured(),
            # The variable that actually did it. `is_configured` is
            # `any(env_vars)`, so Ollama is configured by its key *or* its
            # host — naming the first would send a developer running their
            # own daemon looking for a cloud key they do not need.
            configured_by=next(
                (name for name in spec.env_vars if os.getenv(name, "").strip()), None
            ),
            env_vars=list(spec.env_vars),
            default_model=spec.model_string(),
            key_hint=spec.key_hint(),
        )
        for spec in provider_catalogue().list()
    ]

@router.post(
    "/api/providers/{name}/verify",
    response_model=ProviderVerifyResponse,
    summary="Make one real call, to find out whether a key actually works",
    tags=["Operations"],
)
def verify_provider(name: str) -> ProviderVerifyResponse:
    """`configured` says a variable is set. This says it works.

    They are different questions and the gap between them is where the
    confusing failures live: on the day this shipped an Anthropic key was
    set, well-formed, and rejected for want of credit. Nothing about the
    *value* could have revealed that — only a call.

    **Behind an explicit request, never on page load.** It costs money and
    latency, so a dialog that verified every provider whenever it opened
    would spend an adopter's budget to render a badge.

    The failure is reported in the product's own words where it recognises
    one, and never carries a stack trace or the credential — the same rule
    `credential_error_from` applies to a 401.
    """
    from openstategraph import chat_model
    from openstategraph.compile.workflow_compiler import describe_failure
    from openstategraph.providers import provider_catalogue

    spec = provider_catalogue().get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f'No provider named "{name}".')
    if not spec.is_configured():
        return ProviderVerifyResponse(
            name=name, ok=False, detail=spec.missing_key_message()
        )

    try:
        # The smallest thing that proves the credential is accepted. A
        # single token of output is all this needs to learn.
        chat_model.build_chat_model(spec.model_string()).invoke("hi")
    except Exception as exc:  # noqa: BLE001 — reported, never raised at a user
        return ProviderVerifyResponse(name=name, ok=False, detail=describe_failure(exc))
    return ProviderVerifyResponse(name=name, ok=True)
