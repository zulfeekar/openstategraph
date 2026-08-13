"""Who a run is for — decided by the server (memory-hardening ticket 01)."""

from __future__ import annotations

import pytest

from openstategraph.principal import (
    NoPrincipals,
    TrustedHeaderPrincipals,
    principals_from_env,
)


class TestTheDefaultIsNobody:
    """A deployment that has configured no identity has no identities.

    The defect this ticket exists for is that `user_email` was a free-typed
    box in `/chat`, sent verbatim, and used unverified as the key of a memory
    namespace. Refusing to guess is the only safe default: the alternative is
    a namespace any client can select.
    """

    def test_no_headers_no_principal(self) -> None:
        assert NoPrincipals().resolve({}) is None

    def test_a_client_asserting_an_identity_still_gets_nobody(self) -> None:
        # The whole point. Every header a client can set is a header an
        # attacker can set.
        headers = {"x-forwarded-email": "ceo@company.com", "x-user": "ceo@company.com"}
        assert NoPrincipals().resolve(headers) is None


class TestTrustedHeader:
    """The reverse-proxy pattern: a header the *proxy* sets, never the client.

    Safe only when the proxy strips any client-supplied copy — which is the
    deployment's job and is why this must be opted into by name.
    """

    def test_it_reads_the_named_header(self) -> None:
        who = TrustedHeaderPrincipals("X-Forwarded-Email").resolve(
            {"x-forwarded-email": "Me@Example.COM"}
        )
        # The id is folded, because it keys a namespace and one person must be
        # one key. The label keeps what the proxy actually said, for display.
        assert who is not None
        assert who.id == "me@example.com" and who.label == "Me@Example.COM"

    def test_header_matching_ignores_case_because_http_does(self) -> None:
        resolver = TrustedHeaderPrincipals("X-Forwarded-Email")
        who = resolver.resolve({"X-Forwarded-Email": "a@b.com"})
        assert who is not None and who.id == "a@b.com"

    def test_an_absent_or_blank_header_is_nobody_not_an_empty_principal(self) -> None:
        resolver = TrustedHeaderPrincipals("X-Forwarded-Email")
        assert resolver.resolve({}) is None
        assert resolver.resolve({"x-forwarded-email": "   "}) is None

    def test_it_refuses_to_be_configured_with_no_header_name(self) -> None:
        # A resolver that reads "" would match nothing and look configured.
        with pytest.raises(ValueError):
            TrustedHeaderPrincipals("  ")


class TestPrincipalsFromEnv:
    def test_unset_means_the_refusing_resolver(self, monkeypatch) -> None:
        monkeypatch.delenv("OPENSTATEGRAPH_PRINCIPAL_HEADER", raising=False)
        assert isinstance(principals_from_env(), NoPrincipals)

    def test_set_means_the_trusted_header_resolver(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENSTATEGRAPH_PRINCIPAL_HEADER", "X-Forwarded-Email")
        who = principals_from_env().resolve({"x-forwarded-email": "a@b.com"})
        assert who is not None and who.id == "a@b.com"

    def test_a_blank_setting_is_unset_not_a_broken_resolver(self, monkeypatch) -> None:
        # `OPENSTATEGRAPH_PRINCIPAL_HEADER=` left in a `.env` is somebody
        # turning it off — the same reading `auth.py` gives its own variable.
        monkeypatch.setenv("OPENSTATEGRAPH_PRINCIPAL_HEADER", "   ")
        assert isinstance(principals_from_env(), NoPrincipals)
