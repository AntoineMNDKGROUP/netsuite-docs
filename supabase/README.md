# Supabase – Schéma & Migrations

Schéma Postgres de l'app NetSuite Documentation.

## Tables principales

| Table | Rôle |
|---|---|
| `scripts` | État courant de chaque script NetSuite |
| `script_deployments` | Déploiements (statut, contexte, audience) |
| `custom_fields` | Champs custom (transactions, entities, items, custom records) |
| `saved_searches` | Saved searches |
| `workflows` | Workflows |
| `snapshots` | Historique JSONB de chaque entité (1 ligne par sync où l'objet a changé) |
| `changes` | Log des diffs détectés (qui/quand/quoi) |
| `system_notes` | Mirror de l'audit trail NetSuite |
| `sync_runs` | Log des exécutions de l'extractor (succès/échec, durée, volumes) |

## Appliquer les migrations

Les migrations sont dans `migrations/` au format SQL. À appliquer dans le SQL Editor de Supabase ou via la CLI Supabase :

```bash
npx supabase db push
```

## Contraintes communes

- Toutes les tables ont `ns_internal_id` (TEXT) comme identifiant NetSuite.
- Toutes les tables ont `first_seen_at` et `last_seen_at` pour suivre la présence dans le temps.
- Les snapshots utilisent JSONB pour flexibilité, indexés sur `entity_type` + `ns_internal_id`.
