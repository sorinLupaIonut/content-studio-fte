-- Content Studio FTE — schema.
--
-- Decision 3 built the domain half. D4 of the deployment roadmap replaced the
-- state half with the crash course's own five-table model, so this file now has
-- two clearly separated parts:
--
--   THE DOMAIN (ours)     documents, embeddings — the library
--                         clients, posts        — the client's work
--
--   DURABLE STATE (the course's schema.sql, adopted at D4)
--                         runs, traces, artifacts, audit_log
--
-- NOT here: `agent_sessions` and `agent_messages`. SQLAlchemySession creates them
-- itself, on the same database, keyed by `session_id`. They are the ONLY session
-- table: the course's `sessions` is not created separately, and `runs.session_id`
-- points at `agent_sessions(session_id)` instead — the same foreign key the SDK's
-- own `agent_messages` already uses. One session table, not two.
--
-- WHAT LEFT AT D4, and why:
--
--   `pending_runs` held `RunState.to_string()` for a run stopped at the approval
--   gate. The course's model has no counterpart — Maya's harness never asks
--   permission — so the table went. The gate did not: it moved into
--   `public.runs` as six more columns, which is the better shape anyway, since a
--   run waiting for an answer is still a run. See §5.
--
--   `audit_log` was ours: conversation_id, actor, action (a closed vocabulary of
--   13), target, payload, result. It is replaced by the course's shape —
--   (run_id, event) — which is smaller on purpose. What is lost: the arguments
--   and results of every call, the actor, and the CHECK that made the vocabulary
--   enforceable. What is gained: the link to `runs`. Rule 2 of AGENTS.md still
--   holds (the trail is written in the same transaction as the write it
--   describes), it simply records less about it. `event` is free text, so the
--   vocabulary now lives in `audit.py` as a convention rather than a constraint.
--
-- Every statement that touches the state half is schema-qualified (`public.runs`,
-- `public.audit_log`). The Neon `-pooler` endpoint is PgBouncer in transaction
-- mode: a `SET search_path` issued in one transaction is not guaranteed to apply
-- to the next, so code that relies on it breaks intermittently rather than
-- loudly. Qualifying removes the question. Migrations additionally run against
-- the DIRECT endpoint — see DATABASE_URL_DIRECT in config.py.
--
-- Idempotent: run it as often as you like, through db/apply.py.

CREATE EXTENSION IF NOT EXISTS vector;


-- ─────────────────────────────────────────────────────────────────────────────
-- GUARD — refuse to run against a database still carrying the pre-D4 audit_log.
--
-- `CREATE TABLE IF NOT EXISTS` does NOT reshape an existing table: on a database
-- that still has the old eight-column `audit_log`, this file would succeed in
-- silence and every INSERT in audit.py would then fail at runtime, one message
-- into a real conversation. Better to stop here, with the fix in the message.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'audit_log'
           AND column_name  = 'conversation_id'
    ) THEN
        RAISE EXCEPTION
            'audit_log still has its pre-D4 shape. Apply the one-way migration '
            'first:  uv run python -m content_studio.db.apply '
            '--file migration_d4_course_schema.sql';
    END IF;
END
$$;


-- ═════════════════════════════════════════════════════════════════════════════
-- PART ONE — THE DOMAIN
-- ═════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. DOCUMENTS — the reference library
--    Filled at Decision 5, with source='library'. Provenance (authority_class,
--    version, rights_basis, owner, rank, has_page_markers, is_summary) lives in
--    `metadata`, on every row — §3, the placement decision.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source      TEXT NOT NULL,      -- 'library' today; 'post' only a few hundred from now
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON public.documents(source);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. EMBEDDINGS — the meaning-search layer
--    1536 = the width of text-embedding-3-small.
--
--    Until Decision 11 this table could also point at a conversation, with a
--    CHECK forcing exactly one of the two links. Nothing ever used that half —
--    all 4,778 rows pointed at a document — so one link, enforced by NOT NULL,
--    is the honest shape.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
    chunk_text      TEXT NOT NULL,
    chunk_index     INT  NOT NULL,
    embedding       VECTOR(1536) NOT NULL,
    model           TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {page, chapter} — Decision 5
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
    ON public.embeddings USING hnsw (embedding vector_cosine_ops);

