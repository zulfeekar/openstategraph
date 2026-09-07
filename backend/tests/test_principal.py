"""Who a run is for — decided by the server (memory-hardening ticket 01)."""

from __future__ import annotations

import pytest

from openstategraph.principal import (
    PROXY_ASSERTION_HEADER,
    NoPrincipals,
    TrustedHeaderPrincipals,
    principals_from_env,
)

#: What a correctly configured proxy stamps on every request it forwards.
FROM_A_PROXY = {PROXY_ASSERTION_HEADER.lower(): "1"}


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
            {**FROM_A_PROXY, "x-forwarded-email": "Me@Example.COM"}
        )
        # The id is folded, because it keys a namespace and one person must be
        # one key. The label keeps what the proxy actually said, for display.
        assert who is not None
        assert who.id == "me@example.com" and who.label == "Me@Example.COM"

    def test_header_matching_ignores_case_because_http_does(self) -> None:
        resolver = TrustedHeaderPrincipals("X-Forwarded-Email")
        who = resolver.resolve({**FROM_A_PROXY, "X-Forwarded-Email": "a@b.com"})
        assert who is not None and who.id == "a@b.com"

    def test_an_absent_or_blank_header_is_nobody_not_an_empty_principal(self) -> None:
        resolver = TrustedHeaderPrincipals("X-Forwarded-Email")
        assert resolver.resolve(FROM_A_PROXY) is None
        assert resolver.resolve({**FROM_A_PROXY, "x-forwarded-email": "   "}) is None

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
        who = principals_from_env().resolve(
            {**FROM_A_PROXY, "x-forwarded-email": "a@b.com"}
        )
        assert who is not None and who.id == "a@b.com"

    def test_a_blank_setting_is_unset_not_a_broken_resolver(self, monkeypatch) -> None:
        # `OPENSTATEGRAPH_PRINCIPAL_HEADER=` left in a `.env` is somebody
        # turning it off — the same reading `auth.py` gives its own variable.
        monkeypatch.setenv("OPENSTATEGRAPH_PRINCIPAL_HEADER", "   ")
        assert isinstance(principals_from_env(), NoPrincipals)


class TestTheProxyHasToAssertItself:
    """the-boundary-nobody-checked 01.

    The identity header's name is a deployer's choice, so no config we ship
    can strip the one they picked. The assertion header's name is *ours*, so
    every config we ship can — and does — overwrite it. That inverts the
    problem from a blocklist nobody can write into an allowlist we can.

    The property: a request that did not come through a proxy configured for
    this product names nobody, whatever headers it carries.
    """

    HEADER = "X-Forwarded-Email"

    def test_a_client_that_forges_the_identity_header_gets_nobody(self) -> None:
        resolver = TrustedHeaderPrincipals(self.HEADER)
        assert resolver.resolve({"x-forwarded-email": "ceo@company.com"}) is None

    def test_a_client_that_forges_both_headers_is_stopped_at_the_proxy(self) -> None:
        # This resolver cannot tell a forged assertion from a real one — that
        # is the proxy's job, and it is the one line every shipped config now
        # carries, checked by `test_reverse_proxy.py`. Recorded here so the
        # boundary is not misread as living in this file.
        resolver = TrustedHeaderPrincipals(self.HEADER)
        forged = {**FROM_A_PROXY, "x-forwarded-email": "ceo@company.com"}
        assert resolver.resolve(forged) is not None

    def test_the_assertion_alone_names_nobody(self) -> None:
        assert TrustedHeaderPrincipals(self.HEADER).resolve(FROM_A_PROXY) is None

    def test_a_blank_assertion_does_not_count(self) -> None:
        resolver = TrustedHeaderPrincipals(self.HEADER)
        headers = {PROXY_ASSERTION_HEADER: "  ", "x-forwarded-email": "a@b.com"}
        assert resolver.resolve(headers) is None

    def test_the_two_states_are_distinguishable_to_a_reader(self, caplog) -> None:
        """The deliverable. "The proxy stripped it" and "the client sent it"
        used to produce one output — nobody, silently. They do not now: the
        second says so, once, naming both headers and the file to fix."""
        import logging

        resolver = TrustedHeaderPrincipals(self.HEADER)
        with caplog.at_level(logging.WARNING, logger="openstategraph.principal"):
            assert resolver.resolve({"x-forwarded-email": "ceo@company.com"}) is None
        said = " ".join(record.getMessage() for record in caplog.records)
        assert self.HEADER in said
        assert PROXY_ASSERTION_HEADER in said
        assert "docs/deploying.md" in said

    def test_the_stripped_case_stays_quiet(self, caplog) -> None:
        """A proxy that stripped the header leaves no identity header at all,
        and that is the ordinary anonymous request — warning about it every
        time is how a warning becomes wallpaper (`auth.exposure_warning`)."""
        import logging

        resolver = TrustedHeaderPrincipals(self.HEADER)
        with caplog.at_level(logging.WARNING, logger="openstategraph.principal"):
            assert resolver.resolve({}) is None
        assert caplog.records == []

    def test_it_warns_once_and_not_per_request(self, caplog) -> None:
        """An attacker replaying the forged header must not be able to fill a
        disk with our warnings about it."""
        import logging

        resolver = TrustedHeaderPrincipals(self.HEADER)
        with caplog.at_level(logging.WARNING, logger="openstategraph.principal"):
            for _ in range(5):
                resolver.resolve({"x-forwarded-email": "ceo@company.com"})
        assert len(caplog.records) == 1
