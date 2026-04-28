-- =============================================================================
-- 0003 : tracking des suppressions + table de docs IA d'updates de scripts
-- =============================================================================
-- Ajoute aux tables métier :
--   - is_deleted boolean : true quand l'entité ne revient plus dans nos extractions
--   - deleted_at timestamptz : quand on l'a détectée comme supprimée
--
-- Distinct de `is_inactive` qui reflète un état NetSuite (toggle "Inactive" UI).
-- `is_deleted` veut dire : on ne la retrouve plus du tout dans le compte (vraie
-- suppression OU retirée de l'audience accessible au token).
--
-- Crée également :
--   - changes.kind 'deleted' (déjà dans l'enum change_kind)
--   - script_update_docs : doc IA générée pour chaque update de source code
-- =============================================================================

-- Tables métier : ajout des deux colonnes
alter table scripts                add column if not exists is_deleted  boolean not null default false;
alter table scripts                add column if not exists deleted_at  timestamptz;
alter table script_deployments     add column if not exists is_deleted  boolean not null default false;
alter table script_deployments     add column if not exists deleted_at  timestamptz;
alter table custom_fields          add column if not exists is_deleted  boolean not null default false;
alter table custom_fields          add column if not exists deleted_at  timestamptz;
alter table custom_record_types    add column if not exists is_deleted  boolean not null default false;
alter table custom_record_types    add column if not exists deleted_at  timestamptz;
alter table saved_searches         add column if not exists is_deleted  boolean not null default false;
alter table saved_searches         add column if not exists deleted_at  timestamptz;
alter table workflows              add column if not exists is_deleted  boolean not null default false;
alter table workflows              add column if not exists deleted_at  timestamptz;
alter table script_source_files    add column if not exists is_deleted  boolean not null default false;
alter table script_source_files    add column if not exists deleted_at  timestamptz;

-- Indexes pour les requêtes "récemment supprimés"
create index if not exists idx_scripts_deleted_at             on scripts (deleted_at desc) where is_deleted = true;
create index if not exists idx_fields_deleted_at              on custom_fields (deleted_at desc) where is_deleted = true;
create index if not exists idx_searches_deleted_at            on saved_searches (deleted_at desc) where is_deleted = true;
create index if not exists idx_workflows_deleted_at           on workflows (deleted_at desc) where is_deleted = true;
create index if not exists idx_custom_record_types_deleted_at on custom_record_types (deleted_at desc) where is_deleted = true;

-- =============================================================================
-- script_update_docs : doc IA d'update de script
-- =============================================================================
-- Une ligne par update détecté du source code d'un script (script_source_files
-- dont le content_sha256 a changé entre 2 runs). Stocke un résumé court 1-2
-- phrases généré par Claude qui décrit la nature du changement.
-- =============================================================================

create table if not exists script_update_docs (
    id                       uuid primary key default uuid_generate_v4(),
    script_ns_id             text not null,
    source_file_ns_id        text,                            -- script_source_files.ns_internal_id
    sha256_before            text,                            -- content_sha256 d'avant
    sha256_after             text not null,                   -- content_sha256 d'après
    summary                  text not null,                   -- résumé IA 1-2 phrases
    detail                   text,                            -- placeholder pour version longue future
    diff_lines_added         integer,                         -- comptage lignes ajoutées (utile pour le dashboard)
    diff_lines_removed       integer,                         -- comptage lignes retirées
    detected_at              timestamptz not null default now(),
    sync_run_id              uuid,
    ai_model                 text,
    ai_tokens_used           integer
);

-- Lookups fréquents
create index if not exists idx_update_docs_script  on script_update_docs (script_ns_id, detected_at desc);
create index if not exists idx_update_docs_recent  on script_update_docs (detected_at desc);
create index if not exists idx_update_docs_run     on script_update_docs (sync_run_id);

-- Évite les doublons : on ne génère qu'UNE doc par paire (sha_before, sha_after)
create unique index if not exists uq_update_docs_dedup
    on script_update_docs (script_ns_id, coalesce(sha256_before, ''), sha256_after);
