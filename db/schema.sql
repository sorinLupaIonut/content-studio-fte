-- Content Studio FTE — schema, Decizia 3
--
-- Cele cinci tabele din Concept 7 (coloana vertebrală, nemodificată ca formă)
-- plus cele două de domeniu din §3 al planului: `client` și `postari`.
--
-- NU sunt aici: `agent_sessions` și `agent_messages`. Le creează singur
-- SQLAlchemySession pe aceeași bază, legate prin `session_id`. Vezi §3: „nu se
-- proiectează și nu se scriu de mână".
--
-- Idempotent: rulabil de câte ori vrei, prin db/apply.py.

CREATE EXTENSION IF NOT EXISTS vector;


-- ─────────────────────────────────────────────────────────────────────────────
-- 1. CONVERSATIONS — metadatele de business ale unei conversații
--    Foaia de gardă. Transcrierea tură-cu-tură stă în tabelele SDK-ului, legate
--    prin acelaşi session_id. Asta ține ce SDK-ul nu duce: cine, când, rezumat.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    session_id  TEXT PRIMARY KEY,   -- ACELAȘI id pasat lui SQLAlchemySession
    user_id     TEXT NOT NULL,      -- azi mereu 'viorela'; multi-user e amânat, nu anulat
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary     TEXT                -- scris la închiderea conversației
);
CREATE INDEX IF NOT EXISTS idx_conversations_user
    ON conversations(user_id, started_at DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. DOCUMENTS — biblioteca de referință
--    Se umple la Decizia 5, cu source='biblioteca'. Proveniența (clasa de
--    autoritate, versiune, temei_drepturi, proprietar, rang, are_marcaje_pagina,
--    este_rezumat) stă în `metadata`, pe fiecare rând — §3, decizia de plasare.
--    Rămâne gol până la Decizia 5.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source      TEXT NOT NULL,      -- 'biblioteca' azi; 'postare' abia peste câteva sute
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. EMBEDDINGS — stratul de căutare după înțeles
--    Un singur tabel pentru documente ȘI conversații; CHECK-ul forțează exact
--    una dintre cele două legături. 1536 = dimensiunea lui text-embedding-3-small.
--    Rămâne gol până la Decizia 5.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID REFERENCES documents(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(session_id) ON DELETE CASCADE,
    chunk_text      TEXT NOT NULL,
    chunk_index     INT  NOT NULL,
    embedding       VECTOR(1536) NOT NULL,
    model           TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,  -- {pagina, capitol} — Decizia 5
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        (document_id IS NOT NULL)::int + (conversation_id IS NOT NULL)::int = 1
    )
);
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
    ON embeddings USING hnsw (embedding vector_cosine_ops);

