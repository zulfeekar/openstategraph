-- Row security on the migration ledger — team-board-and-gap-reports/14.
--
-- The security advisor the maintainers run against the owner's project before
-- each migration is committed, the moment 0003 landed:
--
--     ERROR rls_disabled_in_public — Table `public.kanban_schema_migrations`
--     is public, but RLS has not been enabled.
--
-- 0002 enabled and forced RLS on `cards`; 0003 did the same for
-- `gap_report_rate` in the file that created it, so the advisor names neither.
-- The ledger is the one table no migration file creates: the runner creates it
-- itself, in `_migrate`, because it has to exist before the runner can read
-- which files this database has already had applied. Nothing that reads
-- `*.sql` could see it, which is why it was the exception nobody wrote down
-- rather than a decision anybody made. It is exposed through PostgREST to
-- `anon` like every other table in `public`, and what it exposes is the shape
-- of this schema's history.
--
-- **No policy, for either role, and none is coming.** Nobody outside the owner
-- role has a reason to read what version a shared board is at. `enable` alone
-- would leave the table owner exempt, so `force` is here too — the same pair
-- 0002 and 0003 use, and the pair `test_every_table_the_board_creates_has_row_security`
-- now requires of every table this package puts in `public`.
--
-- **The `create table` below is deliberate and is not a second schema.** These
-- files have two appliers: this package's runner, and the maintainers' CLI
-- pointed at the same directory by the symlink at the repository root. The
-- runner always creates the ledger before it applies anything, so there the
-- statement is a no-op. The CLI does not — it records into its *own* ledger —
-- so on a database only ever pushed to with the CLI, `alter table` alone would
-- fail on a relation that is not there, and the migration that fixes the
-- advisor's finding would be the one migration that cannot be pushed. Creating
-- it first makes the file true from either applier, and the column list is
-- pinned against the runner's own `create` so the two cannot drift into two
-- shapes of one table.
--
-- **What this costs, said plainly.** The runner writes this table on every
-- open. A forced table with no policies is readable and writable by nothing
-- but a `bypassrls` role, so the claim that the store still works rests
-- entirely on `OPENSTATEGRAPH_KANBAN_URL` naming an owner-level role — which
-- it does on a managed Postgres, and which is the same thing 0002's own
-- commentary already depends on. That is a property of a database and not of a
-- file, so it is asserted against one: the opt-in live test in
-- `test_every_table_the_board_creates_has_row_security` opens a real store
-- twice through this and fails if the second open cannot read the ledger back.

create table if not exists public.kanban_schema_migrations (
    version text primary key,
    applied_at timestamptz not null default now()
);

alter table public.kanban_schema_migrations enable row level security;
alter table public.kanban_schema_migrations force row level security;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all on table public.kanban_schema_migrations from anon;
    end if;

    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all on table public.kanban_schema_migrations from authenticated;
    end if;
end $$;

-- Guarded on `pg_roles` like the blocks in 0002 and 0003, and for the reason
-- those give: these files are ordinary Postgres, and a stranger running them
-- against their own database has no such roles. Without the guard the whole
-- migration fails there, which would make "plain SQL anyone can run" untrue.
