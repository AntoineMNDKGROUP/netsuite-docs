"""Extraction du change log NetSuite via SystemNote — avec fallback chain.

Plusieurs variantes selon ce qui est exposé sur le compte.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from ..suiteql import SuiteQLClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)


def _build_queries(since: datetime) -> list[str]:
    """Construit plusieurs variantes de requête SystemNote, du plus riche au plus minimal."""
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")
    where_date = f"WHERE sn.date >= TO_DATE('{since_str}', 'YYYY-MM-DD HH24:MI:SS')"
    return [
        # V1 : avec record (FK), field, type, name, role, context — version riche
        f"""
        SELECT
            sn.record       AS record_id,
            sn.field        AS field,
            sn.oldvalue     AS old_value,
            sn.newvalue     AS new_value,
            sn.type         AS change_type,
            sn.name         AS user_id,
            BUILTIN.DF(sn.name) AS user_name,
            sn.date         AS changed_at,
            sn.context      AS context,
            BUILTIN.DF(sn.role) AS role_name
        FROM SystemNote sn
        {where_date}
        """,
        # V2 : sans BUILTIN.DF (au cas où)
        f"""
        SELECT
            sn.record       AS record_id,
            sn.field        AS field,
            sn.oldvalue     AS old_value,
            sn.newvalue     AS new_value,
            sn.type         AS change_type,
            sn.name         AS user_id,
            sn.date         AS changed_at,
            sn.context      AS context
        FROM SystemNote sn
        {where_date}
        """,
        # V3 : ultra minimal
        f"""
        SELECT
            sn.record   AS record_id,
            sn.field    AS field,
            sn.name     AS user_id,
            sn.date     AS changed_at
        FROM SystemNote sn
        {where_date}
        """,
    ]


_TYPE_MAP = {"A": "ADD", "C": "CHANGE", "D": "DELETE"}


def _synthetic_id(row: dict[str, Any]) -> str:
    key = "|".join([
        str(row.get("record_id", "")),
        str(row.get("field", "")),
        str(row.get("changed_at", "")),
        str(row.get("user_id", "")),
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _to_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ns_internal_id": _synthetic_id(row),
        "record_type": "(see record_id)",  # on n'a plus la colonne recordtype directe
        "record_id": str(row.get("record_id") or ""),
        "field": row.get("field"),
        "old_value": (str(row.get("old_value")) if row.get("old_value") is not None else None),
        "new_value": (str(row.get("new_value")) if row.get("new_value") is not None else None),
        "context": row.get("context"),
        "changed_by": (
            f"{row.get('user_name')} (#{row.get('user_id')})"
            if row.get("user_name") and row.get("user_id")
            else (str(row.get("user_id")) if row.get("user_id") else None)
        ),
        "changed_at": row.get("changed_at"),
    }


def extract_system_notes(
    suiteql: SuiteQLClient,
    store: SupabaseStore,
    run_id: str,
    *,
    days_back: int = 30,
    limit: int | None = None,
) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=days_back)
    logger.info(
        "Fetching system_notes since %s (limit=%s)...",
        since.isoformat(), limit or "no limit",
    )

    queries = _build_queries(since)
    last_err = None
    rows: list[dict[str, Any]] = []
    for i, q in enumerate(queries, 1):
        try:
            rows = list(suiteql.query(q, limit=limit))
            logger.info("  → system_notes variante v%s OK (%s rows)", i, len(rows))
            break
        except requests.exceptions.HTTPError as e:
            logger.warning("  → system_notes variante v%s échec (%s)", i, str(e)[:120])
            last_err = e
            continue
    else:
        raise last_err if last_err else RuntimeError("Toutes les variantes systemnote ont échoué")

    records = [_to_record(r) for r in rows]

    deduped: dict[str, dict[str, Any]] = {}
    for r in records:
        deduped[r["ns_internal_id"]] = r
    records = list(deduped.values())

    if not records:
        logger.info("system_notes: aucune entrée sur la période")
        return {"seen": 0, "inserted": 0}

    inserted = 0
    CHUNK = 500
    for i in range(0, len(records), CHUNK):
        chunk = records[i : i + CHUNK]
        store.client.table("system_notes").upsert(
            chunk, on_conflict="ns_internal_id"
        ).execute()
        inserted += len(chunk)

    logger.info("System notes synced: %s rows", inserted)
    return {"seen": len(records), "inserted": inserted}
