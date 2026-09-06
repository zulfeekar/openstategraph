// The second report door — team-board-and-gap-reports/09.
//
// An install with no `gh` and no GitHub account still meets platform gaps, and
// the first door (08) is unreachable for it. This is the other one: a public
// endpoint that accepts exactly the schema `docs/gap-report.schema.json`
// publishes, drops what it does not know, refuses what it knows is wrong, and
// writes one card per distinct finding with a count.
//
// Six properties, each of which is the reason a clause below exists:
//
//   * **Public by declaration.** `verify_jwt = false` is written in
//     `config.toml` with its argument, because a reporting install holds no
//     credential of ours and cannot be asked for one. Everything else here is
//     the answer to the warning that comes with that.
//   * **Refused by length before it is parsed.** A body over the cap is
//     rejected on `content-length`, and again on the bytes actually read,
//     because a header is a claim.
//   * **Tolerant in reading, strict in trusting** (CLAUDE.md). A field this
//     door does not know is dropped rather than refused, so an older or newer
//     client still gets through; a field it knows and cannot accept is a
//     refusal, and nothing outside the allowlist ever reaches the database.
//   * **Rate limited per hashed project id**, in the same statement that
//     increments the counter, so there is no check-then-write race.
//   * **Deduplicated by finding hash**, so a gap reported forty times is one
//     card carrying forty rather than forty cards.
//   * **Nothing of the body is ever logged.** Counts, outcomes and reject
//     reasons only — a reject reason is one of the fixed strings below, never
//     a value out of the request.
//
// The vocabulary is generated (`contract.generated.ts`); the checking is
// written here. That split is deliberate: a validator generated from a schema
// is a schema library, and this door has no dependencies at all — not even a
// client for the database it writes to, which it reaches over the REST
// interface the platform already exposes.

import { CONTRACT } from "./contract.generated.ts";

/** The most a report may weigh. The largest a valid one can be is a few
 * hundred bytes — every field is capped and there are twelve of them — so this
 * is not a limit anybody honest meets. It exists so that an oversized body
 * costs a length check rather than a parse. */
const BODY_CAP_BYTES = 16 * 1024;

/** How much of a hash is a hash. A project id arrives as a full SHA-256 and a
 * finding hash as the twelve characters the model publishes; both are checked
 * for shape here rather than trusted, because they are what the rate limit and
 * the dedup are keyed on. */
const PROJECT_HASH = /^[0-9a-f]{64}$/;
const FINDING_HASH = /^[0-9a-f]{8,64}$/;

/** The kill switch. A function secret, so it takes effect on the next request
 * without a redeploy or a DNS change — which is the point of it: the day this
 * door has to be closed is not a day to be waiting on a build. */
const DISABLED_ENV = "GAP_REPORT_DISABLED";

/** The two the platform pre-populates. `SUPABASE_SERVICE_ROLE_KEY` is the
 * legacy name for the secret key and is the one present on this project; it is
 * read from the function's own environment and appears in no response, no log
 * line and nothing that ships in the package. */
const URL_ENV = "SUPABASE_URL";
const KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY";

/** Every reason this door refuses, as a closed set. A reject reason is logged,
 * so it must be a string chosen here and never one assembled out of the
 * request — that is the whole no-body-logging rule, expressed as a type
 * rather than as a habit. */
type Reason =
  | "method-not-allowed"
  | "too-large"
  | "not-json"
  | "not-an-object"
  | "missing-required-field"
  | "wrong-type"
  | "unknown-enum-value"
  | "text-too-long"
  | "not-a-hash"
  | "rate-limited"
  | "not-configured"
  | "database-refused";

interface Report {
  [field: string]: string | string[] | null | { source: string; text: string };
}

interface Checked {
  report: Report;
  dropped: number;
}

/** What came back, in the two shapes a caller may see. Named here because the
 * Python client (`gap_report_client.py`) types the same two. */
interface Accepted {
  outcome: "filed" | "counted";
  count: number;
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function refuse(reason: Reason, status: number): Response {
  console.log(`gap-report refused: ${reason}`);
  return json({ outcome: "refused", reason }, status);
}

function textOk(value: string): boolean {
  return value.length <= CONTRACT.textCap;
}

/** The report, or the first reason it is not one.
 *
 * Unknown fields are counted and dropped — the count is logged, the names are
 * not, because a field name in an unknown payload is content. Known fields are
 * checked against the shape the generator derived from the model.
 */
function check(payload: unknown): Checked | Reason {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    return "not-an-object";
  }
  const source = payload as Record<string, unknown>;
  const fields = CONTRACT.fields as Record<string, { kind: string; values?: readonly string[] }>;
  const report: Report = {};
  let dropped = 0;

