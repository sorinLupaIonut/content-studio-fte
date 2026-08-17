-- ═══════════════════════════════════════════════════════════════════════════════
-- D4 — adopt the crash course's durable-state schema.
--
-- This file only REMOVES. What replaces the removed tables is created by
-- schema.sql, which refuses to run until this has been applied (it checks for
-- `audit_log.conversation_id` and stops with a message pointing here).
--
--    uv run python -m content_studio.db.apply --file migration_d4_course_schema.sql
--    uv run python -m content_studio.db.apply
--
-- Run it against the DIRECT Neon endpoint. Set DATABASE_URL_DIRECT in `.env` and
-- apply.py will pick it up on its own; without it, apply.py refuses to run DDL
-- through `-pooler`.
--
-- Take a Neon branch first. Nothing here is reversible from inside the database.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- WHAT GOES, AND WHAT IT COSTS
--
-- 1. `pending_runs` — the approval gate's durable home, added at Decision 11 and
--    removed here by decision: the course's five-table model has no counterpart,
--    because Maya's harness never asks permission before writing.
--
--    RESOLVED, same day: the gate did not go with the table. It moved into
--    `public.runs` as six more columns — status, requests, state, decisions,
--    resolved_at, resolved_by — plus a CHECK that a `pending` run must carry
--    what it takes to resume, and a partial unique index for "one run waiting
--    per session". See §5 of schema.sql. A run waiting for an answer is still a
--    run, so this is a better shape than the separate table ever was.
--
-- 2. `audit_log` — ours had conversation_id, actor, action (a CHECK of 13
--    values), target, payload and result. The course's has run_id and a free-text
--    event. The old table is dropped rather than migrated because the two shapes
--    share no column but `created_at`, and because it is empty: Decision 11
--    truncated it, and nothing has run since.
--
--    Lost with it: the arguments and results of every tool call, who acted, and
--    the enforceable vocabulary. Kept: the trail itself, in the same transaction
--    as the write it describes (rule 2), now linked to a run.
--
-- Both DROPs refuse to proceed if the table holds rows. On this database both
-- were verified empty before the migration was written; the guard is for every
-- other environment, where "it was empty when I checked" is not a fact.
-- ═══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. The approval gate's table.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    rows_left BIGINT;
BEGIN
    IF to_regclass('public.pending_runs') IS NULL THEN
        RAISE NOTICE 'pending_runs is already gone.';
        RETURN;
    END IF;

    EXECUTE 'SELECT count(*) FROM public.pending_runs' INTO rows_left;
    IF rows_left > 0 THEN
        RAISE EXCEPTION
            'pending_runs still holds % row(s) — every one of them is a run '
            'waiting for an answer. Resolve or export them before dropping.',
            rows_left;
    END IF;

    DROP TABLE public.pending_runs;
END
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. The old trail.
--    Dropped only if it is the OLD shape: running this file twice must not
--    destroy the new table that schema.sql creates in its place.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    rows_left BIGINT;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'audit_log'
           AND column_name  = 'conversation_id'
    ) THEN
        RAISE NOTICE 'audit_log is already the course shape — nothing to drop.';
        RETURN;
    END IF;

    EXECUTE 'SELECT count(*) FROM public.audit_log' INTO rows_left;
    IF rows_left > 0 THEN
        RAISE EXCEPTION
            'audit_log holds % row(s) of trail. The new shape keeps none of its '
            'columns, so this would be data loss. Export it first: '
            'COPY public.audit_log TO ''audit_log_backup.csv'' CSV HEADER;',
            rows_left;
    END IF;

    DROP TABLE public.audit_log;
END
$$;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Afterwards, run schema.sql. The database then holds:
--
--   documents    17 rows      the library, untouched
--   embeddings   4,778 rows   untouched
--   clients      1 row        the profile, untouched
--   posts        0 rows       re-fillable from content/posts/ with db.seed
--   runs         0 rows       new — one row per turn
--   traces       0 rows       new — one payload per run
--   artifacts    0 rows       new — stays empty until D5 decides on R2
--   audit_log    0 rows       new shape: (run_id, event)
--   agent_*      0 rows       the SDK's, and the only session table
-- ─────────────────────────────────────────────────────────────────────────────
