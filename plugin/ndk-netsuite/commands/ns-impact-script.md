---
description: Analyse l'impact d'un script NetSuite (deployments, dernière modif, doc IA)
allowed-tools: Read, Glob, Bash
argument-hint: "<script_id | ns_internal_id | nom partiel>"
---

L'utilisateur te demande l'impact d'un script NetSuite. Identifiant fourni : **$1**

## 1. Charger le contexte

Lit dans cet ordre :

- `${CLAUDE_PLUGIN_ROOT}/skills/ndk-netsuite-context/references/supabase-schema.md`
- `${CLAUDE_PLUGIN_ROOT}/skills/ndk-netsuite-context/references/sql-patterns.md`

## 2. Bundle complet en un appel (RPC)

La RPC `ns_full_context_script` retourne en un coup metadata, ai_doc, deployments, recent_updates :

```sql
select ns_full_context_script('$1') as ctx;
```

Si la réponse contient `{"error": "script not found"}`, dire au user
clairement et arrêter.

## 3. Synthèse

Format :

1. **Le script en 2 lignes** : `business_purpose` (depuis ai_doc) + `script_type`
2. **État** : `is_inactive` ? `is_deleted` ? Récemment modifié (`last_modified`) ?
3. **Deployments actifs** : nombre et statuts. Flag `log_level=DEBUG` en `RELEASED`.
4. **Dernière modification** : `detected_at` + summary IA du dernier `script_update_docs`
5. **Risques en cas de modif** : si critique (préfix NDK + status RELEASED), signaler clairement
6. **Sources** : RPCs appelées, ids consultés
