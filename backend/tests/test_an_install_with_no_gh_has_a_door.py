"""The keyless report door, from both sides — `team-board-and-gap-reports/09`.

Ticket 07 built what a report may carry. This is the door it goes through when
the user has no `gh` and no GitHub account: a package-side client whose
endpoint is an environment variable, a hosted function that accepts exactly
the published schema, and one SQL routine that counts and files in a single
statement each.

**There is no Deno on this machine, so the handler is not executed here.** The
door's rules are checked two ways instead, and the split is deliberate rather
than a shrug:

- *Against a recorded report* (`fixtures/recorded_gap_report.json`, produced
  by the model itself) — the vocabulary the door was generated with must still
  accept what the model actually emits, field by field, enum by enum, hash by
  hash and byte by byte. That is the drift the two sides can suffer, and it is
  the one a running handler would find too.
- *Against the handler's text* — the properties that are structural and would
  survive any test run: a closed set of reject reasons, a body cap read before
  the parse, and no log line that can carry a value out of the request. The
  ticket asked for a handler test asserting the logger is never called with
  the body; with no runtime, the honest instrument is one that reads every
  `console.log` in the file and fails on an interpolation that is not a count,
  a status or a fixed reason.

A `deno test` would be better and is not available. When Deno is on a
maintainer's PATH the same assertions are worth writing there too; nothing
here becomes wrong when they are.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from openstategraph.gap_report import GapReport
from openstategraph.gap_report_client import (
    ENDPOINT_ENV,
    Accepted,
    Refused,
    ReportDoorClosed,
    endpoint,
    send,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "backend" / "openstategraph"
DOOR = REPO_ROOT / "supabase" / "functions" / "gap-report" / "index.ts"
CONTRACT_TS = REPO_ROOT / "supabase" / "functions" / "gap-report" / "contract.generated.ts"
FUNCTION_CONFIG = REPO_ROOT / "supabase" / "config.toml"
MIGRATION = PACKAGE_ROOT / "kanban_migrations" / "0003_gap_report_door.sql"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "recorded_gap_report.json"


def _generator():
    """The publishing script, imported by path.

    `scripts/` is not a package and is not on the path from `backend/`, and
    making it one to run a drift gate would be a change to the tree for the
    convenience of a test.
    """
    import importlib.util  # noqa: PLC0415

    path = REPO_ROOT / "scripts" / "generate_gap_report_ts.py"
    spec = importlib.util.spec_from_file_location("generate_gap_report_ts", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def recorded() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def built() -> GapReport:
    """The recording, rebuilt from the model.

    Not `model_validate(recorded())`: `finding_hash` is a **computed** field on
    purpose (ticket 07), so a report is constructible from its parts and never
    from its own dump — a door cannot hand a dedup key in. That makes a round
    trip the wrong way to keep the fixture honest, and rebuilding it the right
    one.
    """
    from openstategraph.gap_report import (  # noqa: PLC0415
        GapDoor,
        GapKind,
        Refusal,
        hashed_project_id,
    )

    return GapReport(
        version="0.3.0rc15",
        kind=GapKind.NO_BACKEND,
        type_ids=("tool.acme-ping",),
        door=GapDoor.CLI,
        refusal=Refusal.for_missing_implementation("tool.acme-ping"),
        check="no-backend",
        os="Darwin 25.6.0",
        python="3.12.7",
        project_hash=hashed_project_id("a-project-id"),
    )


def door_text() -> str:
    return DOOR.read_text(encoding="utf-8")


def contract() -> dict:
    """The generated vocabulary, read back out of the TypeScript.

    Read rather than recomputed from the model: the point of every assertion
    below is what the *door* was given, and recomputing it here would make
    this file a second generator and prove nothing about the file that ships.
    """
    text = CONTRACT_TS.read_text(encoding="utf-8")
    body = text.partition("export const CONTRACT = ")[2].rpartition(" as const;")[0]
    return json.loads(body)


# --------------------------------------------------------------------------
# The package's side: a URL in a variable, and nothing sent that was not read.
# --------------------------------------------------------------------------


def test_unset_means_the_door_does_not_exist() -> None:
    """`CLAUDE.md`'s Ollama rule, at the one place this package reaches
    anything of ours: no default endpoint, so an install that has not named
    one has no door rather than a silent one."""
    assert endpoint({}) is None
    assert endpoint({ENDPOINT_ENV: "   "}) is None
    assert endpoint({ENDPOINT_ENV: "https://example.invalid/x"}) == (
        "https://example.invalid/x"
    )


def test_no_shipped_module_carries_a_default_report_endpoint() -> None:
    """Neither the client nor the model may hold a URL that could become one.

    `gap_report.py` is allowed the JSON Schema dialect id — a name, never
    dialled — and the census below is what keeps that exception from becoming
    a precedent.
    """
    carried = [
        value
        for value in _string_constants(PACKAGE_ROOT / "gap_report_client.py")
        if "https://" in value
    ]
    assert carried == []


def _string_constants(path: Path) -> list[str]:
    """Every string literal in a module that is not a docstring.

    Comments are absent by construction, which is the right reading of *"a
    literal outside a docstring"*: a URL nobody can dial is prose, and prose is
    what a docstring and a comment both are.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            first = (getattr(node, "body", []) or [None])[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstrings.add(id(first.value))
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            found.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            found.extend(
                piece.value
                for piece in node.values
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str)
            )
    return found