-- For databases created at Decision 3, before the column existed: `CREATE TABLE
-- IF NOT EXISTS` does not touch an existing table, so the column is added
-- separately. On a fresh database this line does nothing.
ALTER TABLE public.embeddings
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. CLIENTS — one content column, `profile_md`
--    §3: the CTAs live inside it, in section 6, not in a separate table. The
--    whole profile goes into the system prompt at every start, as a string — so
--    the model sees section 6 and the ⚠️ markers directly in the text, with no
--    query at all.
--    It lives here rather than in documents+embeddings because it is the only
--    material that gets WRITTEN to: you cannot UPDATE a vector.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.clients (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        TEXT UNIQUE NOT NULL,  -- 'viorela'; also the session_id prefix
    name        TEXT NOT NULL,
    profile_md  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- `rename_to_english.sql` renamed the tables and the columns, but not the
-- constraints Postgres had already named after them — so a database migrated
-- from the Romanian schema still called this `client_pkey`, while a database
-- created fresh from this file calls it `clients_pkey`. Two databases, same
-- shape, different names.
--
-- That is not cosmetic. It is exactly how Decision 11's migration nearly went
-- wrong: `DROP CONSTRAINT IF EXISTS posts_conversation_id_fkey` would have found
-- nothing, said nothing, and left the constraint in place. `IF EXISTS` turns a
-- guessed name into a silent no-op.
--
-- Renaming a constraint is metadata only: no data is read, no index rebuilt, no
-- lock worth worrying about.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT * FROM (VALUES
            ('clients', 'client_pkey',                       'clients_pkey'),
            ('clients', 'client_slug_key',                   'clients_slug_key'),
            ('posts',   'postari_pkey',                      'posts_pkey'),
            ('posts',   'postari_client_id_fkey',            'posts_client_id_fkey'),
            ('posts',   'postari_client_id_fisier_sursa_key','posts_client_id_source_file_key')
        ) AS t(table_name, old_name, new_name)
    LOOP
        IF EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conname = r.old_name
               AND conrelid = ('public.' || r.table_name)::regclass
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I',
                r.table_name, r.old_name, r.new_name
            );
        END IF;
    END LOOP;
END
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. POSTS — the finished posts
--    §3: at 27 of them, "have I written about this already?" is answered with a
--    WHERE on title, pillar and date. That is why they do NOT go into embeddings
--    yet.
--
--    `body_md` is not in the §3 list — it was added. The reason: the existing
--    posts come in THREE different shapes (see db/seed.py), and only the newest
--    has the full structure. A parser that splits them into columns loses
--    whatever it does not recognize. The columns are for querying; `body_md`
--    keeps the source whole and re-parsable later, without re-reading files.
--
--    `pillar`, `hook_type` and `status` hold Romanian domain values on purpose:
--    they are the client's vocabulary, and they show up in her posts.
--
--    NOT the same thing as the course's `artifacts`. That table holds pointers
--    to files in object storage (R2); a post is a structured row of the client's
--    own work. They were kept apart deliberately at D4.
--
--    `conversation_id` is plain TEXT and holds the session_id — the run that
--    produced a post is findable through `audit_log.run_id` instead.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.posts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    conversation_id TEXT,                 -- the session_id; plain TEXT since Decision 11
    posted_on       DATE NOT NULL,        -- from the file name at import
    title           TEXT NOT NULL,
    pillar          TEXT,                 -- 'Educație', 'Conexiune', 'Conversie', 'Autoritate'
    format          TEXT,                 -- 'Reel mut 6–9 secunde', 'Reel vorbit 35–45s', …
    hook            TEXT,                 -- the chosen hook, its text
    hook_type       TEXT,                 -- PROVOCARE | CIFRĂ | SECRET | ÎNTREBARE | CONTRAST
    script          TEXT,
    caption         TEXT,
    hashtags        TEXT,
    cta             TEXT,
    source          TEXT,                 -- title + page, or 'din memorie'
    status          TEXT NOT NULL DEFAULT 'imported'
                    CHECK (status IN ('imported', 'draft', 'approved', 'published')),
    body_md         TEXT NOT NULL,        -- the whole file, exactly as it arrived
    source_file     TEXT,                 -- the name of the file it came from
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, source_file)       -- so seed.py can run twice
);
CREATE INDEX IF NOT EXISTS idx_posts_client_date ON public.posts(client_id, posted_on DESC);
CREATE INDEX IF NOT EXISTS idx_posts_pillar      ON public.posts(client_id, pillar);

