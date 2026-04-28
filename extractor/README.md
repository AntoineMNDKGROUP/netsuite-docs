# Extractor

Script Python qui extrait les métadonnées du compte NetSuite (sandbox d'abord) et les pousse dans Supabase.

## Setup local

```bash
cd extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Remplir les credentials dans .env
```

## Usage

```bash
# Extraction complète (à lancer une fois pour le seed)
python -m src.main --mode full

# Extraction incrémentielle (system notes uniquement)
python -m src.main --mode incremental
```

## Modules

| Fichier | Rôle |
|---|---|
| `src/auth.py` | Construction du header OAuth 1.0 TBA pour NetSuite |
| `src/suiteql.py` | Client générique SuiteQL (pagination, retry) |
| `src/extractors/scripts.py` | Extraction des scripts + déploiements |
| `src/extractors/fields.py` | Extraction des custom fields |
| `src/extractors/searches.py` | Extraction des saved searches (via RESTlet) |
| `src/extractors/workflows.py` | Extraction des workflows (via RESTlet) |
| `src/extractors/system_notes.py` | Extraction du change log NetSuite |
| `src/diff.py` | Détection de changements entre snapshots |
| `src/supabase_client.py` | Client Supabase + upserts |
| `src/main.py` | Orchestrateur |
