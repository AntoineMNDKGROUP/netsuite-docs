-- =============================================================================
-- 0002 — Enrichissement saved_searches
-- =============================================================================
-- Ajoute les colonnes nécessaires pour stocker la définition complète d'une
-- saved search (telle que renvoyée par le RESTlet `saved_search_reader`) et
-- pour détecter les changements (sha256 du payload normalisé).
-- =============================================================================

alter table saved_searches add column if not exists content_sha256 text not null default '';
alter table saved_searches add column if not exists filter_expression text;
alter table saved_searches add column if not exists is_inactive boolean not null default false;
alter table saved_searches add column if not exists last_extracted_at timestamptz;

create index if not exists idx_searches_search_id on saved_searches (search_id);
create index if not exists idx_searches_owner on saved_searches (owner);
create index if not exists idx_searches_recordtype on saved_searches (search_type);
create index if not exists idx_searches_inactive on saved_searches (is_inactive);
