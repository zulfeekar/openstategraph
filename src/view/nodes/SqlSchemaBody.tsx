import { useEffect, useState } from 'react';
import { WorkflowFileClient, type SqlSource } from '@core/runtime/WorkflowFileClient';
import { CURRENT_SLUG_KEY } from '@app/workflowFileWatch';
import type { NodeBodyProps } from './nodeBodyRegistry';
import './SqlSchemaBody.css';

/**
 * The schema card's body: every table this tool can reach, from the database.
 *
 * **What this replaces.** The card carried a `Table` select — eleven Chinook
 * table names typed into a TypeScript file, defaulting to `Artist`. It
 * configured nothing (the tool takes `table` as a *model* argument and
 * declares no `configure()`), so it only told the reader something false. The
 * owner's objection was exactly right, and the second half of it is the part
 * worth building: the schema should be visible **as the source of truth**, as
 * the agent sees it — all the tables, and it picks.
 *
 * So this is a read, never a control. Nothing here writes to the node; there
 * is no value to save; expanding a table shows the same columns-and-foreign-
 * keys text the runtime tool returns, produced from the same file by the same
 * engine adapter (`GET /api/workflows/{slug}/sql-schema`).
 *
 * **Cost.** A card re-renders on every drag, so the fetch is coalesced per
 * slug — one request shared by every schema card on the canvas, the pattern
 * `CompositionBody` established. Table details ride along in that one
 * response, so expanding costs nothing; a database wide enough for that to
 * matter is capped by the endpoint, which says so rather than truncating
 * silently.
 */
export function SqlSchemaBody(_props: NodeBodyProps) {
  const slug = openSlug();
  const [state, setState] = useState<SchemaState>(() =>
    slug ? (CACHE.get(slug)?.settled ?? { status: 'loading' }) : { status: 'loading' },
  );
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let live = true;
    void resolveSchema(slug).then((next) => {
      if (live) setState(next);
    });
    return () => {
      live = false;
    };
  }, [slug]);

  // An unsaved workflow has no slug to ask about, and a card that guessed
  // would be the old lie in a new place.
  if (!slug) {
    return <div className="sql-schema__note">Save this workflow to see its tables.</div>;
  }
  if (state.status === 'loading') {
    return <div className="sql-schema__note">reading the database…</div>;
  }
  if (state.status === 'failed') {
    return (
      <div className="sql-schema__note" role="note">
        {state.message}
      </div>
    );
  }
  if (state.sources.length === 0) {
    return <div className="sql-schema__note">No database is wired to this workflow.</div>;
  }

  return (
    <div className="sql-schema" data-no-drag>
      {state.sources.map((source) => (
        <SourceView
          key={source.database}
          source={source}
          open={open}
          onToggle={(name) => setOpen((current) => (current === name ? null : name))}
        />
      ))}
    </div>
  );
}

function SourceView({
  source,
  open,
  onToggle,
}: {
  source: SqlSource;
  open: string | null;
  onToggle: (table: string) => void;
}) {
  const detail = source.tables.find((table) => table.name === open)?.detail ?? '';
  const count = source.tables.length;

  return (
    <>
      <div className="sql-schema__summary">
        {count} table{count === 1 ? '' : 's'}, all visible to the agent — it picks
      </div>
      <div className="sql-schema__source" title={source.database}>
        {source.database}
      </div>
      <ul className="sql-schema__tables">
        {source.tables.map((table) => (
          <li key={table.name}>
            <button
              type="button"
              className="sql-schema__table"
              aria-pressed={open === table.name}
              title={`Columns and foreign keys of ${table.name}`}
              onClick={() => onToggle(table.name)}
            >
              {table.name}
            </button>
          </li>
        ))}
      </ul>
      {detail ? <pre className="sql-schema__detail">{detail}</pre> : null}
      {source.warning ? (
        <div className="sql-schema__note" role="note">
          {source.warning}
        </div>
      ) : null}
    </>
  );
}

/* ================================================================== *
 * Per-slug cache
 * ================================================================== */

type SchemaState =
  | { status: 'loading' }
  | { status: 'ready'; sources: readonly SqlSource[] }
  | { status: 'failed'; message: string };

interface CacheEntry {
  readonly inFlight: Promise<SchemaState>;
  settled?: SchemaState;
}

/**
 * One request per slug, shared by every schema card on the canvas.
 *
 * A failure is not cached: an unreachable runtime is not a fact about the
 * document, so it must retry rather than stick.
 */
const CACHE = new Map<string, CacheEntry>();

function resolveSchema(slug: string): Promise<SchemaState> {
  const existing = CACHE.get(slug);
  if (existing) return existing.inFlight;

  const inFlight = new WorkflowFileClient().sqlSchema(slug).then((result): SchemaState => {
    if (!result.ok) {
      CACHE.delete(slug);
      return { status: 'failed', message: result.error };
    }
    return { status: 'ready', sources: result.value };
  });

  const entry: CacheEntry = { inFlight };
  CACHE.set(slug, entry);
  void inFlight.then((settled) => {
    entry.settled = settled;
  });
  return inFlight;
}

function openSlug(): string | null {
  return typeof sessionStorage === 'undefined' ? null : sessionStorage.getItem(CURRENT_SLUG_KEY);
}