-- Pentru bazele făcute la Decizia 3, înainte să existe coloana: `CREATE TABLE
-- IF NOT EXISTS` nu atinge un tabel care există deja, deci coloana se adaugă
-- separat. Pe o bază nouă, linia asta nu face nimic.
ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. AUDIT_LOG — urma reluabilă
--    BIGSERIAL, nu UUID: rândurile se adună repede, iar ordinea trebuie să fie
--    evidentă. `action` e vocabular ÎNCHIS — lărgirea lui e o migrare, nu o
--    scăpare de moment.
--
--    ATENȚIE, abatere deliberată de la Concept 7: vocabularul din carte e de
--    customer support ('refund_issued', 'refund_blocked'). Aici n-au ce căuta.
--    Le-am înlocuit cu acțiunile domeniului, din plan:
--      propuneri_generate  Decizia 4 — cele 10 propuneri, cu toate în payload
--      postare_aleasa      care din 10 a fost aleasă, și implicit care 9 au picat
--                          (§3: „trace-ul vede apeluri, nu decizii" — fix asta)
--      postare_salvata     Decizia 7, în ACEEAȘI tranzacție cu INSERT-ul în postari
--      profil_actualizat   §3, varianta A — agentul scrie în profil la cererea ei
--      aprobare_ceruta     Decizia 9 — poarta s-a deschis
--      aprobare_respinsa   Decizia 9 — respins, și atunci nu se scrie nimic
--    Restul sunt universale și rămân neatinse.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(session_id) ON DELETE SET NULL,
    actor           TEXT NOT NULL,        -- 'worker:content-studio', 'viorela', 'system'
    action          TEXT NOT NULL CHECK (action IN (
                        'message_received', 'message_sent', 'skill_activated',
                        'capability_invoked', 'guardrail_tripped', 'corpus_seeded',
                        'propuneri_generate', 'postare_aleasa', 'postare_salvata',
                        'profil_actualizat', 'aprobare_ceruta', 'aprobare_respinsa'
                    )),
    target          TEXT,                 -- numele tabelului, al skill-ului etc.
    payload         JSONB NOT NULL,
    result          JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_conv   ON audit_log(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action, created_at);


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. CAPABILITY_INVOCATIONS — fiecare apel de skill sau unealtă
--    Păstrat deși e marcat opțional în carte — §3, decizia din 13 aug.
--    'blocked' = aprobare respinsă la poarta de la Decizia 9.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS capability_invocations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id TEXT NOT NULL REFERENCES conversations(session_id) ON DELETE CASCADE,
    capability      TEXT NOT NULL,        -- 'tool:cauta_in_carti', 'agent:propune_postari'
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
-- 6. CLIENT — o singură coloană de conținut, `profil_md`
--    §3: CTA-urile stau înăuntru, în secțiunea 6, nu în tabel separat. Profilul
--    intră ÎNTREG în system prompt la fiecare pornire, ca șir — deci modelul vede
--    secțiunea 6 și marcajele ⚠️ direct în text, fără nicio interogare.
--    Stă aici și nu în documents+embeddings fiindcă e singurul material în care
--    SE SCRIE: un vector nu se face UPDATE.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS client (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug           TEXT UNIQUE NOT NULL,  -- 'viorela'; = conversations.user_id
    nume           TEXT NOT NULL,
    profil_md      TEXT NOT NULL,
    creat_la       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actualizat_la  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. POSTARI — postările finale
--    §3: la 26 de bucăți, „am mai scris despre asta?" se răspunde cu WHERE pe
--    titlu, pilon și dată. De-aia NU intră în embeddings deocamdată.
--
--    `corp_md` nu e în lista din §3 — l-am adăugat. Motivul: cele 26 de postări
--    existente vin în TREI formate diferite (vezi db/seed.py), și doar cea mai
--    nouă are structura completă. Un parser care le sparge pe coloane pierde
--    ce nu recunoaște. Coloanele sunt pentru interogat; `corp_md` e ca sursa să
--    rămână întreagă și repars-abilă mai târziu, fără să reciteşti fişiere.
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS postari (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       UUID NOT NULL REFERENCES client(id) ON DELETE CASCADE,
    conversation_id TEXT REFERENCES conversations(session_id) ON DELETE SET NULL,
    data            DATE NOT NULL,        -- din numele fișierului la import; sigur pe toate 26
    titlu           TEXT NOT NULL,
    pilon           TEXT,                 -- 'Educație', 'Conexiune', 'Conversie', 'Autoritate'
    format          TEXT,                 -- 'Reel mut 6–9 secunde', 'Reel vorbit 35–45s' etc.
    hook            TEXT,                 -- hook-ul ales, textul lui
    tip_hook        TEXT,                 -- PROVOCARE | CIFRĂ | SECRET | ÎNTREBARE | CONTRAST
    script          TEXT,
    caption         TEXT,
    hashtaguri      TEXT,
    cta             TEXT,
    sursa           TEXT,                 -- titlu + pagină, sau 'din memorie'
    status          TEXT NOT NULL DEFAULT 'importata'
                    CHECK (status IN ('importata', 'ciorna', 'aprobata', 'publicata')),
    corp_md         TEXT NOT NULL,        -- fișierul întreg, așa cum a venit
    fisier_sursa    TEXT,                 -- numele fișierului de proveniență
    creat_la        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, fisier_sursa)      -- ca seed.py să fie rulabil de două ori
);
CREATE INDEX IF NOT EXISTS idx_postari_client_data ON postari(client_id, data DESC);
CREATE INDEX IF NOT EXISTS idx_postari_pilon       ON postari(client_id, pilon);
