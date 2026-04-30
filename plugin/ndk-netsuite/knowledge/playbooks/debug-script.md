# Playbook : debug d'un script NetSuite qui se comporte mal

Ordre d'investigation a appliquer quand un dev signale qu'un script NDK
ne marche plus comme avant. Privilegie les RPCs `ns_*` (anti-injection,
plans en cache).

## Etape 1 : resoudre le script

```sql
select * from ns_resolve_script('<script_id ou nom partiel>');
```

Si plusieurs candidats, demander a l'utilisateur de preciser. Verifier
`is_inactive` et `is_deleted` -- si l'un des deux est true, voila la
cause probable.

## Etape 2 : derniers changements detectes

```sql
select sud.detected_at, sud.diff_lines_added, sud.diff_lines_removed,
       sud.summary, sud.detail
from script_update_docs sud
where sud.script_ns_id = '<ns_internal_id_resolu>'
order by sud.detected_at desc
limit 10;
```

Le `summary` Claude du dernier update explique souvent la regression
en une phrase.

## Etape 3 : etat des deployments (RPC)

```sql
select * from ns_script_deployments('<ns_internal_id_resolu>');
```

Causes communes d'un script qui "ne se declenche plus" :

- `status` passe de `RELEASED` a `TESTING` (changement d'audience)
- `is_deployed = false` (toggle desactive)
- `log_level = 'DEBUG'` en prod (a flagger meme si pas cause directe)

## Etape 4 : audit changes table

```sql
select c.detected_at, c.kind, sr.triggered_by, sr.mode
from changes c
join sync_runs sr on sr.id = c.sync_run_id
where c.entity_type in ('script', 'script_source_file')
  and c.ns_internal_id = '<ns_internal_id_resolu>'
order by c.detected_at desc
limit 20;
```

## Etape 5 : impact en cascade (RPC)

```sql
select * from ns_script_callers(
  '<script_id_resolu>',
  '<scripts.id (uuid)>'::uuid
);
```

Identifie quels autres scripts mentionnent le scriptid -- piste pour les
dependances type User Event qui met a jour un field consomme par un
Scheduled Script.

## Etape 6 : source code (avec precaution)

```sql
-- Toujours verifier la taille avant de pull
select length(content) as bytes, ns_last_modified
from script_source_files
where script_ns_id = '<ns_internal_id_resolu>';
```

Si bytes < 8000, OK pour pull avec `select content`. Sinon utiliser
`substring(content from 1 for 8000)` pour un preview.

## Etape 7 : reporter au user

Format de reponse attendu :

1. **Diagnostic** en une phrase
2. **Cause probable** : update detecte, deployment off, field renomme...
3. **Verification a faire** : ce que le dev doit aller voir cote NS UI
4. **Sources** : RPCs appelees, ids consultes

Toujours demander un feedback : "Est-ce que mon diagnostic est juste ?
Si non, /ns-correct pour me corriger."
