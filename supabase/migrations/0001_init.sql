-- =============================================================================
-- NetSuite Documentation Hub - Schéma initial
-- À exécuter dans le SQL Editor de Supabase (projet: netsuite-docs)
-- =============================================================================

-- Extensions utiles
create extension if not exists "uuid-ossp";
create extension if not exists "pg_trgm";  -- pour la recherche full-text simple

-- =============================================================================
-- TYPES ENUM
-- =============================================================================

do $$ begin
  create type entity_type as enum (
    'script',
    'script_deployment',
    'custom_field',
    'saved_search',
    'workflow',
    'custom_record_type'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type change_kind as enum (
    'created',
    'updated',
    'deleted'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type sync_status as enum (
    'running',
    'success',
    'partial',
    'failed'
  );
exception when duplicate_object then null; end $$;

-- =============================================================================
-- TABLES MÉTIER (état courant)
-- =============================================================================

-- Scripts NetSuite (User Event, Client, Suitelet, RESTlet, MapReduce, etc.)
create table if not exists scripts (
  id              uuid primary key default uuid_generate_v4(),
  ns_internal_id  text not null unique,
  script_id       text,                    -- "customscript_xxx"
  name            text not null,
  script_type     text,                    -- USEREVENT, CLIENT, SUITELET, ...
  api_version     text,
  script_file     text,                    -- chemin du .js dans le file cabinet
  description     text,
  is_inactive     boolean default false,
  owner           text,
  date_created    timestamptz,
  last_modified   timestamptz,
  raw             jsonb not null default '{}'::jsonb,
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now()
);

create index if not exists idx_scripts_name_trgm on scripts using gin (name gin_trgm_ops);
create index if not exists idx_scripts_type on scripts (script_type);
create index if not exists idx_scripts_inactive on scripts (is_inactive);

-- Déploiements de scripts
create table if not exists script_deployments (
  id              uuid primary key default uuid_generate_v4(),
  ns_internal_id  text not null unique,
  script_ns_id    text not null references scripts (ns_internal_id) on delete cascade,
  deployment_id   text,                    -- "customdeploy_xxx"
  title           text,
  status          text,                    -- RELEASED, TESTING, ...
  is_deployed     boolean default false,
  log_level       text,
  execute_as_role text,
  audience        jsonb,                   -- roles, depts, employees autorisés
  context         jsonb,                   -- contextes d'exécution
  raw             jsonb not null default '{}'::jsonb,
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now()
);

create index if not exists idx_deploy_script on script_deployments (script_ns_id);

-- Custom fields (transactions, entities, items, lines, custom records)
create table if not exists custom_fields (
  id                uuid primary key default uuid_generate_v4(),
  ns_internal_id    text not null unique,
  field_id          text,                  -- "custbody_xxx"
  label             text not null,
  field_type        text,                  -- TEXT, FREEFORMTEXT, SELECT, DATE, ...
  field_category    text not null,         -- BODY, COLUMN, ENTITY, ITEM, OTHER, RECORD
  applies_to        jsonb,                 -- types de records auxquels le champ s'applique
  source_list       text,                  -- liste source pour les SELECT
  is_mandatory      boolean default false,
  is_inactive       boolean default false,
  default_value     text,
  help              text,
  description       text,
  owner             text,
  date_created      timestamptz,
  last_modified     timestamptz,
  raw               jsonb not null default '{}'::jsonb,
  first_seen_at     timestamptz not null default now(),
  last_seen_at      timestamptz not null default now()
);

create index if not exists idx_fields_label_trgm on custom_fields using gin (label gin_trgm_ops);
create index if not exists idx_fields_category on custom_fields (field_category);
create index if not exists idx_fields_inactive on custom_fields (is_inactive);

-- Saved searches
create table if not exists saved_searches (
  id              uuid primary key default uuid_generate_v4(),
  ns_internal_id  text not null unique,
  search_id       text,
  title           text not null,
  search_type     text,                    -- type de record sur lequel porte la search
  is_public       boolean default false,
  owner           text,
  description     text,
  filters         jsonb,
  columns         jsonb,
  date_created    timestamptz,
  last_modified   timestamptz,
  raw             jsonb not null default '{}'::jsonb,
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now()
);

create index if not exists idx_searches_title_trgm on saved_searches using gin (title gin_trgm_ops);

-- Workflows
create table if not exists workflows (
  id              uuid primary key default uuid_generate_v4(),
  ns_internal_id  text not null unique,
  workflow_id     text,                    -- "customworkflow_xxx"
  name            text not null,
  record_type     text,                    -- type de record déclencheur
  release_status  text,                    -- RELEASED, TESTING, ...
  is_inactive     boolean default false,
  description     text,
  owner           text,
  date_created    timestamptz,
  last_modified   timestamptz,
  states          jsonb,                   -- états + transitions
  raw             jsonb not null default '{}'::jsonb,
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now()
);

create index if not exists idx_workflows_name_trgm on workflows using gin (name gin_trgm_ops);
create index if not exists idx_workflows_record on workflows (record_type);

-- Custom record types (entité associée aux custom records)
create table if not exists custom_record_types (
  id              uuid primary key default uuid_generate_v4(),
  ns_internal_id  text not null unique,
  record_id       text,                    -- "customrecord_xxx"
  name            text not null,
  description     text,
  is_inactive     boolean default false,
  raw             jsonb not null default '{}'::jsonb,
  first_seen_at   timestamptz not null default now(),
  last_seen_at    timestamptz not null default now()
);

-- =============================================================================
-- HISTORIQUE / VERSIONING
-- =============================================================================

-- Snapshots : 1 ligne par sync où l'entité a changé. Permet de reconstruire
-- l'état de n'importe quel objet à n'importe quelle date.
create table if not exists snapshots (
  id              uuid primary key default uuid_generate_v4(),
  entity_type     entity_type not null,
  ns_internal_id  text not null,
  payload         jsonb not null,
  content_hash    text not null,           -- sha256 du payload pour dédup rapide
  captured_at     timestamptz not null default now(),
  sync_run_id     uuid
);

create index if not exists idx_snapshots_entity on snapshots (entity_type, ns_internal_id, captured_at desc);
create index if not exists idx_snapshots_run on snapshots (sync_run_id);
create unique index if not exists uq_snapshots_dedup on snapshots (entity_type, ns_internal_id, content_hash);

-- Changes : log des diffs détectés entre snapshots successifs
create table if not exists changes (
  id              uuid primary key default uuid_generate_v4(),
  entity_type     entity_type not null,
  ns_internal_id  text not null,
  entity_label    text,                    -- nom lisible au moment du change
  kind            change_kind not null,
  diff            jsonb,                   -- {"added": {...}, "removed": {...}, "changed": {...}}
  changed_by      text,                    -- nom NetSuite si dispo (system note)
  changed_at      timestamptz not null,
  detected_at     timestamptz not null default now(),
  sync_run_id     uuid
);

create index if not exists idx_changes_entity on changes (entity_type, ns_internal_id, changed_at desc);
create index if not exists idx_changes_recent on changes (changed_at desc);
create index if not exists idx_changes_run on changes (sync_run_id);

-- System notes : mirror de l'audit trail natif NetSuite
create table if not exists system_notes (
  id              uuid primary key default uuid_generate_v4(),
  ns_internal_id  text not null unique,    -- id system note dans NetSuite
  record_type     text not null,           -- type de record affecté
  record_id       text not null,           -- id du record affecté
  field           text,                    -- champ modifié
  old_value       text,
  new_value       text,
  context         text,                    -- UI, CSV, WS, ...
  changed_by      text,
  changed_at      timestamptz not null,
  inserted_at     timestamptz not null default now()
);

create index if not exists idx_sysnotes_record on system_notes (record_type, record_id, changed_at desc);
create index if not exists idx_sysnotes_recent on system_notes (changed_at desc);
create index if not exists idx_sysnotes_user on system_notes (changed_by);

-- =============================================================================
-- LOG DES EXÉCUTIONS
-- =============================================================================

create table if not exists sync_runs (
  id              uuid primary key default uuid_generate_v4(),
  mode            text not null,           -- 'full' ou 'incremental'
  status          sync_status not null default 'running',
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  duration_ms     integer,
  stats           jsonb default '{}'::jsonb,  -- {scripts_seen: 123, fields_seen: 456, ...}
  error_message   text,
  triggered_by    text                     -- 'cron' / 'manual' / etc.
);

create index if not exists idx_sync_runs_recent on sync_runs (started_at desc);

-- =============================================================================
-- VUES PRATIQUES
-- =============================================================================

-- Dernier change par entité (utile pour les listes)
create or replace view v_last_change_per_entity as
select distinct on (entity_type, ns_internal_id)
  entity_type,
  ns_internal_id,
  entity_label,
  kind,
  changed_by,
  changed_at
from changes
order by entity_type, ns_internal_id, changed_at desc;

-- Activité des 7 derniers jours
create or replace view v_recent_activity as
select
  c.entity_type,
  c.ns_internal_id,
  c.entity_label,
  c.kind,
  c.changed_by,
  c.changed_at
from changes c
where c.changed_at >= now() - interval '7 days'
order by c.changed_at desc;

-- =============================================================================
-- ROW LEVEL SECURITY (à activer plus tard quand on branche l'app Next.js)
-- =============================================================================
-- Pour l'instant on ne l'active pas — l'extractor utilise la service_role
-- (qui bypass RLS). On l'activera quand on branchera l'auth front.

-- alter table scripts enable row level security;
-- create policy "Allow read for authenticated" on scripts for select to authenticated using (true);
-- (idem pour les autres tables)
