-- One-time migration: Romanian identifiers → English, on an existing database.
--
-- Run it BEFORE db.apply. Otherwise `CREATE TABLE IF NOT EXISTS clients` sees no
-- `clients` table, creates an empty one next to the Romanian `client`, and the
-- data stays behind in a table nothing reads any more.
--
-- Idempotent from either direction: every step checks the world before touching
-- it, so a half-finished run can simply be run again.
--
-- What it does NOT touch: `documents.body`, `embeddings.embedding` and
-- `embeddings.chunk_text`. The 4,778 vectors cost real money to produce and
-- nothing about them changes here — only the metadata keys around them.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. Table names
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF to_regclass('public.client') IS NOT NULL AND to_regclass('public.clients') IS NULL THEN
        ALTER TABLE public.client RENAME TO clients;
    END IF;
    IF to_regclass('public.postari') IS NOT NULL AND to_regclass('public.posts') IS NULL THEN
        ALTER TABLE public.postari RENAME TO posts;
    END IF;
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. Column names
--    Each row is [table, old name, new name]. A rename runs only when the old
--    column is still there and the new one is not.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    renames text[][] := ARRAY[
        ['clients', 'nume',          'name'],
        ['clients', 'profil_md',     'profile_md'],
        ['clients', 'creat_la',      'created_at'],
        ['clients', 'actualizat_la', 'updated_at'],
        ['posts',   'data',          'posted_on'],
        ['posts',   'titlu',         'title'],
        ['posts',   'pilon',         'pillar'],
        ['posts',   'tip_hook',      'hook_type'],
        ['posts',   'hashtaguri',    'hashtags'],
        ['posts',   'sursa',         'source'],
        ['posts',   'corp_md',       'body_md'],
        ['posts',   'fisier_sursa',  'source_file'],
        ['posts',   'creat_la',      'created_at']
    ];
    i int;
BEGIN
    FOR i IN 1 .. array_length(renames, 1) LOOP
        IF EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = renames[i][1]
                   AND column_name = renames[i][2]
           ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'public'
                   AND table_name = renames[i][1]
                   AND column_name = renames[i][3]
           )
        THEN
            EXECUTE format(
                'ALTER TABLE public.%I RENAME COLUMN %I TO %I',
                renames[i][1], renames[i][2], renames[i][3]
            );
        END IF;
    END LOOP;
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. Index names — cosmetic, but a database where half the names are Romanian
--    is harder to read than one where none are.
-- ─────────────────────────────────────────────────────────────────────────────
ALTER INDEX IF EXISTS idx_postari_client_data RENAME TO idx_posts_client_date;
ALTER INDEX IF EXISTS idx_postari_pilon       RENAME TO idx_posts_pillar;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. posts.status — a closed vocabulary, so the CHECK comes off before the
--    values move and goes back on after.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF to_regclass('public.posts') IS NULL THEN
        RETURN;
    END IF;

    ALTER TABLE public.posts DROP CONSTRAINT IF EXISTS postari_status_check;
    ALTER TABLE public.posts DROP CONSTRAINT IF EXISTS posts_status_check;

    UPDATE public.posts
       SET status = CASE status
                        WHEN 'importata' THEN 'imported'
                        WHEN 'ciorna'    THEN 'draft'
                        WHEN 'aprobata'  THEN 'approved'
                        WHEN 'publicata' THEN 'published'
                        ELSE status
                    END
     WHERE status IN ('importata', 'ciorna', 'aprobata', 'publicata');

    ALTER TABLE public.posts ALTER COLUMN status SET DEFAULT 'imported';
    ALTER TABLE public.posts ADD CONSTRAINT posts_status_check
        CHECK (status IN ('imported', 'draft', 'approved', 'published'));
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. audit_log.action — the same treatment, on the trail's own vocabulary.
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    ALTER TABLE public.audit_log DROP CONSTRAINT IF EXISTS audit_log_action_check;

    UPDATE public.audit_log
       SET action = CASE action
                        WHEN 'propuneri_generate' THEN 'proposals_generated'
                        WHEN 'postare_aleasa'     THEN 'post_chosen'
                        WHEN 'postare_salvata'    THEN 'post_saved'
                        WHEN 'profil_actualizat'  THEN 'profile_updated'
                        WHEN 'aprobare_ceruta'    THEN 'approval_requested'
                        WHEN 'aprobare_respinsa'  THEN 'approval_rejected'
                        ELSE action
                    END
     WHERE action IN ('propuneri_generate', 'postare_aleasa', 'postare_salvata',
                      'profil_actualizat', 'aprobare_ceruta', 'aprobare_respinsa');

    ALTER TABLE public.audit_log ADD CONSTRAINT audit_log_action_check
        CHECK (action IN (
            'message_received', 'message_sent', 'skill_activated',
            'capability_invoked', 'guardrail_tripped', 'corpus_seeded',
            'proposals_generated', 'post_chosen', 'post_saved',
            'profile_updated', 'approval_requested', 'approval_rejected'
        ));
