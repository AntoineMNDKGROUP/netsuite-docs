"""Extraction des workflows NetSuite via SuiteQL.

NetSuite expose les workflows via la table SuiteQL `workflow`. On récupère les
métadonnées de base (name, record_type, release_status, owner, dates).

La définition complète d'un workflow (états, transitions, actions) n'est pas
exposée par SuiteQL — il faudrait un RESTlet custom (workflow.load) pour ça.
On se contente du listing pour l'instant : suffisant pour la détection
d'updates et le dashboard.

Stratégie défensive identique à scripts.py : query riche d'abord, fallback
minimal si NetSuite refuse certains champs.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from ..suiteql import SuiteQLClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)


# ============================================================================
# WORKFLOWS — fallback chain
# ============================================================================

WORKFLOWS_QUERY_VARIANTS = [
    # V1 : avec BUILTIN.DF pour le owner_name
    """
    SELECT
        w.id              AS ns_internal_id,
        w.scriptid        AS workflow_id,
        w.name            AS name,
        w.recordtype      AS record_type,
        w.releasestatus   AS release_status,
        w.isinactive      AS is_inactive,
        w.description     AS description,
        w.owner           AS owner,
        BUILTIN.DF(w.owner) AS owner_name,
        w.datecreated     AS date_created,
        w.lastmodified    AS last_modified
    FROM workflow w
    """,
    # V2 : sans BUILTIN.DF
    """
    SELECT
        w.id              AS ns_internal_id,
        w.scriptid        AS workflow_id,
        w.name            AS name,
        w.recordtype      AS record_type,
        w.releasestatus   AS release_status,
        w.isinactive      AS is_inactive,
        w.description     AS description,
        w.owner           AS owner,
        w.datecreated     AS date_created,
        w.lastmodified    AS last_modified
    FROM workflow w
    """,
    # V3 : très minimal (cas où certaines colonnes n'existent pas sur ce compte)
    """
    SELECT
        w.id              AS ns_internal_id,
        w.scriptid        AS workflow_id,
        w.name            AS name,
        w.recordtype      AS record_type,
        w.isinactive      AS is_inactive
    FROM workflow w
    """,
]


def _norm_bool(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in {"T", "TRUE", "1", "YES"}


def _to_workflow_record(row: dict[str, Any]) -> dict[str, Any]:
    owner_id = row.get("owner")
    owner_name = row.get("owner_name")
    return {
        "ns_internal_id": str(row["ns_internal_id"]),
        "workflow_id": row.get("workflow_id"),
        "name": row.get("name") or "(unnamed)",
        "record_type": row.get("record_type"),
        "release_status": row.get("release_status"),
        "is_inactive": _norm_bool(row.get("is_inactive")),
        "description": row.get("description"),
        "owner": (
            f"{owner_name} (#{owner_id})" if owner_id and owner_name
            else (str(owner_id) if owner_id else None)
        ),
        "date_created": row.get("date_created"),
        "last_modified": row.get("last_modified"),
        # `states` reste null pour l'instant — pour l'avoir, il faudra un
        # RESTlet workflow_reader (similaire à saved_search_reader).
        "states": None,
        "raw": row,
    }


def _try_variants(
    suiteql: SuiteQLClient,
    variants: list[str],
    limit: int | None,
) -> list[dict[str, Any]]:
    last_err: Exception | None = None
    for i, q in enumerate(variants, 1):
        sql = q.strip()
        if limit:
            sql = sql.rstrip(";") + f"\nFETCH FIRST {int(limit)} ROWS ONLY"
        try:
            rows = suiteql.run(sql)
            logger.info("workflows query variant %d → OK (%d rows)", i, len(rows))
            return rows
        except (requests.HTTPError, RuntimeError) as e:
            logger.warning("workflows query variant %d failed: %s", i, e)
            last_err = e
            continue
    raise RuntimeError(
        f"Toutes les variantes de query workflows ont échoué. Last error: {last_err}"
    )


def extract_workflows(
    suiteql: SuiteQLClient,
    store: SupabaseStore,
    run_id: str,
    limit: int | None = None,
) -> dict[str, int]:
    """Extrait la liste des workflows + métadonnées via SuiteQL.

    Bulk sync standard + détection des suppressions à la fin.
    """
    logger.info("Fetching workflows from NetSuite (limit=%s)...", limit or "no limit")
    rows = _try_variants(suiteql, WORKFLOWS_QUERY_VARIANTS, limit)
    records = [_to_workflow_record(r) for r in rows]
    logger.info("Fetched %s workflows, syncing to Supabase...", len(records))

    stats = store.bulk_sync(
        table="workflows",
        entity_type="workflow",
        records=records,
        run_id=run_id,
        label_keys=("name",),
    )

    # Détection des suppressions : workflows présents en base mais plus en NS
    if not limit:  # ne pas le faire en mode --limit (faux positifs)
        seen_ids = [r["ns_internal_id"] for r in records]
        deletion_stats = store.detect_deletions(
            table="workflows",
            entity_type="workflow",
            seen_ns_ids=seen_ids,
            run_id=run_id,
            label_column="name",
        )
        stats["newly_deleted"] = deletion_stats["newly_deleted"]
        stats["total_deleted"] = deletion_stats["total_deleted"]

    logger.info("Workflows done: %s", stats)
    return stats
