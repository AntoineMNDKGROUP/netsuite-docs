---
description: Brief des dernières modifications détectées dans NetSuite
allowed-tools: Read, Bash
argument-hint: "[période: 24h | 7d | 30d]"
---

L'utilisateur veut un brief des updates récents. Période demandée : **$1**
(par défaut `24h` si non fourni).

## 1. Résoudre la fenêtre (en heures)

| Argument | Heures |
|----------|--------|
| vide / `24h` | 24 |
| `7d` | 168 |
| `30d` | 720 |

## 2. Vue d'ensemble (RPC)

```sql
select * from ns_recent_changes_overview(<hours>);
```

## 3. Modifications de scripts avec doc IA (RPC)

```sql
select * from ns_recent_script_updates(<hours>);
```

Pour chaque entrée :
- **Quand** : timestamp formaté
- **Script** : name + script_id
- **Volume** : `+diff_lines_added / -diff_lines_removed`
- **Résumé IA** : `summary`
- **Module** : préfix dérivé du `name` (NSA / NUS / LPS / LUS / MU / autre)

## 4. Suppressions

```sql
select entity_type, count(*) as nb
from changes
where kind = 'deleted'
  and detected_at >= now() - make_interval(hours => <hours>)
group by entity_type
order by nb desc;
```

## 5. État du pipeline

```sql
select started_at, finished_at, status, mode, triggered_by, duration_ms
from sync_runs
where started_at >= now() - make_interval(hours => <hours>)
order by started_at desc
limit 5;
```

Si un run `failed` ou `partial`, le signaler en HAUT du brief.

## 6. Synthèse

1. **TL;DR** : 1 phrase, ex « 12 scripts modifiés dans les dernières 24h, dont 3 sur le module LPS »
2. **Modifications de scripts** : tableau timestamp / name / +X-Y / résumé IA
3. **Suppressions** : si > 0
4. **État du pipeline** : derniers runs (rouge si échec)

Si tout est `unchanged` : « Aucun changement détecté sur la période. »