END $$;


-- ─────────────────────────────────────────────────────────────────────────────
-- 6. Tool names inside the trail: 'tool:cauta_in_carti' → 'tool:search_books'.
--    Skill names stay Romanian — the folders under skills/ did not move.
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE public.capability_invocations
   SET capability = replace(capability, 'cauta_in_carti',    'search_books')
 WHERE capability LIKE '%cauta_in_carti%';
UPDATE public.capability_invocations
   SET capability = replace(capability, 'cauta_pe_internet', 'search_web')
 WHERE capability LIKE '%cauta_pe_internet%';
UPDATE public.capability_invocations
   SET capability = replace(capability, 'listeaza_postari',  'list_posts')
 WHERE capability LIKE '%listeaza_postari%';
UPDATE public.capability_invocations
   SET capability = replace(capability, 'save_postare',      'save_post')
 WHERE capability LIKE '%save_postare%';
-- The guard matters here: replacing inside an already migrated 'update_profile'
-- would produce 'update_profilee'.
UPDATE public.capability_invocations
   SET capability = replace(capability, 'update_profil',     'update_profile')
 WHERE capability LIKE '%update_profil%'
   AND capability NOT LIKE '%update_profile%';

UPDATE public.audit_log SET target = 'posts'   WHERE target = 'postari';
UPDATE public.audit_log SET target = 'clients' WHERE target = 'client';
UPDATE public.audit_log SET target = 'clients,posts' WHERE target = 'client,postari';


-- ─────────────────────────────────────────────────────────────────────────────
-- 7. JSONB keys. The vectors are untouched; only the labels around them move.
--    `jsonb_strip_nulls` drops keys whose source was absent, so a partially
--    migrated row does not gain empty ones.
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE public.documents SET source = 'library' WHERE source = 'biblioteca';

UPDATE public.documents
   SET metadata = (metadata - 'fisier' - 'autor' - 'clasa' - 'versiune' - 'rang'
                            - 'are_marcaje_pagina' - 'este_rezumat'
                            - 'temei_drepturi' - 'proprietar')
                  || jsonb_strip_nulls(jsonb_build_object(
                        'file',             metadata -> 'fisier',
                        'author',           metadata -> 'autor',
                        'authority_class',  metadata -> 'clasa',
                        'version',          metadata -> 'versiune',
                        'rank',             metadata -> 'rang',
                        'has_page_markers', metadata -> 'are_marcaje_pagina',
                        'is_summary',       metadata -> 'este_rezumat',
                        'rights_basis',     metadata -> 'temei_drepturi',
                        'owner',            metadata -> 'proprietar'))
 WHERE metadata ?| ARRAY['fisier', 'autor', 'clasa', 'versiune', 'rang',
                         'are_marcaje_pagina', 'este_rezumat',
                         'temei_drepturi', 'proprietar'];

UPDATE public.embeddings
   SET metadata = (metadata - 'pagina' - 'capitol')
                  || jsonb_build_object(
                        'page',    metadata -> 'pagina',
                        'chapter', metadata -> 'capitol')
 WHERE metadata ?| ARRAY['pagina', 'capitol'];

