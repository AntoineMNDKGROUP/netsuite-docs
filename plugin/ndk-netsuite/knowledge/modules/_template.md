# Module <PREFIX> -- <Nom du module>

> Ce template doit etre rempli pour chaque module proprietaire NDK
> (NSA, NUS, LPS, LUS, MU). L'agent charge ces fichiers en priorite avant
> de requeter Supabase.

## Vue d'ensemble

- **Equipe** : <equipe responsable>
- **Tech lead** : <nom + Slack handle>
- **Domaine fonctionnel** : <ce que fait le module en 2-3 phrases>
- **Dependances cle** : <autres modules NDK ou SuiteApps tiers requis>

## Scripts critiques

Liste des scripts dont la modification a un fort impact business.
L'agent doit alerter le user quand il detecte un changement sur ces
scripts.

| scriptid | Nom | Type | Pourquoi critique |
|----------|-----|------|--------------------|
| `customscript_xxx_yyy` | XXX_yyy | UserEvent | <raison metier> |

## Custom records utilises

| scriptid | Role |
|----------|------|
| `customrecord_xxx_yyy` | <a quoi sert ce custom record> |

## Custom fields cles

| scriptid | Sur quel record | Role |
|----------|-----------------|------|
| `custbody_xxx_state` | salesorder | <signification du field, ses valeurs possibles> |

## Workflows associes

| scriptid | Record cible | Declencheurs | Transitions importantes |
|----------|--------------|--------------|--------------------------|
| `customworkflow_xxx_yyy` | salesorder | onCreate, onSave | <etats et conditions> |

## Saved searches importantes

| scriptid | Audience | Frequence d'usage |
|----------|----------|-------------------|
| `customsearch_xxx_kpi` | <qui s'en sert> | <quotidien / hebdo / ad-hoc> |

## Pieges connus

Liste de gotchas, edge cases, ou bugs deja rencontres :

- **<titre court>** : <description du piege et comment l'eviter>

## Playbooks lies

- `knowledge/playbooks/<file>.md` : <a quel cas il s'applique>

## Liens utiles

- Doc interne Notion : <url>
- Channel Slack : <#channel>
- Owner principal : <email>
