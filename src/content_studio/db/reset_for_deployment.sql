-- ═══════════════════════════════════════════════════════════════════════════════
-- Decision 11 — the database as the deployment needs it.
--
-- Two things happen here, and they are different in kind:
--
--   1. Two tables leave. `conversations` was the cover sheet of a terminal
--      session; the harness keeps its sessions in the SDK's own `agent_sessions`,
--      so the table would only be a second, drifting copy of the same truth.
--      `capability_invocations` recorded what `audit_log` already records —
--      'approval_rejected' says the same thing as status='blocked', with one
--      writer instead of two.
--
--   2. Everything that is not the library is emptied. Old posts and old
--      conversations belong to the pre-deployment life of this project. The 17
--      books and their 4,778 vectors stay: they cost real money to embed, and
--      nothing about them changes.
--
-- What is deliberately NOT touched: `documents`, `embeddings`, `clients`.
-- The profile in `clients` is the agent's system prompt — without it the worker
-- refuses to start — and it is byte-identical to content/profile.md anyway.
--
-- Every foreign key is dropped BY NAME. `DROP TABLE ... CASCADE` would also
-- work, but it would decide the blast radius on its own; here each dependency is
-- visible, and the names are the real ones read out of pg_constraint (note that
-- the constraints on `posts` still carry their pre-rename Romanian names).
--
-- Run it against the DIRECT Neon endpoint, not `-pooler`: PgBouncer silently
-- drops server settings that DDL sometimes depends on.
--
--    uv run python -m content_studio.db.apply --file reset_for_deployment.sql
--
-- Take a Neon branch first. This is not reversible from inside the database.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- APPLIED on 2026-08-17, to project `dry-fog-12289707`, branch `main`.
-- The snapshot taken beforehand is the Neon branch `pre-deployment-2026-08-17`
-- (`br-lively-cell-avhqk36f`), verified to hold the pre-migration row counts.
--
-- The file is kept rather than deleted: it is the record of what happened to a
-- database that holds a real client's work, and it is what a fresh environment
-- would need if it were ever restored from that branch. Running it again is
-- harmless — every statement is `IF EXISTS` or a TRUNCATE of a table that
-- schema.sql now defines without the dropped columns.
-- ─────────────────────────────────────────────────────────────────────────────
-- ═══════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Cut the four references to `conversations` before removing it.
--    audit_log and posts keep the column: "which conversation produced this" is
--    still worth knowing, it just stops being enforced by a table that no longer
--    exists. Both become plain TEXT.
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.audit_log
    DROP CONSTRAINT IF EXISTS audit_log_conversation_id_fkey;

ALTER TABLE public.posts
    DROP CONSTRAINT IF EXISTS postari_conversation_id_fkey;

ALTER TABLE public.embeddings
    DROP CONSTRAINT IF EXISTS embeddings_conversation_id_fkey;

-- capability_invocations references it too, but that table is about to go, so
-- its constraint goes with it.

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. `embeddings.conversation_id` was always the unused half of an either/or.
--    Zero rows use it (verified: 4,778 of 4,778 point at a document), and with
--    conversations gone it can never be filled again. The CHECK that enforced
--    "exactly one of the two links" collapses into the only link left.
--    Dropping a column is metadata-only in Postgres — the vectors are not
--    rewritten and the HNSW index is not rebuilt.
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.embeddings
    DROP CONSTRAINT IF EXISTS embeddings_check;

ALTER TABLE public.embeddings
    DROP COLUMN IF EXISTS conversation_id;

ALTER TABLE public.embeddings
    ALTER COLUMN document_id SET NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. The two tables that no longer earn their place.
-- ─────────────────────────────────────────────────────────────────────────────
DROP TABLE IF EXISTS public.capability_invocations;
DROP TABLE IF EXISTS public.conversations;

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. Empty everything that is not the library.
--    agent_messages and agent_sessions are the SDK's own tables and are
--    truncated together: the first references the second.
-- ─────────────────────────────────────────────────────────────────────────────
TRUNCATE TABLE public.posts     RESTART IDENTITY;
TRUNCATE TABLE public.audit_log RESTART IDENTITY;

DO $$
BEGIN
    IF to_regclass('public.agent_sessions') IS NOT NULL THEN
        TRUNCATE TABLE public.agent_messages, public.agent_sessions RESTART IDENTITY;
    END IF;
END
$$;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────────
-- Afterwards, the shape is:
--
--   documents    17 rows      the library, untouched
--   embeddings   4,778 rows   untouched, one link instead of two
--   clients      1 row        the profile, untouched
--   posts        0 rows
--   audit_log    0 rows
--   agent_*      0 rows
--
-- SUPERSEDED IN PART. This file also created `pending_runs`, the approval gate's
-- durable home. D4 removed it again when the crash course's five-table state
-- model was adopted, and replaced this file's `audit_log` with the course's
-- (run_id, event) shape. See db/migration_d4_course_schema.sql, which is the
-- newer of the two one-way migrations and the one that describes the database as
-- it stands. This file is kept as the record of what Decision 11 did.
-- ─────────────────────────────────────────────────────────────────────────────
