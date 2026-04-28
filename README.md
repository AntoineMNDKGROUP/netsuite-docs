# NetSuite Documentation Hub

Application interne pour documenter automatiquement les customisations du compte NetSuite NDK et tracker tous les changements (scripts, custom fields, saved searches, workflows).

## Architecture

```
[NetSuite Sandbox/Prod]
        │
        │  REST API + SuiteQL  (OAuth 1.0 TBA)
        ▼
[Extractor Python]   ◄── cron quotidien (GitHub Actions)
        │
        │  upsert + diff
        ▼
[Supabase Postgres]
        ▲
        │  read
        │
[Next.js App on Vercel]
```

## Structure du repo

```
netsuite-docs/
├── extractor/          # Script Python d'extraction NetSuite → Supabase
│   ├── src/
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── supabase/           # Schéma SQL et migrations
│   ├── migrations/
│   └── README.md
├── web/                # App Next.js (front-end)
│   └── (à scaffold avec `npx create-next-app`)
├── .github/
│   └── workflows/      # CI + cron quotidien
├── docs/               # Documentation interne du projet
└── README.md
```

## Stack

| Couche | Techno |
|---|---|
| Extraction | Python 3.11 + `requests` + `requests-oauthlib` |
| Base de données | Supabase (Postgres 15) |
| Front-end | Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui |
| Hosting front | Vercel |
| Scheduler | GitHub Actions (cron quotidien) |
| Auth | Supabase Auth (email/password, restreint à NDK) |

## Sources de vérité NetSuite

| Objet documenté | Source |
|---|---|
| Scripts | SuiteQL sur `script` + `scriptdeployment` |
| Custom Fields | SuiteQL sur `customfield`, `customrecordcustomfield` |
| Saved Searches | RESTlet custom (l'API REST n'expose pas les définitions) |
| Workflows | RESTlet custom |
| Historique des changements | SuiteQL sur `systemnote` (audit trail natif NetSuite) |

## Démarrage rapide

À compléter une fois les comptes créés et les credentials configurés.

## Statut du projet

🚧 En cours de mise en place — voir la TaskList Cowork pour le suivi.
