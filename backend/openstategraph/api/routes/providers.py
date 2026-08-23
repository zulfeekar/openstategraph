"""Which model providers this server is configured for, and whether they work.

Two routes. Neither touches `WorkflowServices` at all — they read the provider
catalogue and the environment — so they moved out of `create_app` without
gaining a dependency (reviews-2026-08-14 ticket 15).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from openstategraph.api.schemas import (
    ProviderStatusListResponse,
    ProviderStatusResponse,
    ProviderVerifyResponse,
)

router = APIRouter()


@router.get(
    "/api/providers",
    response_model=ProviderStatusListResponse,
    summary="Which providers this server is configured for",
    tags=["Operations"],
)
def provider_status() -> ProviderStatusListResponse:
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

    **`environment` names the second thing a reader could not previously
    see** (`providers-and-credentials/13`): the rows above answer "what does
    this process's environment hold", and that process reads `.env` only if
    something loaded it before this server started — `create_app` never
    does, on purpose. Without this, a reader who put keys in `.env` and
    started a bare `uvicorn` line had no way to learn, from this endpoint,
    that those keys never arrived.
    """
    from openstategraph.dotenv import environment_source_note
    from openstategraph.providers import ProviderEnvironment, provider_catalogue

    rows = [
        ProviderStatusResponse(
            name=here.spec.name,
            label=here.spec.display,
            configured=here.is_configured(),
            # The variable that actually did it. `is_configured` is
            # `any(env_vars)`, so Ollama is configured by its key *or* its
            # host — naming the first would send a developer running their
            # own daemon looking for a cloud key they do not need. Asked of
            # `here` rather than of `os.getenv`: this loop was a third copy of
            # `credential_source`, and one written against the real process
            # environment inside an object whose whole point is that it may
            # describe a different one.
            configured_by=(source[0] if (source := here.credential_source()) else None),
            env_vars=list(here.spec.env_vars),
            default_model=here.model_string(),
            key_hint=here.key_hint(),
        )
        for here in map(ProviderEnvironment, provider_catalogue().list())
    ]
    return ProviderStatusListResponse(
        providers=rows,
        environment=environment_source_note(loaded=False),
    )

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
    from openstategraph.chat_model import verify_provider as make_the_call
    from openstategraph.providers import ProviderEnvironment, provider_catalogue

    spec = provider_catalogue().get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f'No provider named "{name}".')

    # The call itself lives in `chat_model.verify_provider`, because
    # `openstategraph providers --check` asks the identical question from a
    # terminal and two spellings of it would let the editor and the CLI
    # disagree about whether a key works (providers-and-credentials 12).
    failure = make_the_call(ProviderEnvironment(spec))
    if failure is not None:
        return ProviderVerifyResponse(name=name, ok=False, detail=failure)
    return ProviderVerifyResponse(name=name, ok=True)