UPDATE public.conversations
   SET metadata = (metadata - 'interfata' - 'versiune_metadata'
                            - 'inchidere_estimata' - 'motiv_inchidere'
                            - 'mesaje_primite' - 'mesaje_trimise'
                            - 'seturi_propuneri' - 'postari_salvate'
                            - 'actualizari_profil' - 'skilluri_activate'
                            - 'unelte_folosite' - 'erori' - 'ultima_activitate')
                  || jsonb_strip_nulls(jsonb_build_object(
                        'interface',         metadata -> 'interfata',
                        'metadata_version',  metadata -> 'versiune_metadata',
                        'closure_estimated', metadata -> 'inchidere_estimata',
                        'closure_reason',    metadata -> 'motiv_inchidere',
                        'messages_received', metadata -> 'mesaje_primite',
                        'messages_sent',     metadata -> 'mesaje_trimise',
                        'proposal_sets',     metadata -> 'seturi_propuneri',
                        'posts_saved',       metadata -> 'postari_salvate',
                        'profile_updates',   metadata -> 'actualizari_profil',
                        'skills_activated',  metadata -> 'skilluri_activate',
                        'tools_used',        metadata -> 'unelte_folosite',
                        'errors',            metadata -> 'erori',
                        'last_activity',     metadata -> 'ultima_activitate'))
 WHERE metadata ?| ARRAY['interfata', 'versiune_metadata', 'inchidere_estimata',
                         'motiv_inchidere', 'mesaje_primite', 'mesaje_trimise',
                         'seturi_propuneri', 'postari_salvate',
                         'actualizari_profil', 'skilluri_activate',
                         'unelte_folosite', 'erori', 'ultima_activitate'];

UPDATE public.conversations
   SET metadata = jsonb_set(metadata, '{status}',
                            to_jsonb(CASE metadata ->> 'status'
                                         WHEN 'activa'              THEN 'active'
                                         WHEN 'inchisa'             THEN 'closed'
                                         WHEN 'eroare_initializare' THEN 'init_error'
                                         ELSE metadata ->> 'status'
                                     END))
 WHERE metadata ->> 'status' IN ('activa', 'inchisa', 'eroare_initializare');

UPDATE public.conversations
   SET metadata = jsonb_set(metadata, '{closure_reason}',
                            to_jsonb(CASE metadata ->> 'closure_reason'
                                         WHEN 'sfarsit_intrare'      THEN 'end_of_input'
                                         WHEN 'intrerupere_terminal' THEN 'terminal_interrupt'
                                         WHEN 'comanda_iesire'       THEN 'exit_command'
                                         WHEN 'mcp_indisponibil'     THEN 'mcp_unavailable'
                                         WHEN 'sandbox_indisponibil' THEN 'sandbox_unavailable'
                                         WHEN 'completare_din_audit' THEN 'backfilled_from_audit'
                                         ELSE metadata ->> 'closure_reason'
                                     END))
 WHERE metadata ->> 'closure_reason' IN
       ('sfarsit_intrare', 'intrerupere_terminal', 'comanda_iesire',
        'mcp_indisponibil', 'sandbox_indisponibil', 'completare_din_audit');


-- ─────────────────────────────────────────────────────────────────────────────
-- 8. Audit payloads written by the write tools, so `conversation.py` can still
--    read the title of the last saved post out of history.
-- ─────────────────────────────────────────────────────────────────────────────
UPDATE public.audit_log
   SET payload = (payload - 'titlu' - 'pilon' - 'tip_hook' - 'hashtaguri' - 'sursa')
                 || jsonb_strip_nulls(jsonb_build_object(
                       'title',     payload -> 'titlu',
                       'pillar',    payload -> 'pilon',
                       'hook_type', payload -> 'tip_hook',
                       'hashtags',  payload -> 'hashtaguri',
                       'source',    payload -> 'sursa'))
 WHERE action = 'post_saved'
   AND payload ?| ARRAY['titlu', 'pilon', 'tip_hook', 'hashtaguri', 'sursa'];

UPDATE public.audit_log
   SET payload = (payload - 'sectiune' - 'text_vechi')
                 || jsonb_strip_nulls(jsonb_build_object(
                       'section',       payload -> 'sectiune',
                       'previous_text', payload -> 'text_vechi'))
 WHERE action = 'profile_updated'
   AND payload ?| ARRAY['sectiune', 'text_vechi'];

UPDATE public.audit_log
   SET payload = (payload - 'motiv') || jsonb_build_object('reason', payload -> 'motiv')
 WHERE payload ? 'motiv';