  for (const [name, value] of Object.entries(source)) {
    const shape = fields[name];
    if (shape === undefined) {
      dropped += 1;
      continue;
    }
    switch (shape.kind) {
      case "string": {
        if (typeof value !== "string") return "wrong-type";
        if (!textOk(value)) return "text-too-long";
        report[name] = value;
        break;
      }
      case "nullableString": {
        if (value === null) {
          report[name] = null;
          break;
        }
        if (typeof value !== "string") return "wrong-type";
        if (!textOk(value)) return "text-too-long";
        report[name] = value;
        break;
      }
      case "enum": {
        if (typeof value !== "string") return "wrong-type";
        if (!(shape.values ?? []).includes(value)) return "unknown-enum-value";
        report[name] = value;
        break;
      }
      case "stringArray": {
        if (!Array.isArray(value)) return "wrong-type";
        for (const item of value) {
          if (typeof item !== "string") return "wrong-type";
          if (!textOk(item)) return "text-too-long";
        }
        report[name] = value as string[];
        break;
      }
      case "refusal": {
        if (value === null || typeof value !== "object" || Array.isArray(value)) {
          return "wrong-type";
        }
        const refusal = value as Record<string, unknown>;
        for (const required of CONTRACT.refusalRequired) {
          if (!(required in refusal)) return "missing-required-field";
        }
        const src = refusal.source;
        const text = refusal.text;
        if (typeof src !== "string" || typeof text !== "string") return "wrong-type";
        if (!(CONTRACT.refusalSources as readonly string[]).includes(src)) {
          return "unknown-enum-value";
        }
        if (!textOk(text)) return "text-too-long";
        // Rebuilt from the two fields the contract names rather than passed
        // through, so an extra key inside the refusal is dropped exactly the
        // way an extra key beside it is.
        dropped += Object.keys(refusal).length - CONTRACT.refusalFields.length;
        report[name] = { source: src, text };
        break;
      }
      default:
        return "wrong-type";
    }
  }

  for (const required of CONTRACT.required) {
    if (!(required in report)) return "missing-required-field";
  }
  if (!PROJECT_HASH.test(report.project_hash as string)) return "not-a-hash";
  if (!FINDING_HASH.test(report.finding_hash as string)) return "not-a-hash";
  return { report, dropped };
}

/** What the card says, out of the report and nothing else.
 *
 * Every line is an allowlisted field, so a card carries exactly what the
 * reporter read before they sent it — which is the promise
 * `docs/reporting-a-platform-gap.md` makes, kept on this side of the wire too.
 */
function title(report: Report): string {
  const ids = report.type_ids as string[] | undefined;
  const subject = ids && ids.length > 0 ? ids.join(", ") : String(report.door);
  return `${report.kind}: ${subject}`.slice(0, 200);
}

function story(report: Report): string {
  const lines: string[] = [];
  for (const name of Object.keys(CONTRACT.fields)) {
    const value = report[name];
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      if (value.length === 0) continue;
      lines.push(`${name}: ${value.join(", ")}`);
    } else if (typeof value === "object") {
      lines.push(`${name}: ${value.source} · ${value.text}`);
    } else {
      lines.push(`${name}: ${value}`);
    }
  }
  return lines.join("\n").slice(0, 2000);
}

/** The one operation this door performs against the database.
 *
 * A routine call rather than an insert, and the argument is in the migration:
 * the rate-limit increment and the card upsert are one transaction and one
 * round trip, so there is no window between counting and writing.
 */
async function file(report: Report): Promise<Accepted | Reason> {
  const base = Deno.env.get(URL_ENV);
  const key = Deno.env.get(KEY_ENV);
  if (!base || !key) return "not-configured";

  const response = await fetch(`${base}/rest/v1/rpc/file_gap_report`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      apikey: key,
      authorization: `Bearer ${key}`,
    },
    body: JSON.stringify({
      p_project_hash: report.project_hash,
      p_finding_hash: report.finding_hash,
      p_kind: "task",
      p_title: title(report),
      p_story: story(report),
    }),
  });
  if (!response.ok) {
    // The status, never the body: an error body from the database can quote
    // the statement, and the statement carries the report.
    console.log(`gap-report database refused with status ${response.status}`);
    return "database-refused";
  }
  const rows = await response.json();
  const row = Array.isArray(rows) ? rows[0] : rows;
  if (!row || row.outcome === "rate-limited") return "rate-limited";
  return { outcome: row.outcome, count: Number(row.card_count) };
}

export async function handle(request: Request): Promise<Response> {
  if (Deno.env.get(DISABLED_ENV) === "1") {
    console.log("gap-report is closed by its kill switch");
    return json({ outcome: "closed" }, 503);
  }
  if (request.method !== "POST") return refuse("method-not-allowed", 405);

  const declared = Number(request.headers.get("content-length") ?? "0");
  if (declared > BODY_CAP_BYTES) return refuse("too-large", 413);

  const bytes = new Uint8Array(await request.arrayBuffer());
  // Again on what actually arrived: a `content-length` is a claim, and a
  // chunked request makes no claim at all.
  if (bytes.byteLength > BODY_CAP_BYTES) return refuse("too-large", 413);

  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return refuse("not-json", 400);
  }

  const checked = check(payload);
  if (typeof checked === "string") return refuse(checked, 400);
  console.log(
    `gap-report accepted a report of ${bytes.byteLength} bytes; ` +
      `${checked.dropped} unknown field(s) dropped`,
  );

  const written = await file(checked.report);
  if (typeof written === "string") {
    return refuse(written, written === "rate-limited" ? 429 : 502);
  }
  // The board is named from the generated contract, never spelled here —
  // `team-board-and-gap-reports/17`. This door does not *choose* where a
  // report lands: the database routine is the single writer, for the
  // atomicity argument `0003` records, and the board comes from that table's
  // column default. What it must not do is describe the landing in its own
  // words: `09` and `04` were each internally consistent and disagreed by one
  // literal, which is how the first live report came to sit on a board no tab
  // lists. `CONTRACT.board` is emitted from `kanban_store.TEAM_BOARD` and
  // pinned against the SQL default, so a log line that says a board the row
  // is not on is a red test rather than an hour.
  console.log(
    `gap-report ${written.outcome} onto ${CONTRACT.board}; ` +
      `this finding now counts ${written.count}`,
  );
  return json(written, 200);
}

Deno.serve(handle);
