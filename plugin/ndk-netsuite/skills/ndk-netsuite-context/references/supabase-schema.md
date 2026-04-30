# Schema Supabase ndk-netsuite-docs (POC focus)

Référence des VRAIES colonnes du schema, copiées depuis information_schema.
Toutes les `id` sont des `uuid`, toutes les jointures se font via
`ns_internal_id` (text) qui correspond à l'internal id NetSuite.

> **Important** : préférer les RPCs `ns_*` listées plus bas pour éviter le
> SQL inline (anti-injection + plans en cache + meilleure clarté).

## Périmètre POC

Le POC ne couvre que **les scripts** et leur cycle de vie :
ingestion → code source → doc IA. Les autres entités (custom_fields,
custom_record_types, saved_searches, workflows, agent_memory, KB, RAG
sémantique) ont été retirées en migration `0006_poc_cleanup.sql` /
`0007_drop_ns_embeddings.sql`.

## scripts

```
scripts (
    id                  uuid    primary key
    ns_internal_id      text    -- internal id NetSuite (clé de jointure)
    script_id           text    -- ex 'CUSTOMSCRIPT_ZC_NSA_VALIDATOR'
    name                text
    script_type         text    -- USEREVENT, SCHEDULED, RESTLET, MAPREDUCE, ...
    api_version         text
    script_file         text    -- ns_internal_id du fichier source
    description         text
    is_inactive         boolean
    owner               text
    date_created        timestamptz
    last_modified       timestamptz
    raw                 jsonb
    is_deleted          boolean
    deleted_at          timestamptz
)
```

> Pas de colonne `ai_doc` ici. La doc IA est dans `script_docs`
> (jointure par `script_ns_id = scripts.ns_internal_id`).

## script_deployments

```
script_deployments (
    id                  uuid
    ns_internal_id      text
    script_ns_id        text    -- FK vers scripts.ns_internal_id
    deployment_id       text
    title               text
    status              text    -- TESTING, RELEASED, NOT_SCHEDULED
    is_deployed         boolean
    log_level           text
    audience            jsonb
    context             jsonb
    raw                 jsonb
    is_deleted, deleted_at
)
```

> Pas de colonne `record_type` directement — c'est dans `context` jsonb.

## script_source_files

```
script_source_files (
    id                  uuid
    ns_internal_id      text    -- file internalid NetSuite
    script_ns_id        text    -- FK vers scripts.ns_internal_id
    file_name           text
    file_path           text
    content             text    -- code source COMPLET (peut être 50 KB)
    content_sha256      text
    ns_last_modified    timestamptz
    is_deleted, deleted_at
)
```

⚠ Ne JAMAIS faire `select content` sans filtre. Toujours :

```sql
select length(content) as bytes
from script_source_files
where script_ns_id = '<id>';
```

## script_docs (doc IA des scripts)

```
script_docs (
    id                  uuid
    script_ns_id        text    -- FK vers scripts.ns_internal_id
    business_purpose    text
    technical_summary   text
    usage_notes         text
    tags                text[]
    related_scripts     text[]
    content_md          text    -- markdown complet de la doc (peut être null)
    ai_generated        boolean
    last_ai_generated_at timestamptz
)
```

## script_update_docs (doc IA des diffs de code)

```
script_update_docs (
    id                  uuid
    script_ns_id        text    -- FK vers scripts.ns_internal_id
    sha256_before       text
    sha256_after        text
    summary             text    -- résumé Claude
    detail              text
    diff_lines_added    integer
    diff_lines_removed  integer
    detected_at         timestamptz
    ai_tokens_used      integer
)
```

## changes / snapshots / sync_runs

```
changes (
    id                  uuid
    entity_type         enum    -- 'script' | 'script_deployment' | 'script_source_file' | 'system_note'
    ns_internal_id      text
    kind                enum    -- 'created' | 'updated' | 'deleted'
    diff                jsonb
    detected_at         timestamptz
    sync_run_id         uuid
)

snapshots (
    id                  uuid
    entity_type         enum
    ns_internal_id      text
    payload             jsonb
    content_hash        text
    captured_at         timestamptz
    -- contrainte unique : (entity_type, ns_internal_id, content_hash)
)

sync_runs (
    id                  uuid
    mode                text    -- 'full' | 'incremental' | 'ping'
    status              enum    -- 'running' | 'success' | 'partial' | 'failed'
    started_at, finished_at
    duration_ms         integer
    stats               jsonb
    triggered_by        text    -- 'github-actions' | 'manual' | 'cli'
)
```

## system_notes (audit trail NetSuite)

Trace les modifications natives NetSuite. Utile pour répondre « qui a
modifié X » avant le sync.

## RPCs disponibles (à privilégier sur le SQL inline)

| RPC | Usage |
|-----|-------|
| `ns_resolve_script(text)` | Résoud par script_id / ns_internal_id / nom partiel |
| `ns_full_context_script(text)` | Bundle complet : metadata + ai_doc + deployments + recent_updates |
| `ns_script_deployments(text)` | Deployments d'un script (par `script_ns_id`) |
| `ns_recent_script_updates(int)` | Derniers updates avec doc IA (fenêtre en heures) |
| `ns_recent_changes_overview(int)` | Compte des changes par type/kind |

## Pièges courants à éviter

- ❌ Joindre `scripts.id` avec `script_deployments.script_ns_id` — la jointure est `scripts.ns_internal_id = script_deployments.script_ns_id`.
- ❌ `select * from scripts` — la colonne `raw` peut faire 5-10 KB. Choisir les colonnes.
- ❌ `select content from script_source_files` sans where — 100+ MB d'un coup.
- ❌ Filtrer sur `scripts.scriptid` — le bon nom est `script_id`.
- ❌ Chercher `ai_doc` dans `scripts` — c'est dans `script_docs.content_md`.
