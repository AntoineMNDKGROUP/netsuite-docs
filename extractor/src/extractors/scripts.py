"""Extraction des scripts et déploiements NetSuite via SuiteQL.

Stratégie défensive : on essaie d'abord une requête riche, et si NetSuite refuse
un champ on retombe sur une version minimale connue pour fonctionner.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from ..suiteql import SuiteQLClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)


# ============================================================================
# SCRIPTS — fallback chain
# ============================================================================

# Du plus riche au plus minimal. La première qui ne lève pas est utilisée.
SCRIPTS_QUERY_VARIANTS = [
    # V1 : avec BUILTIN.DF pour le owner_name (si BUILTIN.DF est exposé)
    """
    SELECT
        s.id              AS ns_internal_id,
        s.scriptid        AS script_id,
        s.name            AS name,
        s.scripttype      AS script_type,
        s.apiversion      AS api_version,
        s.scriptfile      AS script_file,
        s.description     AS description,
        s.isinactive      AS is_inactive,
        s.owner           AS owner,
        BUILTIN.DF(s.owner) AS owner_name
    FROM script s
    """,
    # V2 : minimal (cas where BUILTIN.DF n'est pas exposé)
    """
    SELECT
        s.id              AS ns_internal_id,
        s.scriptid        AS script_id,
        s.name            AS name,
        s.scripttype      AS script_type,
        s.apiversion      AS api_version,
        s.scriptfile      AS script_file,
        s.description     AS description,
        s.isinactive      AS is_inactive,
        s.owner           AS owner
    FROM script s
    """,
]


def _norm_bool(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    return str(v).strip().upper() in {"T", "TRUE", "1", "YES"}


def _to_script_record(row: dict[str, Any]) -> dict[str, Any]:
    owner_id = row.get("owner")
    owner_name = row.get("owner_name")
    return {
        "ns_internal_id": str(row["ns_internal_id"]),
        "script_id": row.get("script_id"),
        "name": row.get("name") or "(unnamed)",
        "script_type": row.get("script_type"),
        "api_version": row.get("api_version"),
        "script_file": row.get("script_file") and str(row.get("script_file")),
        "description": row.get("description"),
        "is_inactive": _norm_bool(row.get("is_inactive")),
        "owner": (
            f"{owner_name} (#{owner_id})" if owner_id and owner_name
            else (str(owner_id) if owner_id else None)
        ),
        "raw": row,
    }


def _try_variants(suiteql: SuiteQLClient, queries: list[str], limit: int | None) -> list[dict[str, Any]]:
    """Tente chaque variante de requête en ordre, retourne la première qui marche."""
    last_err: Exception | None = None
    for i, q in enumerate(queries, 1):
        try:
            rows = list(suiteql.query(q, limit=limit))
            if i > 1:
                logger.info("  → variante v%s utilisée", i)
            return rows
        except requests.exceptions.HTTPError as e:
            logger.warning("  → variante v%s a échoué (%s), tentative suivante", i, str(e)[:80])
            last_err = e
            continue
    raise last_err if last_err else RuntimeError("All query variants failed")


def _format_since_for_suiteql(since) -> str:
    """Convertit un datetime en literal SuiteQL TO_TIMESTAMP('...', 'YYYY-MM-DD HH24:MI:SS')."""
    from datetime import datetime, timezone
    if isinstance(since, str):
        since = datetime.fromisoformat(since.replace("Z", "+00:00"))
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    s = since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return f"TO_TIMESTAMP('{s}', 'YYYY-MM-DD HH24:MI:SS')"


def extract_scripts(
    suiteql: SuiteQLClient,
    store: SupabaseStore,
    run_id: str,
    limit: int | None = None,
    *,
    modified_since=None,
) -> dict[str, int]:
    """Extrait les scripts.

    Si `modified_since` est fourni (datetime), ne récupère que les scripts dont
    `script.lastmodifieddate >= modified_since` côté SuiteQL. Permet de gagner
    en perf en mode incremental. La détection des suppressions est désactivée
    dans ce cas (la liste retournée est partielle, donc une absence n'est pas
    une vraie suppression).
    """
    if modified_since is not None:
        ts_literal = _format_since_for_suiteql(modified_since)
        logger.info("Fetching scripts modified since %s...", modified_since)
        # Le nom du champ "date de dernière modif" varie selon les comptes
        # NetSuite. On essaie plusieurs candidats en cascade ; si tous échouent,
        # on retombe sur la query SANS filtre (full scan, bulk_sync skipera
        # quand même via le hash).
        date_candidates = ["datemodified", "lastmodified", "lastmodifieddate", "lastmoddate"]
        variants = []
        for date_col in date_candidates:
            for v in SCRIPTS_QUERY_VARIANTS:
                variants.append(
                    v.rstrip().rstrip(";") + f"\nWHERE s.{date_col} >= {ts_literal}\n"
                )
        # Fallback: les variantes sans filtre (au cas où aucun nom ne marche)
        variants.extend(SCRIPTS_QUERY_VARIANTS)
    else:
        logger.info("Fetching scripts from NetSuite (limit=%s)...", limit or "no limit")
        variants = SCRIPTS_QUERY_VARIANTS

    rows = _try_variants(suiteql, variants, limit)
    records = [_to_script_record(r) for r in rows]
    logger.info("Fetched %s scripts, syncing to Supabase...", len(records))
    stats = store.bulk_sync(
        table="scripts",
        entity_type="script",
        records=records,
        run_id=run_id,
    )

    # Détection des suppressions : uniquement si la liste est exhaustive
    # (pas en --limit, pas en mode incremental avec filtre lastmodified).
    if not limit and modified_since is None:
        seen_ids = [r["ns_internal_id"] for r in records]
        deletion_stats = store.detect_deletions(
            table="scripts",
            entity_type="script",
            seen_ns_ids=seen_ids,
            run_id=run_id,
            label_column="name",
        )
        stats["newly_deleted"] = deletion_stats["newly_deleted"]
        stats["total_deleted"] = deletion_stats["total_deleted"]

    logger.info("Scripts done: %s", stats)
    return stats


# ============================================================================
# SCRIPT DEPLOYMENTS — fallback chain
# ============================================================================

DEPLOYMENTS_QUERY_VARIANTS = [
    # V1 : minimal (les colonnes exposées de manière fiable sur ce compte)
    """
    SELECT
        d.id           AS ns_internal_id,
        d.script       AS script_ns_id,
        d.scriptid     AS deployment_id,
        d.title        AS title,
        d.status       AS status,
        d.isdeployed   AS is_deployed,
        d.loglevel     AS log_level,
        d.recordtype   AS record_type
    FROM scriptdeployment d
    """,
]


def _to_deployment_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ns_internal_id": str(row["ns_internal_id"]),
        "script_ns_id": str(row["script_ns_id"]),
        "deployment_id": row.get("deployment_id"),
        "title": row.get("title"),
        "status": row.get("status"),
        "is_deployed": _norm_bool(row.get("is_deployed")),
        "log_level": row.get("log_level"),
        "context": {"record_type": row.get("record_type")} if row.get("record_type") else None,
        "raw": row,
    }


def extract_script_deployments(
    suiteql: SuiteQLClient,
    store: SupabaseStore,
    run_id: str,
    limit: int | None = None,
    *,
    modified_since=None,
) -> dict[str, int]:
    if modified_since is not None:
        ts_literal = _format_since_for_suiteql(modified_since)
        logger.info("Fetching script deployments modified since %s...", modified_since)
        # Idem scripts : on essaie plusieurs noms, fallback sans filtre.
        date_candidates = ["datemodified", "lastmodified", "lastmodifieddate", "lastmoddate"]
        variants = []
        for date_col in date_candidates:
            for v in DEPLOYMENTS_QUERY_VARIANTS:
                variants.append(
                    v.rstrip().rstrip(";") + f"\nWHERE d.{date_col} >= {ts_literal}\n"
                )
        variants.extend(DEPLOYMENTS_QUERY_VARIANTS)
    else:
        logger.info("Fetching script deployments (limit=%s)...", limit or "no limit")
        variants = DEPLOYMENTS_QUERY_VARIANTS

    rows = _try_variants(suiteql, variants, limit)
    raw_records = [_to_deployment_record(r) for r in rows]
    logger.info("Fetched %s raw deployment rows, deduplicating...", len(raw_records))

    # Dédup en agrégeant les record_types
    deduped: dict[str, dict[str, Any]] = {}
    for r in raw_records:
        ns_id = r["ns_internal_id"]
        rt = (r.get("context") or {}).get("record_type")
        if ns_id in deduped:
            ctx = deduped[ns_id].get("context") or {}
            existing_rts = ctx.get("record_types", [])
            if rt and rt not in existing_rts:
                existing_rts.append(rt)
            ctx["record_types"] = existing_rts
            deduped[ns_id]["context"] = ctx
        else:
            r = dict(r)
            ctx = {"record_types": [rt] if rt else []}
            r["context"] = ctx
            deduped[ns_id] = r

    records = list(deduped.values())
    logger.info("After dedup: %s unique deployments, syncing to Supabase...", len(records))
    stats = store.bulk_sync(
        table="script_deployments",
        entity_type="script_deployment",
        records=records,
        run_id=run_id,
        label_keys=("title", "deployment_id"),
    )

    if not limit and modified_since is None:
        seen_ids = [r["ns_internal_id"] for r in records]
        deletion_stats = store.detect_deletions(
            table="script_deployments",
            entity_type="script_deployment",
            seen_ns_ids=seen_ids,
            run_id=run_id,
            label_column="title",
        )
        stats["newly_deleted"] = deletion_stats["newly_deleted"]
        stats["total_deleted"] = deletion_stats["total_deleted"]

    logger.info("Script deployments done: %s", stats)
    return stats
