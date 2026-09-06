-- The shared card table — team-board-and-gap-reports/03.
--
-- Applied two ways and they must be the same bytes: `PostgresKanbanStore`
-- runs the files in this directory when it opens, and the maintainers' own
-- migration CLI is pointed at the same directory by a symlink at the
-- repository root. Every statement is therefore idempotent — `if not exists` on the
-- table and the indexes, a `pg_constraint` guard on each `check` (Postgres has
-- no `add constraint if not exists`), a `pg_trigger` guard on the trigger.
--
-- Types, and the one place this deliberately differs from the rule:
--
--   * `text`, never `varchar(n)`.
--   * `boolean` for `evidence_green`, which is an `INTEGER` in the SQLite
--     store and a `bool` on a `Card` either way.
--   * `text[]` for `blocked_by`, not `jsonb`. Both would work; an array cannot
--     hold anything but a list of text, which is precisely the shape the
--     SQLite store's `_decode_blocked_by` has to be tolerant about because its
--     column is JSON in a `TEXT`. The tolerance stays there; there is nothing
--     for it to forgive here.
--   * `filed_at`, `last_heartbeat_at` and `answered_at` stay `text`, holding
--     the same ISO-8601 UTC string `now_iso()` writes today. They are fields
--     of a `Card`, and a card must read identically out of either store — a
--     `timestamptz` here would mean one vocabulary on a laptop and another on
--     the shared board, with the conversion between them a place to lose a
--     value. `updated_at` is the one genuine instant, maintained by the
--     database rather than by a caller, and it is `timestamptz`.

create table if not exists public.cards (
    task_id text primary key,
    project_hash text not null,
    board text not null,
    kind text not null,
    category text not null,
    title text not null,
    stage text not null default 'unattended',
    actor text,
    last_heartbeat_at text,
    priority text not null default 'med',
    area text not null default 'backend',
    priority_reason text not null default '',
    filed_at text not null default '',
    evidence_test_id text not null default '',
    evidence_red_reason text not null default '',
    evidence_green boolean not null default false,
    evidence_commit text not null default '',
    answer text not null default '',
    answered_by text not null default '',
    answered_at text not null default '',
    story text not null default '',
    done_when text not null default '',
    blocked_by text[] not null default '{}',
    agent_model text not null default '',
    agent_effort text not null default '',
    finished_reason text not null default '',
    updated_at timestamptz not null default now()
);

-- `task_id` stays the primary key, and that is a decision against the rule
-- rather than an oversight of it. The Postgres guidance prefers
-- `bigint generated always as identity` and warns that a random UUIDv4
-- fragments the index; `task_id` is neither — it is a natural key
-- (`<project_id>:idea-<slug>`) that both stores have to agree on, because a
-- card filed on a laptop and the same card on the shared board are one card.
-- At the size this table is (tens to hundreds of rows per project; seven on
-- the board this was written against) index locality is worth less than one
-- id. Revisit above roughly a million rows.

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'cards_stage_check'
          and conrelid = 'public.cards'::regclass
    ) then
        alter table public.cards
            add constraint cards_stage_check
            check (stage in ('unattended', 'attended', 'red', 'green', 'finished'));
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'cards_priority_check'
          and conrelid = 'public.cards'::regclass
    ) then
        alter table public.cards
            add constraint cards_priority_check
            check (priority in ('high', 'med', 'low'));
    end if;

    if not exists (
        select 1 from pg_constraint
        where conname = 'cards_area_check'
          and conrelid = 'public.cards'::regclass
    ) then
        alter table public.cards
            add constraint cards_area_check
            check (area in ('ui', 'ux', 'frontend', 'backend', 'test', 'docs'));
    end if;
end $$;

-- Every board read is "this project, this tab, these columns" — the equality
-- columns first, per the composite rule, and `project_hash` leftmost because
-- no query this store makes ever omits it.
create index if not exists cards_project_board_stage_idx
    on public.cards (project_hash, board, stage);

-- The watermark the open board polls: `max(updated_at)` for one project. The
-- descending order is the read, and this index is also the one the RLS policy
-- below needs on its own predicate column.
create index if not exists cards_project_updated_idx
    on public.cards (project_hash, updated_at desc);

-- `updated_at` is maintained here rather than by callers, so a write that
-- forgets it is not a thing anybody can do. `security invoker` is the default
-- and is stated: a trigger has no reason to run with the creator's rights, and
-- `security definer` is how a helper quietly becomes a way around RLS.
create or replace function public.cards_set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

do $$
begin
    if not exists (
        select 1 from pg_trigger
        where tgname = 'cards_set_updated_at'
          and tgrelid = 'public.cards'::regclass
    ) then
        create trigger cards_set_updated_at
            before update on public.cards
            for each row execute function public.cards_set_updated_at();
    end if;
end $$;
