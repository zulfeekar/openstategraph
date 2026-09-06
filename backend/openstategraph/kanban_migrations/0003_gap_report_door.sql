-- The keyless report door's own tables and its one write — team-board-and-gap-reports/09.
--
-- 0001 created the shared card table and 0002 said who may read it. This file
-- adds the three things a public, unauthenticated door needs and nothing else:
-- a place to count what a project has already sent, two columns on `cards` so
-- one gap reported forty times is one card with a count, and a single function
-- that does the whole write.
--
-- Idempotent by the same rules the first two files follow — `if not exists` on
-- the table, the columns and the indexes, a `pg_constraint` guard on the check
-- — because both appliers run every file every time they find it unrecorded.
--
-- **Why the write is one function rather than an insert from the door.**
-- The ticket asked for the choice to be argued rather than assumed, and the
-- honest argument is not the obvious one. It is *not* that a routine narrows
-- what the key can do: the caller holds the project's secret key either way,
-- and a secret key that may call this may also do everything else. What a
-- single routine buys is **atomicity across a network hop**. Rate-limit-then-
-- write is two statements, and a door that sends them as two requests has a
-- window between them in which a second request from the same project reads
-- the same counter — the check-then-write race the Postgres guidance names.
-- Here the counter's increment and the card's upsert are one statement each,
-- inside one transaction, decided by one round trip. The narrowing is real but
-- secondary: the door's code can express exactly one operation against this
-- database, so a later change to it cannot quietly grow a second.
--
-- `security definer` with `set search_path = ''`, and `execute` revoked from
-- `public` before it is granted to anything. A routine in this schema is
-- callable by every role the moment it exists — that default is the reason the
-- revoke is written before the grant rather than after it.

alter table public.cards
    add column if not exists finding_hash text not null default '';

-- The count the owner asked for: "repeats are one card with a count". One,
-- not zero, because a card exists because something was reported once.
alter table public.cards
    add column if not exists count integer not null default 1;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'cards_count_check'
          and conrelid = 'public.cards'::regclass
    ) then
        alter table public.cards
            add constraint cards_count_check check (count >= 1);
    end if;
end $$;

-- The dedup key, and it is partial on purpose: every card filed by any other
-- route carries the empty default, and a plain unique index would make the
-- second such card a conflict with the first. The predicate is repeated on the
-- `on conflict` clause below, which is how Postgres is told which partial
-- index to infer.
create unique index if not exists cards_project_finding_idx
    on public.cards (project_hash, finding_hash)
    where finding_hash <> '';

-- How much a project may send in a window, and how wide the window is. Named
-- here rather than at the door: a limit that lives in the caller is a limit
-- the next caller gets to choose for itself.
create table if not exists public.gap_report_rate (
    project_hash text not null,
    window_start timestamptz not null,
    count integer not null default 0,
    primary key (project_hash, window_start)
);

-- The natural key is the key — `(project_hash, window_start)` is what every
-- statement here addresses and what the upsert conflicts on — so there is no
-- surrogate id, and the primary key is the only index this table has. The
-- retention job (10) sweeps by `window_start`; at one row per project per
-- window that is a scan of a table measured in hundreds of rows, and a second
-- index would cost every write to save a query nobody has measured.

alter table public.gap_report_rate enable row level security;
alter table public.gap_report_rate force row level security;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke all on table public.gap_report_rate from anon;
    end if;

    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke all on table public.gap_report_rate from authenticated;
    end if;
end $$;

-- No policy for either role, and none is coming: nobody but the routine below
-- has a reason to read another project's send counter, and the routine reads
-- it as its owner. RLS is on and forced anyway, so the table fails closed for
-- every role that is not the owner rather than relying on the absence of a
-- grant.

create or replace function public.file_gap_report(
    p_project_hash text,
    p_finding_hash text,
    p_kind text,
    p_title text,
    p_story text,
    p_window_seconds integer default 3600,
    p_window_limit integer default 20
)
returns table (outcome text, card_count integer, window_count integer)
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_now timestamptz := clock_timestamp();
    v_window timestamptz;
    v_filed text;
    v_sent integer;
    v_count integer;
begin
    v_window := to_timestamp(
        floor(extract(epoch from v_now) / p_window_seconds) * p_window_seconds
    );
    v_filed := to_char(v_now at time zone 'UTC', 'YYYY-MM-DD')
        || 'T'
        || to_char(v_now at time zone 'UTC', 'HH24:MI:SS.US')
        || '+00:00';

    insert into public.gap_report_rate as rate (project_hash, window_start, count)
    values (p_project_hash, v_window, 1)
    on conflict (project_hash, window_start)
        do update set count = rate.count + 1
    returning rate.count into v_sent;

    if v_sent > p_window_limit then
        return query select 'rate-limited'::text, 0, v_sent;
        return;
    end if;

    insert into public.cards as card (
        task_id, project_hash, board, kind, category, title, story,
        finding_hash, count, priority, area, filed_at
    )
    values (
        'gap-reports:' || left(p_project_hash, 12) || '-' || p_finding_hash,
        p_project_hash,
        'gap-reports',
        p_kind,
        'gap',
        p_title,
        p_story,
        p_finding_hash,
        1,
        'med',
        'backend',
        v_filed
    )
    on conflict (project_hash, finding_hash) where finding_hash <> ''
        do update set count = card.count + 1
    returning card.count into v_count;

    return query select
        case when v_count = 1 then 'filed' else 'counted' end,
        v_count,
        v_sent;
end;
$$;

-- `task_id` is derived from the two hashes rather than minted, so the same gap
-- from the same install is the same row whether it arrives once or a thousand
-- times, and a re-send after the retention job has swept the card files it
-- again under the id it had. Twelve characters of the project hash is the
-- width this project already reads in an id; the finding hash is already
-- twelve.
--
-- `updated_at` is not set here. The trigger 0001 installs owns it, which is
-- the whole reason that trigger exists — a write that has to remember a
-- watermark is a write that will one day forget it.

revoke all on function public.file_gap_report(
    text, text, text, text, text, integer, integer
) from public;

do $$
begin
    if exists (select 1 from pg_roles where rolname = 'service_role') then
        grant execute on function public.file_gap_report(
            text, text, text, text, text, integer, integer
        ) to service_role;
    end if;
end $$;

-- Guarded like the role blocks in 0002, and for the same reason: these files
-- are ordinary Postgres, and a stranger running them against their own
-- database has no such role. The revoke above is not guarded because `public`
-- exists everywhere — and it must run even where the grant does not, or the
-- routine would be left callable by every role on that install.