ALTER TABLE public.posts DROP CONSTRAINT IF EXISTS postari_conversation_id_fkey;
ALTER TABLE public.posts DROP CONSTRAINT IF EXISTS posts_conversation_id_fkey;


-- ═════════════════════════════════════════════════════════════════════════════
-- PART TWO — DURABLE STATE, the crash course's schema (D4)
--
-- The companion's `schema.sql`, with two deliberate departures:
--
--   1. The course's `sessions` table is not created. `agent_sessions` already
--      exists, the SDK writes it, and `agent_messages` already keys off it — a
--      second session table would be a second copy of the same truth, which is
--      exactly what took `conversations` out at Decision 11. So
--      `runs.session_id` points there instead.
--
--   2. `runs` carries six more columns than the course's, because this agent has
--      an approval gate and Maya's does not. Everything the course writes is
--      still written, in the same columns; the additions are additive.
-- ═════════════════════════════════════════════════════════════════════════════

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. RUNS — one agent task, and the approval gate
--
--    The first six columns are the course's, unchanged. The rest are this
--    project's addition, and the reason is rule 6: nothing is written without
--    her yes.
--
--    In the terminal the gate is a blocked process — `Runner.run` returns
--    interruptions, `input()` waits, the run resumes. That works because the
--    person is sitting at the process. Over HTTP there is nobody to block for:
--    the request has to END while the run is unfinished, and the run has to be
--    picked up later, possibly by a different container after the old one scaled
--    to zero. So the run itself is written down.
--
--    This lived in a `pending_runs` table of its own until D4, which dropped it
--    along with the rest of the old state half. Folding it into `runs` is the
--    better shape anyway: a run waiting for an answer is still a run, and it
--    keeps one row per turn instead of two rows that can disagree.
--
--    `state` is `RunState.to_string()` — the conversation so far, the pending
--    tool calls, and the sandbox resume payload. Large; Postgres TOASTs it out
--    of line and compresses it, and there is nothing to tune.
--
--    One row = one interrupted run, not one tool call. A single run can stop on
--    several calls at once (`result.interruptions` is a list) and ALL of them
--    have to be decided before it continues — hence `requests`/`decisions` as
--    arrays, and one resume.
--
--    The foreign key to `agent_sessions` is added separately, below, because on
--    a brand-new database that table does not exist until SQLAlchemySession
--    creates it on the worker's first run.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.runs (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    input_message   TEXT NOT NULL,
    output_message  TEXT,
    used_sandbox    BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- the gate
    status          TEXT NOT NULL DEFAULT 'running',
    requests        JSONB,         -- [{call_id, tool_name, arguments}, …]
    state           TEXT,          -- RunState.to_string()
    decisions       JSONB,         -- [{call_id, approved, reason}, …] once answered
    resolved_at     TIMESTAMPTZ,
    resolved_by     TEXT           -- 'viorela'; multi-user is deferred, not cancelled
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON public.runs(session_id);
CREATE INDEX IF NOT EXISTS idx_runs_created ON public.runs(created_at);

