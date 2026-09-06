"""How the T-SQL leaf logs in — `osg-agent-experience/73`.

The leaf knew one shape: one variable holding a whole ODBC connection string.
So a login that needs a secret needed the secret pasted into that string, beside
the `SQL_AZURE_AD_CLIENT_SECRET` that already held it — and when the secret was
the thing that was wrong, ODBC Driver 18's own Azure AD flow hung for the full
login timeout and reported `HYT00 Login timeout expired`, which is what an
unreachable server says too.

Nothing here opens a socket or reaches Azure AD. `msal` is faked at the one
`import_module` seam, exactly as the driver is in `test_prebuilt_warehouse.py` —
there is no live warehouse and no service principal in this checkout, so the
token's *shape* and the refusal's *words* are what can be proved, and they are
the two things that were wrong.
"""

from __future__ import annotations

import struct
import sys
import types
from typing import Any

import pytest

from openstategraph.mssql_connection import (
    AAD_SCOPE,
    AAD_VARS,
    ACCESS_TOKEN_ATTRIBUTE,
    ConnectionPlan,
    resolve_connection,
)

PARTS = {
    "MSSQL_DB_SERVER": "warehouse.database.windows.net",
    "MSSQL_DB_PORT": "1433",
    "MSSQL_DB_NAME": "analytics",
}
AAD = {
    "SQL_AZURE_AD_TENANT_ID": "a-tenant",
    "SQL_AZURE_AD_CLIENT_ID": "a-client",
    "SQL_AZURE_AD_CLIENT_SECRET": "a-secret-value",
}
SQL_AUTH = {"MSSQL_DB_USER": "reader", "MSSQL_DB_PASSWORD": "hunter2"}


class _FakeApplication:
    """`msal.ConfidentialClientApplication`, reduced to the one call we make."""

    instances: list["_FakeApplication"] = []

    def __init__(self, client_id: str, *, authority: str, client_credential: str) -> None:
        self.client_id = client_id
        self.authority = authority
        self.client_credential = client_credential
        self.scopes: list[str] = []
        _FakeApplication.instances.append(self)

    answer: dict[str, Any] = {"access_token": "a-token"}

    def acquire_token_for_client(self, scopes: list[str]) -> dict[str, Any]:
        self.scopes = list(scopes)
        return dict(type(self).answer)


@pytest.fixture()
def fake_msal(monkeypatch: pytest.MonkeyPatch) -> type[_FakeApplication]:
    """Stand a fake `msal` in at the module's single import seam."""
    module = types.ModuleType("msal")
    module.ConfidentialClientApplication = _FakeApplication  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "msal", module)
    _FakeApplication.instances = []
    _FakeApplication.answer = {"access_token": "a-token"}
    return _FakeApplication


