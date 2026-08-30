#!/usr/bin/env python3
"""schema-patrol — the deterministic half of the sweep.

A data package carries **five** descriptions of one warehouse, and until this
script nothing compared them:

    1. FACT       Unity Catalog + a verified query   — what is actually true
    2. INDEX      the retrieval index the agent searches — what it is TOLD
    3. KNOWLEDGE  a hand-written warehouse map        — what we UNDERSTAND
    4. SKILL      the declaration files               — what is DECLARED
    5. RULES      the validator and the prompt rules  — what is ENFORCED

**Fact is the authority. The other four are claims about it.** This script
checks the claims, in the order that has actually drawn blood:

    check 1  INDEX vs SKILL      told to use it, forbidden to use it   FAILS
    check 2  SKILL vs FACT       a declaration the warehouse denies    FAILS
    check 3  INDEX vs FACT       the agent is told something stale     FAILS
    check 4  RULES vs SKILL      decoration, or a rule with no source  reports
    check 5  KNOWLEDGE vs all    the map disagrees, or was inferred    reports

Check 1 is why this exists. A `usage_hint` naming a table no declaration
permits is the highest-severity finding there is: the agent obeys the index,
the validator refuses, the agent invents a column to replace what the join
would have given it, runs out of attempts, and the user gets a non-answer.
That was found by a human reading three failed traces.

Checks 4 and 5 only report. They need judgement and usually have a good
reason, and a patrol that fails for defensible reasons gets ignored — which
is how a check stops protecting anything.

**Not every source exists in every package.** That is normal, not an error. A
missing source skips its check and the skip is *printed*: silence about a
skipped check is the same defect this whole thing exists to prevent.

This script has no judgement in it. It reads, parses, diffs and prints. It
never calls a model, never touches the warehouse, and **never edits a
declaration, a rule or the map** — it prints a proposed change and stops. See
SKILL.md: a rule silently rewritten by a scan is a rule nobody can trust.

Usage
-----
    python3 patrol.py <package-path>
    python3 patrol.py <package-path> --knowledge ../../dyflow/docs/warehouse-map.md
    python3 patrol.py <package-path> --refresh     # recapture the fixture first
    python3 patrol.py <package-path> --json
    python3 patrol.py <package-path> --quiet       # failing findings only

Exit codes
----------
    0  no failing findings (notes may still be printed)
    1  a failing finding from check 1, 2 or 3
    2  the patrol could not run at all

Standard library only. No new dependencies, and none of the package's own.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# ==========================================================================
# Discovery.  Nothing below hardcodes a filename from any one package: this
# must patrol ANY package of this shape.  A fixture is a JSON file carrying a
# "catalog" key; a declaration is a fenced YAML block naming a canonical
# table; a rules file is code or prose that mentions them; a generator is the
# script that writes the fixture.
# ==========================================================================

FIXTURE_GLOBS = ("data/*.json", "data/**/*.json", "fixtures/*.json")
DECLARATION_GLOBS = ("skills/**/*.md", "declarations/**/*.md", "lenses/**/*.md")
RULES_GLOBS = ("tools/*.py", "functions/*.py", "middlewares/*.py", "skills/*.md")
GENERATOR_GLOBS = ("scripts/*.py", "tools/*.py")
KNOWLEDGE_HINTS = ("docs/warehouse-map.md", "docs/warehouse_map.md", "WAREHOUSE.md")

_YAML_FENCE = re.compile(r"```ya?ml\s*\n(.*?)\n```", re.DOTALL)
_FQ_TABLE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+){2})\b")


def find_fixture(pkg: Path) -> Path | None:
    for pattern in FIXTURE_GLOBS:
        for path in sorted(pkg.glob(pattern)):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — an unrelated JSON file is not an error
                continue
            if isinstance(data, dict) and isinstance(data.get("catalog"), dict):
                return path
    return None


def find_generator(pkg: Path, fixture: Path | None) -> Path | None:
    """The package's OWN fixture generator. The patrol never captures facts
    itself: the credentials, the catalog name and the index name are the
    package's business, and a second generator is a second source of truth."""
    needle = fixture.name if fixture else ""
    for pattern in GENERATOR_GLOBS:
        for path in sorted(pkg.glob(pattern)):
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            if needle and needle in text and "def main" in text:
                return path
    return None