#: One row per shipped module holding an `https://` literal outside a
#: docstring, with the count and the argument beside it — the same ratchet
#: shape as `test_module_size_ceiling.py`, and for the same reason: a bare
#: prohibition would be red on day one for eleven modules, which is how a pin
#: acquires a suppression and dies.
#:
#: What the ticket is defending is narrower than *no URLs*: it is that **no
#: URL of ours is baked into a build**. Every row below reaches a third party
#: the user named, a public registry, or nothing at all.
URL_CENSUS: dict[str, tuple[int, str]] = {
    "api/plugin_capabilities.py": (1, "a link to our own published docs page"),
    "examples/guarded-lookup/tools/directory.py": (6, "example.com rows in a sample"),
    "examples/web-research-digest/tests/test_web_research_digest_document.py": (
        1,
        "a deliberately unreachable loopback URL in an example's own test",
    ),
    "gap_report.py": (1, "the JSON Schema dialect id — a name, never dialled"),
    "gap_report_door.py": (
        1,
        "github.com, the host the issue form and the `gh` door share — the "
        "owner and repository after it are read from the package's own "
        "metadata (`team-board-and-gap-reports/08`)",
    ),
    "mssql_connection.py": (3, "Azure AD's own scope and authority"),
    "plugin_interop.py": (2, "the plugin format's published schema ids"),
    "prebuilt_mcp.py": (2, "two MCP servers a user picks from a catalogue"),
    "prebuilt_youtube.py": (3, "YouTube's own player endpoint"),
    "providers.py": (1, "Ollama's cloud endpoint, the default behind OLLAMA_HOST"),
    "search_backends.py": (2, "the two search vendors a key opts into"),
}


def test_the_url_census_is_exact() -> None:
    """A new `https://` literal in a shipped module is a red test naming the
    module, not a line somebody notices in review."""
    found: dict[str, int] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        count = sum(1 for value in _string_constants(path) if "https://" in value)
        if count:
            found[str(path.relative_to(PACKAGE_ROOT))] = count
    assert found == {name: row[0] for name, row in URL_CENSUS.items()}


def test_a_report_is_sent_only_after_it_was_shown() -> None:
    """Opt-in per send, expressed structurally: a caller cannot show one
    report and post another, because the text it printed is an argument and is
    compared against this report's own rendering."""
    report = built()
    posted: list[tuple[str, bytes]] = []

    def transport(url, body, headers):
        posted.append((url, body))
        return 200, b'{"outcome": "filed", "count": 1}'

    with pytest.raises(ValueError):
        send(report, "https://example.invalid/x", shown="looks fine to me", transport=transport)
    assert posted == []


def test_the_wire_is_the_models_own_dump() -> None:
    report = built()
    seen: dict[str, object] = {}

    def transport(url, body, headers):
        seen["url"] = url
        seen["body"] = json.loads(body.decode("utf-8"))
        seen["headers"] = dict(headers)
        return 200, b'{"outcome": "filed", "count": 1}'

    answer = send(
        report,
        "https://example.invalid/gap-report",
        shown=report.render(),
        transport=transport,
    )
    assert answer == Accepted(outcome="filed", count=1)
    assert seen["url"] == "https://example.invalid/gap-report"
    assert seen["body"] == recorded()
    assert seen["headers"]["content-type"] == "application/json"


def test_an_unconfigured_door_is_not_a_refusal() -> None:
    report = built()
    with pytest.raises(ReportDoorClosed) as raised:
        send(report, "", shown=report.render())
    assert ENDPOINT_ENV in str(raised.value)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b'{"outcome": "counted", "count": 41}', Accepted("counted", 41)),
        (429, b'{"outcome": "refused", "reason": "rate-limited"}', Refused(429, "rate-limited")),
        (413, b'{"outcome": "refused", "reason": "too-large"}', Refused(413, "too-large")),
        (503, b'{"outcome": "closed"}', Refused(503, "closed")),
        (200, b"not json at all", Refused(200, "unrecognised-answer")),
        (200, b"[1, 2, 3]", Refused(200, "unrecognised-answer")),
        (500, b"", Refused(500, "unrecognised-answer")),
    ],
)
def test_every_answer_has_a_type(status: int, body: bytes, expected: object) -> None:
    """Tolerant in reading, strict in trusting. A door that changed the shape
    of its answer turns a courtesy into a `Refused`, never into a traceback —
    and only a 200 carrying an outcome this side knows becomes an `Accepted`."""
    report = built()
    answer = send(
        report,
        "https://example.invalid/x",
        shown=report.render(),
        transport=lambda url, data, headers: (status, body),
    )
    assert answer == expected


