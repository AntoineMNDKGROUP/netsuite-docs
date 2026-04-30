# Patterns SQL fréquents (POC focus)

Privilégier les RPCs `ns_*` (paramétrées, anti-injection, plans en cache).
Si un cas n'est pas couvert par une RPC, écrire du SQL direct en respectant
les VRAIES colonnes (cf. `supabase-schema.md`).

## Résoudre un script (RPC)

```sql
-- Accept script_id, ns_internal_id ou nom partiel
select * from ns_resolve_script('CUSTOMSCRIPT_ZC_NSA_VALIDATOR');
select * from ns_resolve_script('NSA validator');
select * from ns_resolve_script('4585');
```

## Bundle complet d'un script (RPC)

```sql
-- Retourne metadata + ai_doc + deployments + recent_updates en un coup
select ns_full_context_script('customscript_xxx') as ctx;
```

## Deployments d'un script (RPC)

```sql
-- p_script_ns_id = le ns_internal_id du script (text)
select * from ns_script_deployments('4585');
```

## Derniers updates avec doc IA (RPC)

```sql
select * from ns_recent_script_updates(24);   -- dernières 24h
select * from ns_recent_script_updates(168);  -- 7 derniers jours
```

## Vue d'ensemble des changes (RPC)

```sql
select * from ns_recent_changes_overview(24);
-- entity_type | kind | nb
```

## Patterns SQL inline (quand pas de RPC)

### Filtre NDK custom (par préfix)

```sql
where name ~* '^(NSA|NUS|LPS|LUS|MU)[ _-]'
  and is_deleted = false
  and is_inactive = false
```

### Doc IA d'un script (table séparée)

```sql
select sd.business_purpose, sd.technical_summary, sd.content_md, sd.last_ai_generated_at
from script_docs sd
where sd.script_ns_id = '4585'
order by sd.last_ai_generated_at desc nulls last
limit 1;
```

### Source code : taille avant pull

```sql
-- Toujours faire ça AVANT un select content
select length(content) as bytes, ns_last_modified
from script_source_files
where script_ns_id = '4585';
```

Si bytes < 8000 : OK pour pull avec `select content`.
Sinon : faire un `substring(content from 1 for 8000)` ou ne pas pull du tout.

### Histoire d'un script (changes)

```sql
select c.detected_at, c.kind, sr.triggered_by, sr.mode
from changes c
join sync_runs sr on sr.id = c.sync_run_id
where c.entity_type = 'script'
  and c.ns_internal_id = '4585'
order by c.detected_at desc
limit 50;
```

### Snapshots (versions historiques)

```sql
select id, captured_at, content_hash, length(payload::text) as bytes
from snapshots
where entity_type = 'script_source_file'
  and ns_internal_id = '<file_ns_internal_id>'
order by captured_at desc
limit 5;
```

## Anti-patterns à éviter

- ❌ `select *` sur scripts (colonne `raw` jsonb peut être lourde)
- ❌ `select content` sans filtre ciblé
- ❌ Joindre par `id` au lieu de `ns_internal_id` ou clés texte natives
- ❌ Hardcoder `scripts.scriptid` → c'est `script_id`
- ❌ Chercher `scripts.ai_doc` → c'est dans `script_docs.content_md`

## Conventions d'identifiants NetSuite

- `customscript_*` → scripts (`scripts.script_id` lowercase, mais data en MAJ : `CUSTOMSCRIPT_*`)
- `customdeploy_*` → deployments (`deployment_id`)
