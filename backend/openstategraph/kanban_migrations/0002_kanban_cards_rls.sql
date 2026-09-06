-- Row level security on the shared card table — team-board-and-gap-reports/03.
--
-- Separate from 0001 on purpose: the schema and who may read it are two
-- changes, and a reviewer reading a policy wants to read only policies.
--
-- **What actually connects today, so the policies are not read as more than
-- they are.** The maintainer's own store connects with the URL in
-- `OPENSTATEGRAPH_KANBAN_URL`, which on a managed Postgres is an owner-level
-- role. That role has `bypassrls`, so it is not subject to a single line
-- below — `force row level security` closes the table-owner exemption, it does
-- not close `bypassrls`, and nothing can. The store scopes every statement it
-- writes with `project_hash = %s` of its own accord for that reason.
--
-- So these policies are the floor for every *other* reader: the second door
-- for an install with no `gh` (09), and the separate read accounts a rotation
-- story needs (10). A reader arriving through one of those declares which
-- project it is by setting `app.project_hash` on its connection and sees that
-- project's rows and no others. A reader that declares nothing sees nothing,
-- which is the safe direction to fail in.
--
-- The role guards are not ceremony: these files are ordinary Postgres and a
-- stranger running them against their own database has no `anon` and no
-- `authenticated` role. Without the guard the whole migration fails there,
-- which would make "plain SQL anyone can run" untrue.

alter table public.cards enable row level security;
alter table public.cards force row level security;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        -- No policy and no grant. Insert-only for a gap report arrives with
        -- its own migration (09); until then this is said rather than left to
        -- whatever the platform's default happens to be this month.
        revoke all on table public.cards from anon;
    end if;

    if not exists (select 1 from pg_roles where rolname = 'authenticated') then
        return;
    end if;

    grant select, insert, update on table public.cards to authenticated;

    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'cards'
          and policyname = 'cards_project_select'
    ) then
        create policy cards_project_select on public.cards
            for select
            to authenticated
            using (
                project_hash = (select nullif(current_setting('app.project_hash', true), ''))
            );
    end if;

    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'cards'
          and policyname = 'cards_project_insert'
    ) then
        create policy cards_project_insert on public.cards
            for insert
            to authenticated
            with check (
                project_hash = (select nullif(current_setting('app.project_hash', true), ''))
            );
    end if;

    -- `using` and `with check` both, and the second one is the load-bearing
    -- half: without it a reader that may update its own rows may hand one to
    -- another project by rewriting `project_hash`.
    if not exists (
        select 1 from pg_policies
        where schemaname = 'public'
          and tablename = 'cards'
          and policyname = 'cards_project_update'
    ) then
        create policy cards_project_update on public.cards
            for update
            to authenticated
            using (
                project_hash = (select nullif(current_setting('app.project_hash', true), ''))
            )
            with check (
                project_hash = (select nullif(current_setting('app.project_hash', true), ''))
            );
    end if;
end $$;

-- No delete policy and no delete grant, for either role. Retention is a job
-- that runs as the owner (09/10), and a board where a reader can remove a card
-- is a board that cannot be trusted to still hold what was filed.