def test_nothing_in_the_package_imports_the_transport() -> None:
    """Ticket 07's rule, extended to the transport it deliberately lacked.

    The census is over **imports** rather than over calls to a function called
    `send`: this package has a dozen ASGI `send` parameters and matching them
    by name would be a test about a word. Importing this module is the
    decision — a door a person invoked is the only thing that may make it, and
    today nothing does.
    """
    importers = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name == "gap_report_client.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "gap_report_client" in text:
            importers.append(str(path.relative_to(PACKAGE_ROOT)))
    assert importers == []


# --------------------------------------------------------------------------
# The generated vocabulary: one description of the report, in two languages.
# --------------------------------------------------------------------------


def test_the_contract_is_what_the_model_produces_today() -> None:
    """The drift gate. A field added to `GapReport` and not regenerated is a
    red test here, not a door that silently drops it."""
    assert _generator().main(["--check"]) == 0


def test_the_drift_gate_can_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Break the fix: a stale contract must be reported as stale. A `--check`
    that cannot say no is a `--check` nobody should trust."""
    generate_gap_report_ts = _generator()
    stale = tmp_path / "contract.generated.ts"
    stale.write_text("export const CONTRACT = {} as const;\n", encoding="utf-8")
    monkeypatch.setattr(generate_gap_report_ts, "CONTRACT_PATH", stale)
    assert generate_gap_report_ts.main(["--check"]) == 1


def test_the_door_knows_every_field_the_model_emits() -> None:
    """The recorded report, field by field, against the vocabulary the door
    holds. This is the assertion a running handler would make first."""
    fields = contract()["fields"]
    payload = recorded()
    assert set(payload) <= set(fields), set(payload) - set(fields)
    for required in contract()["required"]:
        assert required in payload, required
    for name, value in payload.items():
        shape = fields[name]["kind"]
        if shape == "enum":
            assert value in fields[name]["values"], (name, value)
        elif shape == "stringArray":
            assert isinstance(value, list) and all(isinstance(x, str) for x in value)
        elif shape == "nullableString":
            assert value is None or isinstance(value, str)
        elif shape == "refusal":
            assert set(value) == set(contract()["refusalFields"])
            assert value["source"] in contract()["refusalSources"]
        else:
            assert isinstance(value, str), name


def test_the_recorded_report_is_still_a_report() -> None:
    """A fixture that has drifted from the model is a fixture that proves
    nothing about it, so the recording is validated back through the model
    every run."""
    report = built()
    assert report.model_dump(mode="json") == recorded()


def test_every_carried_sentence_fits_the_doors_cap() -> None:
    cap = contract()["textCap"]
    payload = recorded()
    assert len(payload["refusal"]["text"]) <= cap
    assert len(json.dumps(payload).encode("utf-8")) < 16 * 1024


# --------------------------------------------------------------------------
# The handler's own properties, read off the file that ships.
# --------------------------------------------------------------------------


def test_the_door_is_public_by_declaration() -> None:
    """`verify_jwt = false`, written down with its argument, because a
    reporting install holds no credential of ours and cannot be asked for
    one."""
    config = FUNCTION_CONFIG.read_text(encoding="utf-8")
    assert "[functions.gap-report]" in config
    section = config.partition("[functions.gap-report]")[2]
    assert re.search(r"^verify_jwt\s*=\s*false", section, re.M)


def test_every_reject_reason_is_from_a_closed_set() -> None:
    """A reject reason is logged, so it must be a string chosen in the handler
    and never one assembled out of the request."""
    text = door_text()
    union = text.partition("type Reason =")[2].partition(";")[0]
    declared = set(re.findall(r'"([a-z-]+)"', union))
    assert declared
    used = set(re.findall(r'refuse\(\s*"([a-z-]+)"', text))
    used |= set(re.findall(r'return "([a-z-]+)";', text))
    assert used <= declared, used - declared


#: What a log line may interpolate. Counts, the door's own reject reasons, a
#: status — and, from `team-board-and-gap-reports/17`, one **generated
#: constant**: the board a filed report lands on.
#:
#: The rule this set enforces is *nothing out of the request*, and a value
#: emitted from `kanban_store.TEAM_BOARD` into `contract.generated.ts` at
#: build time is the opposite of that — it is the same word on every line the
#: door will ever write, whoever called it. Widened by naming the one member
#: rather than by allowing `CONTRACT.*`: the contract also carries the field
#: names and enum values a report is checked against, and a log line
#: interpolating one of those would say which field a caller sent.
_ALLOWED_IN_A_LOG = re.compile(
    r"^(bytes\.byteLength|checked\.dropped|reason|written\.outcome|written\.count"
    r"|response\.status|CONTRACT\.board)$"
)


def test_no_log_line_can_carry_a_value_out_of_the_request() -> None:
    """The runbook's §7, as an instrument: counts and reject reasons only,
    never the payload, never a field value, not even on an error path.

    Every interpolation in every `console.log` in the handler is matched
    against the closed set above, so a later edit that logs `report`,
    `payload`, a field or a response body is a red test rather than an
    incident found by reading the dashboard.
    """
    for logged in re.findall(r"console\.log\(([\s\S]*?)\);", door_text()):
        for interpolated in re.findall(r"\$\{([^}]*)\}", logged):
            assert _ALLOWED_IN_A_LOG.match(interpolated.strip()), interpolated
        assert "JSON.stringify" not in logged


def test_the_body_is_capped_before_it_is_parsed() -> None:
    """A cap that runs after the parse is not a cap — the parse is the cost it
    exists to avoid. Checked twice, because `content-length` is a claim and a
    chunked request makes none."""
    text = door_text()
    caps = [m.start() for m in re.finditer(r"BODY_CAP_BYTES", text)]
    parse = text.index("JSON.parse")
    assert len([position for position in caps if position < parse]) >= 3


def test_the_door_calls_the_one_routine_the_migration_defines() -> None:
    """One operation against the database, and the two files agree on its
    name — the door's code can express exactly one write, so a later change
    cannot quietly grow a second."""
    called = re.findall(r"rest/v1/rpc/([a-z_]+)", door_text())
    assert called == ["file_gap_report"]
    sql = _statements(MIGRATION.read_text(encoding="utf-8"))
    assert f"create or replace function public.{called[0]}(" in sql


def test_the_door_holds_no_key_and_names_the_two_it_reads() -> None:
    """The service key is the function's, never the caller's: read from the
    function's own environment by name, and present in no response and no log
    line."""
    text = door_text()
    assert 'Deno.env.get(URL_ENV)' in text
    assert 'Deno.env.get(KEY_ENV)' in text
    assert re.search(r'const KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"', text)
    for secretish in re.findall(r'"[A-Za-z0-9+/=]{40,}"', text):
        pytest.fail(f"a literal that could be a key is in the handler: {secretish[:12]}…")


# --------------------------------------------------------------------------
# The migration: least privilege, and no check-then-write anywhere.
# --------------------------------------------------------------------------


def test_the_routine_is_definer_with_an_empty_search_path() -> None:
    sql = _statements(MIGRATION.read_text(encoding="utf-8"))
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    revoke = sql.index("revoke all on function public.file_gap_report")
    grant = sql.index("grant execute on function public.file_gap_report")
    assert revoke < grant, "execute is granted before it is revoked from public"


def test_the_rate_table_is_forced_closed() -> None:
    sql = _statements(MIGRATION.read_text(encoding="utf-8"))
    assert "alter table public.gap_report_rate enable row level security" in sql
    assert "alter table public.gap_report_rate force row level security" in sql
    assert "create policy" not in sql


def _statements(sql: str) -> str:
    """The SQL with its commentary taken out — these files argue for
    themselves at length, and a comment naming a clause is not that clause."""
    return "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )


def test_counting_and_filing_are_upserts_not_reads() -> None:
    """`data-upsert`: the increment is the statement, so there is no window
    between reading a counter and writing it."""
    sql = _statements(MIGRATION.read_text(encoding="utf-8"))
    assert sql.count("on conflict") == 2
    assert "do update set count = rate.count + 1" in sql
    assert "do update set count = card.count + 1" in sql
    assert not re.search(r"select\s+count\s*\(", sql)


def test_the_dedup_index_is_the_key_the_report_carries() -> None:
    """One card per `(project_hash, finding_hash)` with a count — the owner's
    *"repeats are one card with a count"*, and the reason the retention job in
    the runbook can be a dated delete rather than a partition drop."""
    sql = _statements(MIGRATION.read_text(encoding="utf-8"))
    assert "create unique index if not exists cards_project_finding_idx" in sql
    assert "on public.cards (project_hash, finding_hash)" in sql
    assert "where finding_hash <> ''" in sql
