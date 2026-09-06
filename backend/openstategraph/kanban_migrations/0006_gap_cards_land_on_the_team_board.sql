-- The keyless door files onto a board a tab reads — team-board-and-gap-reports/17.
--
-- `0003` wrote every filed report onto `board = 'gap-reports'`. `04` had, in
-- the same hour, fixed the boards a card can be on — `kanban_store.BOARD_IDS`
-- — and `GET /api/kanban/cards` refuses anything outside that tuple by name.
-- Both were internally consistent and together they put the first live report
-- in a row no tab lists and no API call can return.
--
-- Three things here, and the third is the one that stops this recurring.
--
-- **The rows already filed are moved.** A default fixes the next card and
-- says nothing about the one the owner asked to see. The `update` names both
-- boards explicitly rather than moving everything: a card another route filed
-- onto the local board is not this door's to relocate.
--
-- **The routine stops naming a board at all.** It is replaced, not corrected:
-- an `insert` that lists `board` and a column default are two answers to one
-- question, and the one that loses is whichever a later reader does not open.
-- With the column out of the insert list there is exactly one board literal
-- in this whole directory, and it is the default below.
--
-- **That literal is pinned to the Python constant it publishes.** SQL imports
-- nothing, so the three spellings — `kanban_store.TEAM_BOARD`, the generated
-- contract the keyless door reads (emitted from it, because that door is a
-- Deno function and cannot import a Python module), and this default — are
-- made one fact by
-- `tests/test_the_keyless_door_files_onto_a_board_a_tab_reads.py` rather than
-- by an import that cannot exist. That is the same answer this directory
-- already gives for the `check` constraints, for the same stated reason: a
-- file the maintainers' migration CLI sends must be the bytes we applied.
--
-- Additive and idempotent, the rule every file here follows. Nothing is
-- dropped: `create or replace` keeps the routine's identity, its signature
-- and the grants `0003` set on it, so no window exists in which the door has
-- no function to call.

alter table public.cards
    alter column board set default 'osgEngineering';

update public.cards
    set board = 'osgEngineering'
    where board = 'gap-reports';

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
        task_id, project_hash, kind, category, title, story,
        finding_hash, count, priority, area, filed_at
    )
    values (
        'gap-reports:' || left(p_project_hash, 12) || '-' || p_finding_hash,
        p_project_hash,
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

-- `board` is absent from that column list on purpose — the default above is
-- what fills it, and it is the only board literal these files contain now.
-- The `task_id` prefix is unchanged and is not a board: it is the id
-- namespace `0003` minted, and a card whose id moved is a card the retention
-- job and every re-send would file twice.
--
-- `category` stays a literal here because it is not a board id and no tab
-- reads it — it is what the card *is*, published to the door as
-- `CONTRACT.category` from `gap_report.GAP_CARD_CATEGORY` and pinned against
-- this line by the same test. It is a literal and not a second column default
-- because it is not a board id: no tab reads it, and a default would put the
-- word somewhere a reader of the routine cannot see it.
--
-- The grants are not restated. `create or replace` preserves the routine's
-- ACL, so `0003`'s `revoke ... from public` and its guarded grant to
-- `service_role` still hold; re-issuing them here would read as though they
-- did not, and the first person to believe that would remove one of them.