-- Forward migration for the database D4 already created without the gate
-- columns: `CREATE TABLE IF NOT EXISTS` does not reshape an existing table.
-- On a fresh database these do nothing.
ALTER TABLE public.runs ADD COLUMN IF NOT EXISTS status      TEXT NOT NULL DEFAULT 'running';
ALTER TABLE public.runs ADD COLUMN IF NOT EXISTS requests    JSONB;
ALTER TABLE public.runs ADD COLUMN IF NOT EXISTS state       TEXT;
ALTER TABLE public.runs ADD COLUMN IF NOT EXISTS decisions   JSONB;
ALTER TABLE public.runs ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE public.runs ADD COLUMN IF NOT EXISTS resolved_by TEXT;

--    running    the model is working, or the process died while it was
--    pending    stopped at the gate, waiting for her answer
--    completed  answered and finished
--    failed     the turn died; `output_message` stays NULL
--    expired    nobody ever answered, and the harness gave up on it
ALTER TABLE public.runs DROP CONSTRAINT IF EXISTS runs_status_check;
ALTER TABLE public.runs ADD  CONSTRAINT runs_status_check
    CHECK (status IN ('running', 'pending', 'completed', 'failed', 'expired'));

-- A run cannot claim to be waiting at the gate without the two things needed to
-- resume it. Without this, a half-written suspend leaves a row that the harness
-- would show her as "waiting for your answer" and then fail to continue.
ALTER TABLE public.runs DROP CONSTRAINT IF EXISTS runs_pending_is_resumable;
ALTER TABLE public.runs ADD  CONSTRAINT runs_pending_is_resumable
    CHECK (status <> 'pending' OR (state IS NOT NULL AND requests IS NOT NULL));

-- The real guarantee: a conversation can have at most ONE run waiting at a time.
-- Without it, two browser tabs could each leave a pending run and the second
-- resume would replay the first. Only `pending` is exclusive — a crashed run
-- left at `running` must not lock the session out forever.
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_one_open_per_session
    ON public.runs(session_id) WHERE status = 'pending';

-- The one session table. Added only once both sides exist, so `apply.py` can run
-- on an empty database and again after the first conversation, with the same
-- result. `agent_sessions.session_id` is a VARCHAR primary key; TEXT and VARCHAR
-- are binary-coercible, so the key is exact, not a cast.
DO $$
BEGIN
    IF to_regclass('public.agent_sessions') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
            WHERE conname = 'runs_session_id_fkey'
              AND conrelid = 'public.runs'::regclass
       )
    THEN
        ALTER TABLE public.runs
            ADD CONSTRAINT runs_session_id_fkey
            FOREIGN KEY (session_id)
            REFERENCES public.agent_sessions(session_id) ON DELETE CASCADE;
    END IF;
END
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. TRACES — one payload per run
--    The name is the course's. What goes in is `{"input": …, "output": …}`, not
--    an SDK trace: the real traces live in the OpenAI dashboard, grouped by
--    `group_id = session_id` (see worker.py). Keeping the course's shape means
--    the harness and the CLI write the same thing.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.traces (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES public.runs(id),
    payload     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_traces_run ON public.traces(run_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. ARTIFACTS — pointers to files in object storage
--    Empty until D5 decides on Cloudflare R2. Created now because it is part of
--    the course's schema and costs nothing; if D5 concludes that this project
--    has no files worth storing, the emptiness is the answer, written down.
--
--    A post is NOT an artifact. Posts are structured rows in `public.posts`.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.artifacts (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES public.runs(id),
    object_key  TEXT NOT NULL,
    url         TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON public.artifacts(run_id);


-- ─────────────────────────────────────────────────────────────────────────────
-- 8. AUDIT_LOG — the trail
--    The course's shape, adopted whole at D4. `run_id` is NULLABLE on purpose:
--    `db.seed` writes `corpus_seeded` with no run behind it, and so does anything
--    else that happens outside a conversation.
--
--    `event` is free text. The vocabulary that used to be a CHECK now lives in
--    audit.py as EVENTS, and replay.py reads it back — a convention the database
--    no longer enforces. That is the trade this table makes.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.audit_log (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id      TEXT REFERENCES public.runs(id),
    event       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_run ON public.audit_log(run_id);
