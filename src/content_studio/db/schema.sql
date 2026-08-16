-- Content Studio FTE — schema, Decision 3
--
-- The five tables from Concept 7 (the backbone, unchanged in shape) plus the two
-- domain tables from §3 of the plan: `clients` and `posts`.
--
-- NOT here: `agent_sessions` and `agent_messages`. SQLAlchemySession creates them
-- itself, on the same database, linked by `session_id`. See §3: "not designed and
-- not hand-written".
--
-- Idempotent: run it as often as you like, through db/apply.py.

CREATE EXTENSION IF NOT EXISTS vector;


-- ─────────────────────────────────────────────────────────────────────────────
-- 1. CONVERSATIONS — the business metadata of one conversation
--    The cover sheet. The turn-by-turn transcript lives in the SDK's own tables,
--    linked by the same session_id. This table holds what the SDK does not
--    carry: who, when, and a summary.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    session_id  TEXT PRIMARY KEY,   -- THE SAME id passed to SQLAlchemySession
    user_id     TEXT NOT NULL,      -- always 'viorela' today; multi-user is deferred, not cancelled
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary     TEXT                -- written when the conversation closes
);
CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations(user_id, started_at DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. DOCUMENTS — the reference library
--    Filled at Decision 5, with source='library'. Provenance (authority_class,
--    version, rights_basis, owner, rank, has_page_markers, is_summary) lives in
--    `metadata`, on every row — §3, the placement decision.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source      TEXT NOT NULL,      -- 'library' today; 'post' only a few hundred from now
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. EMBEDDINGS — the meaning-search layer
--    One table for documents AND conversations; the CHECK forces exactly one of
--    the two links. 1536 = the width of text-embedding-3-small.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES documents(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(session_id) ON DELETE CASCADE,
    chunk_text      TEXT NOT NULL,
    chunk_index     INT  NOT NULL,
    embedding       VECTOR(1536) NOT NULL,
    model           TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {page, chapter} — Decision 5
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (document_id IS NOT NULL)::int + (conversation_id IS NOT NULL)::int = 1
    )
);
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
    ON embeddings USING hnsw (embedding vector_cosine_ops);

-- For databases created at Decision 3, before the column existed: `CREATE TABLE
-- IF NOT EXISTS` does not touch an existing table, so the column is added
-- separately. On a fresh database this line does nothing.
ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. AUDIT_LOG — the replayable trail
--    BIGSERIAL, not UUID: rows pile up fast and the order has to be obvious.
--    `action` is a CLOSED vocabulary — widening it is a migration, not an
--    afterthought.
--
--    NOTE, a deliberate departure from Concept 7: the book's vocabulary is
--    customer-support flavoured ('refund_issued', 'refund_blocked'). Those have
--    no place here. They are replaced by this domain's actions, from the plan:
--      proposals_generated  Decision 4 — the ten proposals, all of them in the payload
--      post_chosen          which of the ten was picked, and implicitly which nine lost
--                           (§3: "the trace sees calls, not decisions" — this fixes that)
--      post_saved           Decision 7, in the SAME transaction as the INSERT into posts
--      profile_updated      §3, variant A — the agent writes to the profile when she asks
--      approval_requested   Decision 9 — the gate opened
--      approval_rejected    Decision 9 — refused, and then nothing is written
--    The rest are universal and stay untouched.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(session_id) ON DELETE SET NULL,
    actor           TEXT NOT NULL,        -- 'worker:content-studio', 'viorela', 'system'
    action          TEXT NOT NULL CHECK (action IN (
                        'message_received', 'message_sent', 'skill_activated',
                        'capability_invoked', 'guardrail_tripped', 'corpus_seeded',
                        'proposals_generated', 'post_chosen', 'post_saved',
                        'profile_updated', 'approval_requested', 'approval_rejected'
                    )),
    target          TEXT,                 -- the table name, the skill name, and so on
    payload         JSONB NOT NULL,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_conv   ON audit_log(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, created_at);


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. CAPABILITY_INVOCATIONS — every skill or tool call
--    Kept even though the book marks it optional — §3, the decision of 13 Aug.
--    'blocked' = approval refused at the Decision 9 gate.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS capability_invocations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id TEXT NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
    capability      TEXT NOT NULL,        -- 'tool:search_books', 'skill:propune-postari'
    arguments       JSONB NOT NULL,
    result          JSONB,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error', 'blocked', 'timeout')),
    latency_ms      INT,
    cost_cents      INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_cap_conv
    ON capability_invocations(conversation_id, created_at);


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. CLIENTS — one content column, `profile_md`
--    §3: the CTAs live inside it, in section 6, not in a separate table. The
--    whole profile goes into the system prompt at every start, as a string — so
--    the model sees section 6 and the ⚠️ markers directly in the text, with no
--    query at all.
--    It lives here rather than in documents+embeddings because it is the only
--    material that gets WRITTEN to: you cannot UPDATE a vector.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS clients (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        TEXT UNIQUE NOT NULL,  -- 'viorela'; = conversations.user_id
    name        TEXT NOT NULL,
    profile_md  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. POSTS — the finished posts
--    §3: at 26 of them, "have I written about this already?" is answered with a
--    WHERE on title, pillar and date. That is why they do NOT go into embeddings
--    yet.
--
--    `body_md` is not in the §3 list — it was added. The reason: the 26 existing
--    posts come in THREE different shapes (see db/seed.py), and only the newest
--    has the full structure. A parser that splits them into columns loses
--    whatever it does not recognize. The columns are for querying; `body_md`
--    keeps the source whole and re-parsable later, without re-reading files.
--
--    `pillar`, `hook_type` and `status` hold Romanian domain values on purpose:
--    they are the client's vocabulary, and they show up in her posts.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS posts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(session_id) ON DELETE SET NULL,
    posted_on       DATE NOT NULL,        -- from the file name at import; present on all 26
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
CREATE INDEX IF NOT EXISTS idx_posts_client_date ON posts(client_id, posted_on DESC);
CREATE INDEX IF NOT EXISTS idx_posts_pillar      ON posts(client_id, pillar);
