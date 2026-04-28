"""Diagnostic complet pour comprendre pourquoi les fichiers ne sont pas accessibles.

Usage: python -m src.debug_file <file_id>
       python -m src.debug_file 27168304
"""
from __future__ import annotations

import json
import sys

import requests

from .auth import build_oauth
from .config import load_settings, setup_logging
from .metadata import MetadataClient


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python -m src.debug_file <file_id>")
        return 1

    file_id = argv[1]
    settings = load_settings()
    setup_logging(settings.log_level)
    auth = build_oauth(settings)

    base = settings.ns_rest_base_url

    # 1. Le record 'file' existe-t-il dans le metadata-catalog ?
    print("=== 1. Vérification: 'file' dans le metadata-catalog ===")
    mc = MetadataClient(settings)
    try:
        types = mc.list_record_types()
        print(f"Total record types : {len(types)}")
        candidates = [t for t in types if "file" in t.lower() or "media" in t.lower() or "script" in t.lower()]
        print(f"Records contenant 'file', 'media' ou 'script' : {len(candidates)}")
        for c in sorted(candidates)[:30]:
            print(f"  - {c}")
    except Exception as e:
        print(f"❌ list types failed: {e}")

    # 2. Tester plusieurs endpoints
    print()
    print(f"=== 2. Test endpoints REST pour file_id={file_id} ===")
    candidates = [
        f"{base}/services/rest/record/v1/file/{file_id}",
        f"{base}/services/rest/record/v1/scriptFile/{file_id}",
        f"{base}/services/rest/record/v1/scriptfile/{file_id}",
        f"{base}/services/rest/record/v1/mediaItem/{file_id}",
        f"{base}/services/rest/record/v1/mediaitem/{file_id}",
        # En SuiteScript, les fichiers sont accessibles via des endpoints SOAP
        # Pas testable simplement en REST sans RESTlet custom.
    ]
    s = requests.Session()
    for url in candidates:
        try:
            r = s.get(url, auth=auth, headers={"Accept": "application/json"}, timeout=30)
            print(f"  [{r.status_code}] {url}")
            if r.status_code < 400:
                data = r.json()
                print(f"    → keys: {list(data.keys())}")
                if "url" in data:
                    print(f"    → download url: {data['url']}")
        except Exception as e:
            print(f"  [ERR ] {url}: {e}")

    # 3. Tester via l'endpoint script (pour récupérer les liens)
    print()
    print(f"=== 3. GET /script via le scriptFile ===")
    # On essaie de récupérer le script qui a ce fichier pour voir comment il y accède
    script_url = f"{base}/services/rest/record/v1/script/3744"
    try:
        r = s.get(script_url, auth=auth, headers={"Accept": "application/json"}, timeout=30)
        print(f"  [{r.status_code}] {script_url}")
        if r.status_code < 400:
            data = r.json()
            print(f"    → keys: {list(data.keys())}")
            if "scriptFile" in data or "scriptfile" in data:
                sf = data.get("scriptFile") or data.get("scriptfile")
                print(f"    → scriptFile: {json.dumps(sf, indent=2)}")
    except Exception as e:
        print(f"  [ERR ] {e}")

    # 4. Si on trouve une URL de download, on l'essaie
    print()
    print(f"=== 4. Suggestion ===")
    print("Si tous les endpoints retournent 404 :")
    print("  - Vérifier dans NetSuite : Setup → Company → Enable Features → SuiteCloud")
    print("    → cocher 'REST RECORD SERVICE'")
    print("  - Vérifier le rôle 'Documentation Reader' :")
    print("    → onglet Permissions → sous-onglet Lists")
    print("    → ajouter 'Documents and Files' niveau View")
    print("  - Les RESTlets custom sont l'alternative officielle pour récupérer")
    print("    le contenu des fichiers script si l'API REST file ne marche pas.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
