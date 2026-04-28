"""Extraction des custom fields NetSuite — stratégie en 2 niveaux.

Approche 1 (préférée) : SuiteQL sur la table `customfield` (singulier, unifiée).
  Couvre BODY, COLUMN, ENTITY, ITEM, OTHER, CRM, CUSTOMRECORD via la colonne fieldtype.

Approche 2 (fallback) : REST /metadata-catalog. Plus lent mais marche sans privilèges
  spécifiques sur la table customfield. Utile si l'approche 1 lève "Record not found".
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..metadata import MetadataClient
from ..suiteql import SuiteQLClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)

# NetSuite tolère ~10 requêtes parallèles sur les endpoints REST. On reste sage.
PARALLEL_WORKERS = 8


# ============================================================================
# APPROCHE 1 : SuiteQL sur la table 'customfield' unifiée
# ============================================================================

_CUSTOMFIELD_QUERY = """
SELECT
    cf.internalid           AS ns_internal_id,
    cf.scriptid             AS field_id,
    cf.name                 AS name,
    cf.label                AS label,
    cf.description          AS description,
    cf.fieldtype            AS field_type_category,
    cf.fieldvaluetype       AS field_type,
    cf.fieldvaluetyperecord AS field_value_record_type,
    cf.recordtype           AS applies_to_record_type,
    cf.ismandatory          AS is_mandatory,
    cf.isinactive           AS is_inactive,
    cf.defaultvalue         AS default_value,
    BUILTIN.DF(cf.owner)    AS owner_name
