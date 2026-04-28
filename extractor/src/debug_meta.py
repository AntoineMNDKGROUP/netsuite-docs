"""Outil de debug : dump la structure metadata-catalog pour un record type donné.

Usage:
    python -m src.debug_meta customer
"""
from __future__ import annotations

import json
import sys

from .config import load_settings, setup_logging
from .metadata import MetadataClient


CUSTOM_PREFIXES = ("custbody", "custcol", "custentity", "custitem", "custrecord", "custevent")


def _is_custom(name: str) -> bool:
    return name.lower().startswith(CUSTOM_PREFIXES)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: python -m src.debug_meta <record_type>")
        return 1

    record_type = argv[1]
    settings = load_settings()
    setup_logging(settings.log_level)

    client = MetadataClient(settings)
    print(f"\n=== Fetching metadata for: {record_type} ===\n")

    try:
        meta = client.get_record_metadata(record_type)
    except Exception as e:
        print(f"ERROR: {e}")
        return 2

    print("Top-level keys:", list(meta.keys()))
    print()
    if "openapi" in meta:
        print("OpenAPI:", meta["openapi"])
    if "swagger" in meta:
        print("Swagger:", meta["swagger"])
    print()

    # Collecter tous les schemas selon la version
    schemas: dict[str, dict] = {}
    if isinstance(meta.get("definitions"), dict):
        schemas.update(meta["definitions"])
    components = meta.get("components") or {}
    if isinstance(components.get("schemas"), dict):
        schemas.update(components["schemas"])

    print(f"Total schemas trouvés : {len(schemas)}")
    print()

    total_customs = 0
    customs_found: list[str] = []
    schemas_with_customs: list[tuple[str, int]] = []

    for name, schema in schemas.items():
        props = (schema or {}).get("properties", {}) or {}
        cust_props = [p for p in props if _is_custom(p)]
        if cust_props:
            schemas_with_customs.append((name, len(cust_props)))
            total_customs += len(cust_props)
            customs_found.extend(cust_props)

    print(f"📊 RÉSUMÉ")
    print(f"  Schemas avec custom fields : {len(schemas_with_customs)}")
    print(f"  Total occurrences de customs : {total_customs}")
    print(f"  Customs uniques : {len(set(customs_found))}")
    print()

    if schemas_with_customs:
        print("Top 10 schemas avec customs :")
        for name, cnt in sorted(schemas_with_customs, key=lambda x: -x[1])[:10]:
            print(f"  - {name}: {cnt} customs")
        print()
        print("Premiers 10 customs trouvés :")
        for c in customs_found[:10]:
            print(f"  - {c}")

    out_path = f"/tmp/metadata_{record_type}.json"
    with open(out_path, "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"\n📁 JSON complet sauvé : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