def find_knowledge(pkg: Path, explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    roots = [pkg, *pkg.parents[:5]]
    for root in roots:
        for hint in KNOWLEDGE_HINTS:
            p = root / hint
            if p.is_file():
                return p
    return None


# ==========================================================================
# Parsing a declaration block
# ==========================================================================


def _split_comment(text: str) -> str:
    """Drop a trailing ` # comment`, tracking quote state.

    Written the long way on purpose: a first draft skipped stripping whenever
    the line contained a quote character anywhere, which meant
    `quantity_column: null   # a directory answers "which/where"` parsed as a
    column literally named `null # a directory answers "which/where`, and the
    patrol reported a nonexistent column that nobody had declared. A parser
    bug reported as a package bug is worse than no patrol.
    """
    quote = ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1].isspace()):
            return text[:i].strip()
    return text.strip()


def _mini_yaml(block: str) -> dict:
    """Enough YAML for a declaration block, standard library only.

    Handles `key: scalar`, `key: [a, b]`, `key: >` folded text, and a list of
    single-level mappings. Anything richer than a declaration needs is
    deliberately unsupported — a declaration that needs it has stopped being
    machine-checkable, which is the whole point of writing it as data.
    """
    out: dict = {}
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[:1] in (" ", "\t", "-") or ":" not in raw:
            continue
        key, _, rest = raw.partition(":")
        key = key.strip()
        rest = _split_comment(rest.strip())

        if rest in (">", "|", ">-", "|-"):
            buf = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                buf.append(lines[i].strip())
                i += 1
            out[key] = " ".join(b for b in buf if b)
            continue

        if rest == "":
            items: list[dict] = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                stripped = lines[i].strip()
                i += 1
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("- "):
                    items.append({})
                    stripped = stripped[2:].strip()
                if ":" in stripped and items:
                    k2, _, v2 = stripped.partition(":")
                    items[-1][k2.strip()] = _scalar(_split_comment(v2.strip()))
            if items:
                out[key] = items
            continue

        out[key] = _scalar(rest)
    return out


def _scalar(text: str):
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [p.strip().strip("\"'") for p in _split_top(inner) if p.strip()] if inner else []
    if text in ("null", "~", ""):
        return None
    if text in ("true", "false"):
        return text == "true"
    return text.strip("\"'")


def _split_top(text: str) -> list[str]:
    parts, depth, quote, buf = [], 0, "", []
    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


@dataclass
class Declaration:
    name: str
    path: Path
    prose: str
    canonical_table: str
    joins: list[dict] = field(default_factory=list)
    body: dict = field(default_factory=dict)

    def tables(self) -> set[str]:
        out = {self.canonical_table}
        for j in self.joins:
            if j.get("table"):
                out.add(str(j["table"]))
        return out


