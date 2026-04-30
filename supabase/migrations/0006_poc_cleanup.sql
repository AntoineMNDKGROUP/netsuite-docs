-- 0006_poc_cleanup.sql
--
-- Recentre le POC sur le flux scripts → code source → doc IA.
-- On supprime les entités hors-périmètre :
--   * custom_fields, custom_record_types
--   * saved_searches
--   * workflows
--   * agent_memory, agent_corrections, agent_metrics
--   * knowledge_articles
-- ainsi que les RPCs et embeddings associés.
--
-- Tables conservées :
--   scripts, script_deployments, script_source_files,
--   script_docs, script_update_docs,
--   changes, snapshots, sync_runs, system_notes
--
-- RPCs conservées :
--   ns_resolve_script, ns_full_context_script,
--   ns_script_deployments, ns_recent_script_updates,
--   ns_recent_changes_overview

BEGIN;

-- ───────────────────────────────────────────────────────────────────────────
-- 1. RPCs hors-périmètre
-- ───────────────────────────────────────────────────────────────────────────

DROP FUNCTION IF EXISTS public.ns_field_usages(text) CASCADE;
DROP FUNCTION IF EXISTS public.ns_full_context_field(text) CASCADE;
DROP FUNCTION IF EXISTS public.ns_script_callers(text, uuid) CASCADE;

DROP FUNCTION IF EXISTS public.ns_semantic_search(vector, text[], integer, double precision) CASCADE;
DROP FUNCTION IF EXISTS public.ns_embedding_upsert(text, text, text, text, text, text, text) CASCADE;

-- RPCs liées à la KB / agent memory (peuvent ne pas exister selon l'historique des migrations)
DROP FUNCTION IF EXISTS public.kb_get(text) CASCADE;
DROP FUNCTION IF EXISTS public.kb_search(text) CASCADE;
DROP FUNCTION IF EXISTS public.kb_search(text, text) CASCADE;
DROP FUNCTION IF EXISTS public.search_agent_memory(vector, integer, double precision) CASCADE;
DROP FUNCTION IF EXISTS public.search_agent_corrections(vector, integer, double precision) CASCADE;
DROP FUNCTION IF EXISTS public.log_qa(text, text, text, jsonb) CASCADE;
DROP FUNCTION IF EXISTS public.log_metric(text, text, integer, jsonb) CASCADE;

-- ───────────────────────────────────────────────────────────────────────────
-- 2. Tables hors-périmètre
-- ───────────────────────────────────────────────────────────────────────────

DROP TABLE IF EXISTS public.custom_fields          CASCADE;
DROP TABLE IF EXISTS public.custom_record_types    CASCADE;
DROP TABLE IF EXISTS public.saved_searches         CASCADE;
DROP TABLE IF EXISTS public.workflows              CASCADE;

-- Stack agent / RAG sémantique
DROP TABLE IF EXISTS public.agent_memory           CASCADE;
DROP TABLE IF EXISTS public.agent_corrections      CASCADE;
DROP TABLE IF EXISTS public.agent_metrics          CASCADE;
DROP TABLE IF EXISTS public.knowledge_articles     CASCADE;

-- ───────────────────────────────────────────────────────────────────────────
-- 3. Cleanup des données orphelines dans changes / snapshots
-- ───────────────────────────────────────────────────────────────────────────
-- changes et snapshots gardent l'historique des entités hors-périmètre.
-- On supprime ces lignes pour ne garder que le périmètre POC.

DELETE FROM public.changes
 WHERE entity_type IN (
   'custom_field', 'custom_record_type',
   'saved_search', 'workflow'
 );

DELETE FROM public.snapshots
 WHERE entity_type IN (
   'custom_field', 'custom_record_type',
   'saved_search', 'workflow'
 );

COMMIT;
