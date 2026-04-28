# NetSuite Docs Hub — Front-end

App Next.js 14 (App Router) qui affiche les données extraites par l'extracteur Python depuis Supabase.

## Démarrage

```bash
cd web
cp .env.local.example .env.local
# (les valeurs Supabase sont déjà préremplies pour ce projet POC)
npm install
npm run dev
```

→ App accessible sur http://localhost:3000

## Pages disponibles (v0)

| Route | Contenu |
|---|---|
| `/` | Vue d'ensemble (compteurs + dernier sync run) |
| `/scripts` | Liste paginée + recherche + filtres (type, statut) |
| `/scripts/[id]` | Détail d'un script + ses déploiements + son historique |
| `/deployments` | Tous les déploiements |
| `/fields` | Custom fields (200 premiers) |
| `/custom-records` | Custom record types |
| `/changes` | 100 derniers changements détectés |

## Stack

- Next.js 14 App Router (Server Components)
- @supabase/supabase-js (lecture côté serveur uniquement)
- Tailwind CSS pour le style
- Aucune authentification pour le POC

## Sécurité

- La `SUPABASE_SERVICE_ROLE_KEY` n'est utilisée que dans des Server Components / Route Handlers — jamais envoyée au navigateur.
- Pour aller en production, il faudra activer RLS sur les tables, ajouter Supabase Auth, et utiliser uniquement la publishable key côté client.
