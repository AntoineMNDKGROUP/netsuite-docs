"""Extraction des custom record types via SuiteQL — fallback chain."""
from __future__ import annotations

import logging
from typing import Any

import requests

from ..suiteql import SuiteQLClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)

# Variantes : on tente d'abord avec les noms qu'on espère, puis on dégrade.
QUERY_VARIANTS = [
    # V1 : id + camelCase
    """
    SELECT
        crt.id           AS ns_internal_id,
        crt.scriptid     AS record_id,
        crt.name         AS name,
        crt.description  AS description,
        crt.isinactive   AS is_inactive
    FROM CustomRecordType crt
    """,
    # V2 : internalid + lowercase
    """
    SELECT
        crt.internalid   AS ns_internal_id,
        crt.scriptid     AS record_id,
        crt.name         AS name,
        crt.description  AS description,
        crt.isinactive   AS is_inactive
    FROM customrecordtype crt
    """,
    # V3 : minimal sans description (au cas où description ne serait pas accessible)
    """
    SELECT
        crt.scriptid     AS ns_internal_id,
        crt.scriptid     AS record_id,
        crt.name         AS name,
        crt.isinactive   AS is_inactive
    FROM customrecordtype crt
    """,
]


def _norm_bool(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in {"T", "TRUE", "1", "YES"}


def _to_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ns_internal_id": str(row["ns_internal_id"]),
        "record_id": row.get("record_id"),
        "name": row.get("name") or "(unnamed)",
        "description": row.get("description"),
        "is_inactive": _norm_bool(row.get("is_inactive")),
        "raw": row,
    }


def extract_custom_record_types(
    suiteql: SuiteQLClient,
    store: SupabaseStore,
    run_id: str,
    limit: int | None = None,
) -> dict[str, int]:
    logger.info("Fetching custom record types (limit=%s)...", limit or "no limit")
    last_err = None
    rows: list[dict[str, Any]] = []
    for i, q in enumerate(QUERY_VARIANTS, 1):
        try:
            rows = list(suiteql.query(q, limit=limit))
            logger.info("  → custom_records variante v%s OK (%s rows)", i, len(rows))
            break
        except requests.exceptions.HTTPError as e:
            logger.warning("  → custom_records variante v%s échec (%s)", i, str(e)[:80])
            last_err = e
            continue
    else:
        raise last_err if last_err else RuntimeError("Toutes les variantes ont échoué")

    records = [_to_record(r) for r in rows]
    stats = store.bulk_sync(
        table="custom_record_types",
        entity_type="custom_record_type",
        records=records,
        run_id=run_id,
    )

    if not limit:
        seen_ids = [r["ns_internal_id"] for r in records]
        deletion_stats = store.detect_deletions(
            table="custom_record_types",
            entity_type="custom_record_type",
            seen_ns_ids=seen_ids,
            run_id=run_id,
            label_column="name",
        )
        stats["newly_deleted"] = deletion_stats["newly_deleted"]
        stats["total_deleted"] = deletion_stats["total_deleted"]

    logger.info("Custom record types done: %s", stats)
    return stats
