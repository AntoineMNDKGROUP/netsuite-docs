---
description: Explique en langage clair ce que fait un script NetSuite
allowed-tools: Read, Glob, Bash
argument-hint: "<script_id | ns_internal_id | nom partiel>"
---

L'utilisateur veut une explication en français clair de ce que fait le
script : **$1**

## 1. Résoudre le script (RPC)

```sql
select * from ns_resolve_script('$1');
```

Si plusieurs candidats, demander au user de préciser.

## 2. Récupérer la doc IA

```sql
select sd.business_purpose, sd.technical_summary, sd.usage_notes,
       sd.tags, sd.last_ai_generated_at, sd.ai_generated,
       s.last_modified
from script_docs sd
join scripts s on s.ns_internal_id = sd.script_ns_id
where sd.script_ns_id = '<ns_internal_id_resolu>'
order by sd.last_ai_generated_at desc nulls last
limit 1;
```

## 3. Stratégie selon ce qu'on a

### Cas A : doc IA présente et à jour

Si `last_ai_generated_at >= last_modified`, la doc IA est à jour. La
rendre telle quelle, en la formatant pour la lecture, et en citant la
date de génération.

### Cas B : doc IA présente mais obsolète

Si `last_ai_generated_at < last_modified`, signaler explicitement :

> Doc générée le <date>. Le script a été modifié le <date_modif>. Pour
> régénérer une doc à jour, lance :
> `cd extractor && ./bin/run.sh extract --ai-docs --ai-docs-force` (ne
> régénère que ce script).

Vérifier ensuite les `script_update_docs` récents :

```sql
select detected_at, summary
from script_update_docs
where script_ns_id = '<ns_internal_id_resolu>'
order by detected_at desc
limit 5;
```

### Cas C : doc IA absente

Si rien dans `script_docs`, on n'a pas de doc générée. Deux options :

1. Si le source code est accessible, lire un preview pour analyser :

```sql
select substring(content from 1 for 8000) as preview, length(content) as total_bytes
from script_source_files
where script_ns_id = '<ns_internal_id_resolu>'
limit 1;
```

Travailler sur le preview seulement (jamais avaler 50 KB d'un coup).

2. Sinon, dire qu'on ne peut pas analyser sans le source, suggérer
   `./bin/run.sh extract --script-files` pour rapatrier le code.

## 4. Format de l'explication

1. **Identité** : script_id, name, type SuiteScript (User Event, Scheduled,
   RESTlet...), api_version
2. **Rôle** : 2-3 phrases en langage métier
3. **Mécanisme** : sur quel record il s'applique, quels events, ce qu'il
   modifie ou retourne
4. **Dépendances** : modules `N/*` importés, autres scripts appelés
5. **Note de version** : si récemment modifié, mentionner le summary du
   dernier `script_update_docs`
6. **Sources** : doc IA ou source code parsé à la volée

## 5. Si modification prévue

Lui rappeler : `/ns-impact-script $1` avant pour voir les deployments et
la dernière modif IA.