class TestTheUrlStillWins:
    def test_a_url_is_taken_whole_and_asks_for_no_token(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        """Somebody who wrote a connection string meant it — parts do not edit it."""
        plan, refusal = resolve_connection(
            {**PARTS, **AAD}, url="Server=written-by-hand;Database=warehouse"
        )
        assert refusal is None
        assert plan is not None
        assert plan.connection_string == "Server=written-by-hand;Database=warehouse"
        assert plan.shape == "url"
        assert plan.attrs_before == {}
        assert fake_msal.instances == []


class TestTheConnectionIsComposedFromNamedParts:
    def test_sql_auth_composes_server_port_database_and_the_credential(self) -> None:
        plan, refusal = resolve_connection({**PARTS, **SQL_AUTH})
        assert refusal is None
        assert plan is not None
        assert plan.shape == "sql-auth"
        assert "Server=tcp:warehouse.database.windows.net,1433" in plan.connection_string
        assert "Database=analytics" in plan.connection_string
        assert "ODBC Driver 18 for SQL Server" in plan.connection_string
        assert "UID=reader" in plan.connection_string
        assert "PWD=hunter2" in plan.connection_string

    def test_the_port_has_a_default_so_five_variables_are_enough(self) -> None:
        env = {key: value for key, value in PARTS.items() if key != "MSSQL_DB_PORT"}
        plan, refusal = resolve_connection({**env, **SQL_AUTH})
        assert refusal is None and plan is not None
        assert "Server=tcp:warehouse.database.windows.net,1433" in plan.connection_string

    def test_azure_ad_composes_the_same_string_without_a_password(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        plan, refusal = resolve_connection({**PARTS, **AAD})
        assert refusal is None
        assert plan is not None
        assert plan.shape == "azure-ad"
        assert "Server=tcp:warehouse.database.windows.net,1433" in plan.connection_string
        assert "Database=analytics" in plan.connection_string

    def test_no_composed_string_ever_asks_the_driver_to_do_azure_ad(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        """The flow that hung. We hold the token, so the driver is never asked."""
        plan, _ = resolve_connection({**PARTS, **AAD})
        assert plan is not None
        assert "Authentication=" not in plan.connection_string

    def test_the_token_route_strips_a_password_left_beside_it(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        """Both shapes set is a real machine: the trio wins and UID/PWD go.

        ODBC handed a password beside an access token tries the password, which
        is the hang this ticket removed reappearing by another door.
        """
        plan, refusal = resolve_connection({**PARTS, **AAD, **SQL_AUTH})
        assert refusal is None
        assert plan is not None
        assert plan.shape == "azure-ad"
        assert "UID=" not in plan.connection_string
        assert "PWD=" not in plan.connection_string
        assert "hunter2" not in plan.connection_string


class TestTheTokenIsShapedTheWayTheDriverTakesIt:
    def test_it_is_utf_16_le_length_prefixed_under_attribute_1256(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        plan, refusal = resolve_connection({**PARTS, **AAD})
        assert refusal is None and plan is not None
        assert ACCESS_TOKEN_ATTRIBUTE == 1256
        blob = plan.attrs_before[ACCESS_TOKEN_ATTRIBUTE]
        encoded = "a-token".encode("utf-16-le")
        assert blob == struct.pack("<i", len(encoded)) + encoded

    def test_the_service_principal_is_read_from_the_three_named_variables(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        resolve_connection({**PARTS, **AAD})
        application = fake_msal.instances[-1]
        assert application.client_id == "a-client"
        assert application.authority.endswith("/a-tenant")
        assert application.client_credential == "a-secret-value"
        assert application.scopes == [AAD_SCOPE]
        assert AAD_SCOPE == "https://database.windows.net/.default"


class TestARefusedTokenIsReportedAtOnceAndByName:
    def test_an_expired_secret_reaches_the_developer_with_its_aad_code(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        """The cause the driver swallowed for a day, said in one sentence."""
        fake_msal.answer = {
            "error": "invalid_client",
            "error_description": (
                "AADSTS7000222: The provided client secret keys for app "
                "'a-client' are expired.\r\nTrace ID: x\r\nCorrelation ID: y"
            ),
        }
        plan, refusal = resolve_connection({**PARTS, **AAD})
        assert plan is None
        assert refusal is not None
        assert "AADSTS7000222" in refusal
        assert "expired" in refusal
        assert "invalid_client" in refusal
        assert "SQL_AZURE_AD_CLIENT_SECRET" in refusal
        # The multi-line trace is not the answer, and a refusal is read by a person.
        assert "Trace ID" not in refusal

    def test_the_secret_itself_is_never_echoed(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        fake_msal.answer = {"error": "invalid_client", "error_description": "AADSTS7000222"}
        _, refusal = resolve_connection({**PARTS, **AAD})
        assert refusal is not None and "a-secret-value" not in refusal

    def test_azure_ad_being_unreachable_is_data_and_not_an_exception(
        self, fake_msal: type[_FakeApplication]
    ) -> None:
        def _explode(self: Any, scopes: list[str]) -> dict[str, Any]:
            raise OSError("no route to host")

        fake_msal.acquire_token_for_client = _explode  # type: ignore[assignment]
        try:
            plan, refusal = resolve_connection({**PARTS, **AAD})
        finally:
            del fake_msal.acquire_token_for_client  # type: ignore[attr-defined]
        assert plan is None
        assert refusal is not None and "no route to host" in refusal

    def test_a_missing_token_library_names_the_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import openstategraph.mssql_connection as mod

        def _no_msal(name: str) -> Any:
            raise ModuleNotFoundError("No module named 'msal'")

        monkeypatch.setattr(mod.importlib, "import_module", _no_msal)
        plan, refusal = resolve_connection({**PARTS, **AAD})
        assert plan is None
        assert refusal is not None and "openstategraph[mssql]" in refusal
        # and says which shape asked for it, by variable name
        assert all(name in refusal for name in AAD_VARS)


class TestTheReadinessDoorNamesTheMissingVariable:
    """Which of the three shapes is configured, and what each still needs.

    There is no `openstategraph connectors` verb, and inventing one would put
    this sentence in two places. The refusal is the door: it is where a person
    stands when the answer matters.
    """

    def test_nothing_configured_names_all_three_shapes(self) -> None:
        plan, refusal = resolve_connection({}, url_name="OPENSTATEGRAPH_MSSQL_URL")
        assert plan is None
        assert refusal is not None
        assert "OPENSTATEGRAPH_MSSQL_URL" in refusal
        assert "MSSQL_DB_SERVER" in refusal and "MSSQL_DB_NAME" in refusal

    def test_a_half_configured_service_principal_names_the_one_that_is_missing(
        self,
    ) -> None:
        env = {**PARTS, **AAD}
        env.pop("SQL_AZURE_AD_CLIENT_SECRET")
        plan, refusal = resolve_connection(env)
        assert plan is None
        assert refusal is not None
        assert "SQL_AZURE_AD_CLIENT_SECRET" in refusal
        # and says the parts it does have are fine, so there is one thing to do
        assert "MSSQL_DB_SERVER, MSSQL_DB_NAME are set" in refusal

    def test_a_half_configured_sql_login_names_the_one_that_is_missing(self) -> None:
        plan, refusal = resolve_connection({**PARTS, "MSSQL_DB_USER": "reader"})
        assert plan is None
        assert refusal is not None and "MSSQL_DB_PASSWORD" in refusal

    def test_a_blank_variable_is_the_same_as_an_unset_one(self) -> None:
        env = {**PARTS, **SQL_AUTH, "MSSQL_DB_PASSWORD": "   "}
        plan, refusal = resolve_connection(env)
        assert plan is None
        assert refusal is not None and "MSSQL_DB_PASSWORD" in refusal


class TestAPlanNeverPrintsWhatItHolds:
    def test_repr_redacts_the_string_and_the_token(self) -> None:
        """A plan reaches a traceback the day something else goes wrong."""
        plan = ConnectionPlan(
            connection_string="Server=x;UID=y;PWD=hunter2",
            attrs_before={ACCESS_TOKEN_ATTRIBUTE: b"secret-bytes"},
            shape="azure-ad",
        )
        printed = repr(plan)
        assert "hunter2" not in printed
        assert "secret-bytes" not in printed
        assert "azure-ad" in printed