FROM customfield cf
"""


def _norm_bool(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in {"T", "TRUE", "1", "YES"}


_FIELDTYPE_TO_CATEGORY = {
    "TRANSACTION": "BODY",
    "COLUMN": "COLUMN",
    "ENTITY": "ENTITY",
    "ITEM": "ITEM",
    "OTHER": "OTHER",
    "CRM": "CRM",
    "CUSTOMRECORD": "RECORD",
    "RECORD": "RECORD",
}


def _suiteql_to_record(row: dict[str, Any]) -> dict[str, Any]:
    cat_raw = (row.get("field_type_category") or "OTHER").upper()
    return {
        "ns_internal_id": str(row["ns_internal_id"]),
        "field_id": row.get("field_id"),
        "label": row.get("label") or row.get("name") or "(unlabeled)",
        "field_type": row.get("field_type"),
        "field_category": _FIELDTYPE_TO_CATEGORY.get(cat_raw, cat_raw),
        "applies_to": (
            [str(row["applies_to_record_type"])]
            if row.get("applies_to_record_type")
            else []
        ),
        "is_mandatory": _norm_bool(row.get("is_mandatory")),
        "is_inactive": _norm_bool(row.get("is_inactive")),
        "default_value": row.get("default_value"),
        "description": row.get("description"),
        "owner": row.get("owner_name"),
        "raw": row,
    }


def _try_suiteql(
    suiteql: SuiteQLClient,
    store: SupabaseStore,
    run_id: str,
    limit: int | None = None,
) -> dict[str, int] | None:
    """Tente l'approche SuiteQL. Retourne None si la table n'existe pas (-> fallback)."""
    try:
        logger.info("[Approche 1] SuiteQL sur la table customfield (limit=%s)...", limit or "no limit")
        rows = list(suiteql.query(_CUSTOMFIELD_QUERY, limit=limit))
        logger.info("[Approche 1] Fetched %s custom fields via SuiteQL", len(rows))
    except Exception as e:
        logger.warning("[Approche 1] SuiteQL customfield failed: %s — falling back to metadata-catalog", e)
        return None

    records = [_suiteql_to_record(r) for r in rows]
    if not records:
        logger.info("[Approche 1] 0 rows from customfield, falling back")
        return None

    stats = store.bulk_sync(
        table="custom_fields",
        entity_type="custom_field",
        records=records,
        run_id=run_id,
        label_keys=("label", "field_id"),
    )

    if not limit:
        seen_ids = [r["ns_internal_id"] for r in records]
        deletion_stats = store.detect_deletions(
            table="custom_fields",
            entity_type="custom_field",
            seen_ns_ids=seen_ids,
            run_id=run_id,
            label_column="label",
        )
        stats["newly_deleted"] = deletion_stats["newly_deleted"]
        stats["total_deleted"] = deletion_stats["total_deleted"]

    stats["source"] = "suiteql:customfield"
    return stats


# ============================================================================
# APPROCHE 2 : REST metadata-catalog (fallback)
# ============================================================================

_CUSTOM_PREFIXES = ("custbody", "custcol", "custentity", "custitem", "custrecord", "custevent")


def _category_from_field_id(field_id: str) -> str:
    fid = field_id.lower()
    if fid.startswith("custbody"):
        return "BODY"
    if fid.startswith("custcol"):
        return "COLUMN"
    if fid.startswith("custentity"):
        return "ENTITY"
    if fid.startswith("custitem"):
        return "ITEM"
    if fid.startswith("custrecord"):
        return "RECORD"
    if fid.startswith("custevent"):
        return "EVENT"
    return "OTHER"


def _is_custom_field(prop_name: str) -> bool:
    return prop_name.lower().startswith(_CUSTOM_PREFIXES)


def _extract_fields_from_schema(record_type: str, schema: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    properties = schema.get("properties", {}) or {}
    for prop_name, prop_def in properties.items():
        if not _is_custom_field(prop_name):
            continue
        prop_def = prop_def or {}
        out.append({
            "field_id": prop_name,
            "label": prop_def.get("title") or prop_def.get("description") or prop_name,
            "field_type": prop_def.get("type") or prop_def.get("format") or "unknown",
            "field_category": _category_from_field_id(prop_name),
            "applies_to": [record_type],
            "is_mandatory": bool(prop_def.get("nullable") is False),
            "description": prop_def.get("description"),
            "raw": {"source_record": record_type, "swagger": prop_def},
        })
    return out


def _try_metadata(
    metadata: MetadataClient,
    store: SupabaseStore,
    run_id: str,
    limit: int | None = None,
) -> dict[str, int]:
    logger.info("[Approche 2] Listing record types via /metadata-catalog...")
    record_types = metadata.list_record_types()
    logger.info("[Approche 2] Found %s record types", len(record_types))

    if limit is not None:
        record_types = record_types[:limit]
        logger.info("[Approche 2] Limiting to %s record types", limit)

    fields_by_id: dict[str, dict[str, Any]] = {}

    def _fetch_one(rt: str) -> tuple[str, list[dict[str, Any]] | None, str | None]:
        """Fetch + parse pour un record type. Retourne (rt, fields_list, error)."""
        try:
            meta = metadata.get_record_metadata(rt)
        except Exception as e:
            return rt, None, str(e)[:120]

        schemas: dict[str, dict[str, Any]] = {}
        if isinstance(meta.get("definitions"), dict):
            schemas.update(meta["definitions"])
        components = meta.get("components") or {}
        if isinstance(components.get("schemas"), dict):
            schemas.update(components["schemas"])
        if isinstance(meta.get("properties"), dict):
            schemas[rt] = {"properties": meta["properties"]}

        out: list[dict[str, Any]] = []
        for _, schema in schemas.items():
            out.extend(_extract_fields_from_schema(rt, schema))
        return rt, out, None

    completed = 0
    skipped = 0
    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        futures = {ex.submit(_fetch_one, rt): rt for rt in record_types}
        for fut in as_completed(futures):
            rt, fields, err = fut.result()
            completed += 1
            if err:
                skipped += 1
                logger.debug("  skip %s: %s", rt, err)
            elif fields:
                for f in fields:
                    fid = f["field_id"]
                    if fid in fields_by_id:
                        if rt not in fields_by_id[fid]["applies_to"]:
                            fields_by_id[fid]["applies_to"].append(rt)
                    else:
                        fields_by_id[fid] = f
            if completed % 50 == 0 or completed == len(record_types):
                logger.info(
                    "  %s/%s records processed (%s skipped), %s unique fields so far",
                    completed, len(record_types), skipped, len(fields_by_id),
                )

    records = []
    for fid, f in fields_by_id.items():
        records.append({
            "ns_internal_id": fid,
            "field_id": fid,
            "label": f.get("label") or fid,
            "field_type": f.get("field_type"),
            "field_category": f.get("field_category"),
            "applies_to": f["applies_to"],
            "is_mandatory": f.get("is_mandatory", False),
            "is_inactive": False,
            "description": f.get("description"),
            "raw": f.get("raw", {}),
        })

    stats = store.bulk_sync(
        table="custom_fields",
        entity_type="custom_field",
        records=records,
        run_id=run_id,
        label_keys=("label", "field_id"),
    )

    if not limit:
        seen_ids = [r["ns_internal_id"] for r in records]
        deletion_stats = store.detect_deletions(
            table="custom_fields",
            entity_type="custom_field",
            seen_ns_ids=seen_ids,
            run_id=run_id,
            label_column="label",
        )
        stats["newly_deleted"] = deletion_stats["newly_deleted"]
        stats["total_deleted"] = deletion_stats["total_deleted"]

    stats["source"] = "rest:metadata-catalog"
    stats["records_scanned"] = len(record_types)
    return stats


# ============================================================================
# Entrée publique
# ============================================================================

def extract_custom_fields(
    suiteql: SuiteQLClient,
    metadata: MetadataClient,
    store: SupabaseStore,
    run_id: str,
    limit: int | None = None,
) -> dict[str, int]:
    """Extrait tous les custom fields. Tente d'abord SuiteQL, fallback metadata-catalog."""
    result = _try_suiteql(suiteql, store, run_id, limit=limit)
    if result is not None:
        logger.info("✅ Custom fields via SuiteQL: %s", result)
        return result

    result = _try_metadata(metadata, store, run_id, limit=limit)
    logger.info("✅ Custom fields via metadata-catalog: %s", result)
    return result