def load_declarations(pkg: Path) -> tuple[list[Declaration], list[str]]:
    """Every declaration block, plus notes about what would not parse.

    A file that will not parse is *reported*, never silently skipped: a
    declaration the patrol cannot read is a declaration nobody is checking,
    and saying so is the difference between a clean run and a blind one.
    """
    decls: list[Declaration] = []
    notes: list[str] = []
    seen: set[Path] = set()
    for pattern in DECLARATION_GLOBS:
        for path in sorted(pkg.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                notes.append(f"unreadable declaration file {path.name}: {exc}")
                continue
            for block in _YAML_FENCE.findall(text):
                if "canonical_table" not in block:
                    continue
                data = _mini_yaml(block)
                table = data.get("canonical_table")
                if not table:
                    notes.append(f"a block in {path.name} names no canonical_table; not checked")
                    continue
                joins = data.get("joins")
                decls.append(Declaration(
                    name=str(data.get("lens") or path.stem),
                    path=path,
                    prose=text,
                    canonical_table=str(table),
                    joins=[j for j in joins if isinstance(j, dict)] if isinstance(joins, list) else [],
                    body=data,
                ))
    return decls, notes


_NOT_A_TABLE = re.compile(r"^##+\s*not a (lens|table|fact)", re.IGNORECASE)


def load_exemptions(pkg: Path) -> dict[str, str]:
    """Tables the package has deliberately *placed as not-a-lens*.

    An index or infrastructure table that answers no user question is a
    correct thing to have, and must not make the patrol cry wolf.
    """
    out: dict[str, str] = {}
    for pattern in DECLARATION_GLOBS:
        for path in sorted(pkg.glob(pattern)):
            try:
                lines = path.read_text(encoding="utf-8").split("\n")
            except Exception:  # noqa: BLE001
                continue
            inside = False
            for line in lines:
                if line.startswith("#"):
                    inside = bool(_NOT_A_TABLE.match(line))
                    continue
                if inside:
                    for tbl in re.findall(r"`([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){2})`", line):
                        out.setdefault(tbl, path.name)
    return out


def load_rules(pkg: Path) -> dict[Path, str]:
    """The enforcement layer: validator code and prompt-rule prose."""
    out: dict[Path, str] = {}
    for pattern in RULES_GLOBS:
        for path in sorted(pkg.glob(pattern)):
            if path.name.startswith("__"):
                continue
            try:
                out[path] = path.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
    return out


# ==========================================================================
# Findings
# ==========================================================================

CHECKS = {
    1: ("INDEX vs SKILL", "told to use it, forbidden to use it"),
    2: ("SKILL vs FACT", "a declaration the warehouse denies"),
    3: ("INDEX vs FACT", "the agent is told something stale"),
    4: ("RULES vs SKILL", "decoration, or a rule with no source"),
    5: ("KNOWLEDGE vs all", "the map disagrees, or was never verified"),
}

# The four finding kinds of the original brief, now spread across five checks.
FAILING_KINDS = {
    "told-but-not-permitted",       # check 1 — the bug class
    "declared-but-nonexistent",     # check 2
    "told-about-nonexistent",       # check 3
    "contradictory-type",           # check 2, unless the declaration documents it
    "stale-version",                # check 2 — a newer member of the same family exists
}
# "existing-but-unplaced" (check 1) is a REPORT: an unplaced infrastructure
# table is fine, and a check that fails for acceptable reasons gets ignored.

DATE_LIKE = {"DATE", "TIMESTAMP", "TIMESTAMP_NTZ", "STRING"}
NUMERIC = {"INT", "LONG", "BIGINT", "SHORT", "BYTE", "DOUBLE", "FLOAT", "DECIMAL"}


@dataclass
class Finding:
    check: int
    kind: str
    subject: str
    detail: str
    evidence: str
    proposal: str

    @property
    def fails(self) -> bool:
        return self.kind in FAILING_KINDS


def _cols(catalog: dict, table: str) -> dict[str, str]:
    return {k.lower(): v for k, v in (catalog.get(table) or {}).items()}


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [str(value)] if value else []


# --- check 1 --------------------------------------------------------------


# --- table families and which member is current ---------------------------
#
# Some warehouses spell a version `v{major}r{minor}` — `movements_v2r0`,
# `geofences_v3r1`, `idle_events_v1r2` — alongside a `_latest` alias. Both
# forms coexist for the same stem, so "the table" is a family and a
# declaration picks one member of it.
#
# The owner's rule, and it is a rule about *intent* rather than about
# arithmetic: **`_latest` wins; otherwise the highest `v` then the highest
# `r` wins.** `_latest` is a promise the warehouse maintains, so a
# declaration naming it is asking to follow the warehouse rather than to
# freeze. A versioned name is the opposite request, and pointing at anything
# but the newest is then almost always an oversight.
#
# The allowlist blocks a stale table nobody declared. It cannot tell you the
# table you *did* declare has been superseded — that is what this finds, and
# it is why the check belongs to a patrol that sees the catalog over time
# rather than to a validator that sees one query (launch-readiness/89).
_VERSION_RE = re.compile(r"^(?P<stem>.+?)_(?:(?P<latest>latest)|v(?P<v>\d+)r(?P<r>\d+))$")


def _family(full_name: str):
    """Split `catalog.schema.table` into (family_key, rank) or None.

    rank sorts members: `_latest` above every version, then (v, r).
    A name matching neither form has no family and is left alone — inventing
    one would silently regroup unrelated tables, which is worse than the
    drift going unreported.
    """
    head, _, table = full_name.rpartition(".")
    m = _VERSION_RE.match(table)
    if not m:
        return None
    stem = m.group("stem")
    if m.group("latest"):
        rank = (1, 0, 0)
    else:
        rank = (0, int(m.group("v")), int(m.group("r")))
    return f"{head}.{stem}", rank


def stale_version_findings(catalog, declared) -> list["Finding"]:
    """A declared table with a newer sibling in the same family."""
    members: dict[str, list[tuple[tuple, str]]] = {}
    for name in catalog:
        fam = _family(name)
        if fam:
            members.setdefault(fam[0], []).append((fam[1], name))

    out: list[Finding] = []
    for name in sorted(declared):
        fam = _family(name)
        if not fam:
            continue
        siblings = members.get(fam[0], [])
        if not siblings:
            continue
        best_rank, best_name = max(siblings)
        if best_name == name:
            continue
        others = ", ".join(n for _, n in sorted(siblings, reverse=True) if n != name)
        out.append(Finding(
            check=2,
            kind="stale-version",
            subject=name,
            detail=(f"a newer member of this family exists — {best_name} — and the "
                    f"declaration still names {name}"),
            evidence=f"family {fam[0]}: {others or '(no siblings)'}",
            proposal=("confirm deliberately, then retarget or record why not. A newer "
                      "version may change grain, units or semantics, so this is a "
                      "decision and not a rename — the patrol will not make it."),
        ))
    return out


def check_index_vs_skill(catalog, index_named, declared, exempt) -> list[Finding]:
    out: list[Finding] = []
    for table, why in sorted(index_named.items()):
        if table in declared or table in exempt:
            continue
        hinted = any("usage_hint" in w for w in why)
        out.append(Finding(
            1, "told-but-not-permitted", table,
            "named by the index, permitted by no declaration"
            + (" — and named in a usage_hint, which is an instruction the agent follows literally"
               if hinted else ""),
            "; ".join(why[:4]),
            f"decide: is {table.split('.')[-1]} a dimension an existing declaration should join, "
            "or a fact table deserving its own? Then add it, by hand, to the declaration that "
            "owns it — or record it under '## Not a lens' with the reason.",
        ))
    unplaced = [t for t in sorted(catalog) if t not in declared and t not in exempt
                and t not in index_named]
    if unplaced:
        by_schema: dict[str, list[str]] = {}
        for t in unplaced:
            by_schema.setdefault(".".join(t.split(".")[:2]), []).append(t.split(".")[-1])
        out.append(Finding(
            1, "existing-but-unplaced", f"{len(unplaced)} tables",
            "exist in the catalog, named by no declaration and by no index row",
            "; ".join(f"{s}: {', '.join(n)}" for s, n in sorted(by_schema.items())),
            "no action required — an unplaced table is usually correct. Act only if a real "
            "user question needs one; record a permanent no under '## Not a lens' to stay quiet.",
        ))
    return out


# --- check 2 --------------------------------------------------------------

def _join_pairs(join: dict, catalog: dict, canonical: str):
    """Resolve `on: a.col = b.col` to (table, column, type) on both sides.
    Declarations write short table names, so short names are matched against
    the catalog's fully-qualified keys."""
    m = re.match(r"\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)",
                 str(join.get("on") or ""))
    if not m:
        return []
    short = {full.split(".")[-1]: full for full in catalog}
    lt, lc, rt, rc = m.groups()
    lf, rf = short.get(lt), short.get(rt)
    if not lf or not rf:
        return []
    return [((lf, lc, _cols(catalog, lf).get(lc.lower())),
             (rf, rc, _cols(catalog, rf).get(rc.lower())))]


def check_skill_vs_fact(pkg: Path, catalog, decls) -> list[Finding]:
    out: list[Finding] = []
    for d in decls:
        rel = str(d.path.relative_to(pkg))
        for t in sorted(d.tables()):
            if t not in catalog:
                out.append(Finding(
                    2, "declared-but-nonexistent", t,
                    f"declared by '{d.name}' but absent from the catalog", rel,
                    f"the table was renamed or dropped: correct or remove the declaration in "
                    f"{d.path.name}. Do not invent a replacement.",
                ))

        # A declared column may live on the canonical table OR on any table the
        # declaration joins — checking it against the canonical table alone
        # reports correct declarations as broken.
        reachable: dict[str, str] = {}
        for t in d.tables():
            for col, typ in (catalog.get(t) or {}).items():
                reachable.setdefault(col.lower(), typ)
        if not reachable:
            continue

        for key in ("date_columns", "join_axes", "resolve_before_filter", "quantity_column",
                    "default_date_column"):
            for col in _as_list(d.body.get(key)):
                if col.lower() not in reachable:
                    out.append(Finding(
                        2, "declared-but-nonexistent", f"{d.name}.{key}: {col}",
                        "declared, but no table this declaration reaches has that column", rel,
                        f"correct the column name in {d.path.name} against the catalog.",
                    ))

        canon = _cols(catalog, d.canonical_table)
        for col in _as_list(d.body.get("date_columns")):
            typ = canon.get(col.lower())
            if typ and typ.upper() not in DATE_LIKE:
                out.append(Finding(
                    2, "contradictory-type", f"{d.canonical_table}.{col}",
                    f"declared a date column by '{d.name}' but the catalog types it {typ}", rel,
                    "either the declaration is wrong, or the column needs a documented cast.",
                ))
        qc = d.body.get("quantity_column")
        if isinstance(qc, str) and qc:
            typ = canon.get(qc.lower())
            if typ and typ.upper() not in NUMERIC:
                out.append(Finding(
                    2, "contradictory-type", f"{d.canonical_table}.{qc}",
                    f"declared the quantity column by '{d.name}' but the catalog types it {typ}",
                    rel, "aggregating a non-numeric column needs a declared cast.",
                ))
        for j in d.joins:
            for (lf, lc, lt), (rf, rc, rt) in _join_pairs(j, catalog, d.canonical_table):
                if not (lt and rt) or lt.upper() == rt.upper():
                    continue
                # A mismatch the declaration ALREADY documents is a note, not a
                # failure. The team knows; the trap is written down; failing on
                # it would train everyone to ignore the patrol.
                documented = (lt.upper() in d.prose.upper() and rt.upper() in d.prose.upper()
                              and rf.split(".")[-1] in d.prose)
                out.append(Finding(
                    2, "documented-type-mismatch" if documented else "contradictory-type",
                    f"{lf.split('.')[-1]}.{lc} = {rf.split('.')[-1]}.{rc}",
                    f"'{d.name}' joins {lt} to {rt}"
                    + (" — already recorded as a trap in the declaration" if documented
                       else " — the equality is legal, but a value overflowing the narrower "
                            "type is silently lost, and nothing warns"),
                    rel,
                    "no action" if documented else
                    f"record the mismatch as a trap in {d.path.name}, or declare an explicit cast.",
                ))
    return out


# --- check 3 --------------------------------------------------------------

_INDEX_COLUMN_ID = re.compile(r"^([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+){2})\.([A-Za-z0-9_]+)\s")


def check_index_vs_fact(catalog, index_named, facts) -> tuple[list[Finding], str | None]:
    """The index describes something the warehouse no longer has.

    Column-level index rows identify themselves as `<table>.<column>`, so a
    column the index still describes but the catalog has dropped is
    checkable offline from the fixture as it stands.

    `sample_distinct_values` drift is NOT checkable here: the fixture records
    which tables the index names, not the body of each row. That is the
    package's generator's call, not this patrol's — the contract is stated in
    the skipped-checks note rather than papered over by a second capture path.
    """
    out: list[Finding] = []
    seen = 0
    for table, whys in sorted(index_named.items()):
        cols = _cols(catalog, table)
        for why in whys:
            m = _INDEX_COLUMN_ID.match(why)
            if not m or m.group(1) != table:
                continue
            seen += 1
            if m.group(2).lower() not in cols:
                out.append(Finding(
                    3, "told-about-nonexistent", f"{table}.{m.group(2)}",
                    "an index row describes this column; the catalog does not have it. "
                    "The agent is being told something stale, which is worse than being "
                    "told nothing.", why,
                    "re-run the index build for this table, or delete the row. The index is "
                    "the package owner's to correct — this patrol only reports it.",
                ))
    skipped = None
    if not facts.get("index_rows"):
        skipped = ("check 3 is partial: the fixture records which tables the index names, "
                   "not each row's body, so column-existence is checked and "
                   "`sample_distinct_values` drift is not. To complete it, the package's own "
                   "fixture generator should also emit `index_rows` (id, table_name, "
                   "column_name, sample_distinct_values). The patrol will not capture that "
                   "itself: one generator, one source of truth.")
    return out, skipped


# --- check 4 --------------------------------------------------------------

def check_rules_vs_skill(pkg: Path, rules, decls, declared, exempt, catalog) -> list[Finding]:
    """Both directions are findings. A declaration nothing checks is
    decoration; a check with no declaration behind it is a rule with no
    source."""
    out: list[Finding] = []
    if not rules:
        return out
    code = "\n".join(text for path, text in rules.items() if path.suffix == ".py")
    everything = "\n".join(rules.values())

    fields: dict[str, list[str]] = {}
    for d in decls:
        for key in d.body:
            fields.setdefault(key, []).append(d.name)
    for key, owners in sorted(fields.items()):
        if key in ("lens", "description"):
            continue
        if key not in everything:
            out.append(Finding(
                4, "declared-but-unenforced", key,
                f"declared by {len(owners)} declaration(s) ({', '.join(sorted(owners)[:4])}) "
                "and named nowhere in the rules layer — nothing enforces it",
                "no occurrence in the validator or the prompt rules",
                "either write the check, or drop the field. A declaration nothing checks is "
                "decoration, and it reads as a guarantee.",
            ))

    for table in sorted(set(_FQ_TABLE.findall(code))):
        if table not in catalog or table in declared or table in exempt:
            continue
        out.append(Finding(
            4, "enforced-but-undeclared", table,
            "named as a literal in the rules layer, but no declaration declares it — "
            "a rule with no source",
            "occurs in the validator code",
            "point the rule at the declarations instead of a hardcoded list, or add the "
            "declaration the rule is quietly assuming.",
        ))

    for table in sorted(declared):
        if table in catalog and table not in code and any(
                d.canonical_table == table for d in decls):
            out.append(Finding(
                4, "declared-but-unnamed-in-rules", table,
                "a canonical table no rules file names — expected when the rules read the "
                "declarations generically, a gap when they do not",
                "no literal occurrence in the rules layer",
                "confirm the rules resolve this table through the declarations rather than "
                "by name; no action if they do.",
            ))
    return out


# --- check 5 --------------------------------------------------------------

_PROVENANCE = re.compile(r"\*\*(UC|index|verified|lens|inferred)\*\*")


def check_knowledge(kpath: Path, catalog, declared, exempt) -> list[Finding]:
    """The map claims something the other four contradict, plus the two
    standing lists only this source can produce."""
    out: list[Finding] = []
    text = kpath.read_text(encoding="utf-8")
    lines = text.split("\n")

    short = {full.split(".")[-1]: full for full in catalog}
    catalog_schemas = {".".join(t.split(".")[:2]) for t in catalog}
    for i, line in enumerate(lines, 1):
        for tbl in _FQ_TABLE.findall(line):
            if tbl in catalog or tbl in exempt:
                continue
            if ".".join(tbl.split(".")[:2]) not in catalog_schemas:
                continue  # a name from some other system; not this warehouse's business
            if tbl.count(".") == 3:
                continue
            near = short.get(tbl.split(".")[-1])
            out.append(Finding(
                5, "knowledge-contradicts-fact", tbl,
                f"named in the map ({kpath.name}:{i}) but absent from the catalog",
                line.strip()[:110],
                f"correct the map{' — did it mean ' + near + '?' if near else ''}. "
                "The map is a claim about the warehouse; the warehouse wins.",
            ))

    inferred = [(i, l.strip()) for i, l in enumerate(lines, 1)
                if "**inferred**" in l and not l.startswith("|")]
    if inferred:
        out.append(Finding(
            5, "inferred-not-verified", f"{len(inferred)} claim(s)",
            "recorded in the map as reasoning, not checked. This is the standing to-do: an "
            "inference that quietly becomes load-bearing is how a hand-drawn coordinate box "
            "ends up upstream of a number a trader would act on.",
            "; ".join(f"{kpath.name}:{i}" for i, _ in inferred),
            "verify each with a query and re-tag it, or state in the map that it is still "
            "a hypothesis where it is used.",
        ))

    verified = [(i, l.strip()) for i, l in enumerate(lines, 1) if "**verified**" in l
                or re.search(r"\bverified\b\s+\d{4}-\d{2}-\d{2}", l, re.IGNORECASE)]
    # Only dates ON a verified line count. A first draft scanned the whole
    # document and reported the oldest date anywhere in it — which was a data
    # date from 2015, not a verification date. A patrol that reports a
    # frightening number for the wrong reason is a patrol people mute.
    dates = sorted({d for _, line in verified for d in re.findall(r"(20\d\d-\d\d-\d\d)", line)})
    if verified:
        age = ""
        if dates:
            try:
                oldest = date.fromisoformat(dates[0])
                age = f"; oldest verification date is {dates[0]} ({(date.today() - oldest).days}d ago)"
            except ValueError:
                pass
        out.append(Finding(
            5, "verified-needs-recheck", f"{len(verified)} claim(s)",
            "the map records these as verified by a query. This patrol runs offline and "
            "cannot re-run a SELECT, so it lists them rather than pretending to confirm them"
            + age,
            "; ".join(f"{kpath.name}:{i}" for i, _ in verified[:12]),
            "re-run these queries when the fixture is refreshed, and update the date beside "
            "each. A verified claim with a stale date is an inference wearing a badge.",
        ))
    return out


# ==========================================================================
# Reporting
# ==========================================================================


def render(pkg, fixture, kpath, facts, decls, exempt, rules, notes, skips, findings,
           quiet, skipped_checks=()) -> str:
    catalog = facts.get("catalog") or {}
    named = facts.get("index_named_tables") or {}
    L = [
        f"schema-patrol  {pkg}",
        "",
        "  sources found",
        f"    FACT       {fixture.relative_to(pkg)} — {len(catalog)} tables",
        f"    INDEX      {len(named)} tables named across {facts.get('index_row_count', '?')} "
        f"index rows (same fixture)",
        f"    KNOWLEDGE  {kpath if kpath else '— none found (check 5 skipped)'}",
        f"    SKILL      {len(decls)} declarations: {', '.join(sorted(d.name for d in decls))}",
        f"    RULES      {len(rules)} files: {', '.join(sorted(p.name for p in rules)) or '—'}",
        f"    exempt     {', '.join(sorted(t.split('.')[-1] for t in exempt)) or '—'}"
        " (placed as not-a-lens)",
        "",
    ]
    for n in notes + skips:
        L.append(f"  note: {n}")
    if notes or skips:
        L.append("")

    for chk in (1, 2, 3, 4, 5):
        hits = [f for f in findings if f.check == chk]
        fails = [f for f in hits if f.fails]
        # A skipped check prints "skip", never "ok". Silence about a skipped
        # check is the same defect this whole thing exists to prevent.
        verdict = "FAIL" if fails else ("note" if hits else
                                        ("skip" if chk in skipped_checks else "ok"))
        title, gloss = CHECKS[chk]
        L.append(f"[{verdict}] check {chk}  {title:<17} {gloss}")
        shown = fails if quiet else hits
        for f in shown:
            L.append(f"        - ({f.kind}) {f.subject}")
            L.append(f"          {f.detail}")
            L.append(f"          evidence: {f.evidence}")
            L.append(f"          proposed: {f.proposal}")
        if hits and quiet and not fails:
            L.append(f"        - {len(hits)} note(s) hidden by --quiet")
        if not hits:
            L.append("        - not run" if chk in skipped_checks else "        - none")
        L.append("")

    fails = [f for f in findings if f.fails]
    if fails:
        L.append(f"{len(fails)} failing finding(s). The patrol proposes; a human or an agent")
        L.append("with judgement disposes — nothing above has been written to any file.")
    else:
        L.append("Clean: the index tells the agent nothing the declarations forbid, every")
        L.append("declaration names something that exists, and the index describes no")
        L.append("column the warehouse has dropped. Remaining items are notes, for a reader.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile a data package's five descriptions "
                                             "of one warehouse against the warehouse.")
    ap.add_argument("package", help="path to the data package to patrol")
    ap.add_argument("--knowledge", help="path to the warehouse map (check 5); auto-discovered "
                                        "from docs/warehouse-map.md if not given")
    ap.add_argument("--refresh", action="store_true",
                    help="recapture the fixture via the PACKAGE'S generator first "
                         "(the only mode needing credentials)")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    ap.add_argument("--quiet", action="store_true", help="print failing findings only")
    args = ap.parse_args(argv)

    pkg = Path(args.package).expanduser().resolve()
    if not pkg.is_dir():
        print(f"schema-patrol: not a directory: {pkg}", file=sys.stderr)
        return 2

    fixture = find_fixture(pkg)
    if args.refresh:
        gen = find_generator(pkg, fixture)
        if not gen:
            print("schema-patrol: --refresh needs the package's own fixture generator "
                  "(a script that writes the fixture). Not found. The patrol does not "
                  "capture warehouse facts itself, by design: one generator, one source "
                  "of truth.", file=sys.stderr)
            return 2
        print(f"schema-patrol: refreshing via {gen.relative_to(pkg)}", file=sys.stderr)
        if subprocess.call([sys.executable, str(gen)], cwd=str(pkg)) != 0:
            print("schema-patrol: generator failed; fixture not refreshed", file=sys.stderr)
            return 2
        fixture = find_fixture(pkg)

    if not fixture:
        print(f"schema-patrol: no committed fixture under {pkg}. Run the package's fixture "
              f"generator (or --refresh) once and commit the result.", file=sys.stderr)
        return 2

    facts = json.loads(fixture.read_text(encoding="utf-8"))
    catalog = facts.get("catalog") or {}
    index_named = facts.get("index_named_tables") or {}
    decls, notes = load_declarations(pkg)
    if not decls:
        print(f"schema-patrol: no declaration blocks under {pkg}. Nothing to compare the "
              f"catalog against — a finding, but not one this script can grade.", file=sys.stderr)
        return 2
    exempt = load_exemptions(pkg)
    rules = load_rules(pkg)
    kpath = find_knowledge(pkg, args.knowledge)

    declared: dict[str, list[str]] = {}
    for d in decls:
        for t in d.tables():
            declared.setdefault(t, []).append(d.name)

    skips: list[str] = []
    skipped_checks: set[int] = set()
    findings = check_index_vs_skill(catalog, index_named, declared, exempt)
    findings += check_skill_vs_fact(pkg, catalog, decls)
    findings += stale_version_findings(catalog, declared)
    f3, skip3 = check_index_vs_fact(catalog, index_named, facts)
    findings += f3
    if skip3:
        skips.append(skip3)
    if not index_named:
        skips.append("checks 1 and 3 are inert: the fixture names no index tables.")
        skipped_checks.update({1, 3})
    if rules:
        findings += check_rules_vs_skill(pkg, rules, decls, declared, exempt, catalog)
    else:
        skips.append("check 4 skipped: no rules files found in this package.")
        skipped_checks.add(4)
    if kpath:
        findings += check_knowledge(kpath, catalog, declared, exempt)
    else:
        skips.append("check 5 skipped: no knowledge map found. Pass --knowledge <path> if "
                     "one exists outside the package.")
        skipped_checks.add(5)

    if args.json:
        print(json.dumps({
            "package": str(pkg),
            "fixture": str(fixture.relative_to(pkg)),
            "knowledge": str(kpath) if kpath else None,
            "notes": notes, "skipped": skips, "skipped_checks": sorted(skipped_checks),
            "findings": [{**f.__dict__, "fails": f.fails} for f in findings],
        }, indent=1))
    else:
        print(render(pkg, fixture, kpath, facts, decls, exempt, rules, notes, skips,
                     findings, args.quiet, skipped_checks))

    return 1 if any(f.fails for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
