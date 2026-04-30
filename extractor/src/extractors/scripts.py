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
# Whitelist des colonnes "significatives" pour la détection de changement.
# Le hash de detection (snapshots.content_hash) ne porte QUE sur ces colonnes,
# pour ignorer les drifts du `raw` jsonb et autres champs cosmétiques.
# ============================================================================

SCRIPT_HASH_KEYS = (
    "ns_internal_id",
    "name",
    "script_type",
    "owner",
    "is_inactive",
)

SCRIPT_DEPLOYMENT_HASH_KEYS = (
    "ns_internal_id",
    "title",
    "status",
    "is_deployed",
    "log_level",
)


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


def _restlet_to_script_record(it: dict[str, Any]) -> dict[str, Any]:
    """Mappe un item RESTlet (action=list_scripts) vers le format de la table
    scripts. Format RESTlet : {internalid, scriptid, name, script_type,
    api_version, script_file, description, is_inactive, owner_id, owner,
    last_modified, date_created}.
    """
    owner_id = it.get("owner_id")
    owner_name = it.get("owner")
    return {
        "ns_internal_id": str(it["internalid"]),
        "script_id": it.get("scriptid"),
        "name": it.get("name") or "(unnamed)",
        "script_type": it.get("script_type"),
        "api_version": it.get("api_version"),
        "script_file": it.get("script_file") and str(it.get("script_file")),
        "description": it.get("description"),
        "is_inactive": bool(it.get("is_inactive", False)),
        "owner": (
            f"{owner_name} (#{owner_id})" if owner_id and owner_name
            else (str(owner_id) if owner_id else None)
        ),
        "raw": it,
    }


def _restlet_to_deployment_record(it: dict[str, Any]) -> dict[str, Any]:
    """Mappe un item RESTlet (action=list_script_deployments) vers le format
    de la table script_deployments.
    """
    return {
        "ns_internal_id": str(it["internalid"]),
        "script_ns_id": str(it.get("script_internalid")) if it.get("script_internalid") else None,
        "deployment_id": it.get("deployment_scriptid"),
        "title": it.get("title"),
        "status": it.get("status_text") or it.get("status"),
        "is_deployed": bool(it.get("is_deployed", False)),
        "log_level": it.get("log_level_text") or it.get("log_level"),
        "context": {"record_type": it.get("record_type")} if it.get("record_type") else None,
        "raw": it,
    }


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
    metadata_client=None,
) -> dict[str, int]:
    """Extrait les scripts.

    Si `modified_since` est fourni :
      1. Si `metadata_client` est fourni → utilise le RESTlet `list_scripts`
         (qui bypasse les limitations SuiteQL via N/search). Approche
         recommandée — c'est le seul moyen fiable de filtrer par
         lastmodifieddate sur ce record type.
      2. Sinon → fallback SuiteQL avec WHERE en cascade de noms de colonnes.

    La détection des suppressions est désactivée si modified_since (la liste
    retournée est partielle, donc une absence n'est pas une vraie suppression).
    """
    # ---- Mode incremental via RESTlet (recommandé) -----------------------
    if modified_since is not None and metadata_client is not None:
        from datetime import datetime, timezone
        ts = modified_since
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        since_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Fetching scripts modified since %s (via RESTlet)...", since_str)
        items = metadata_client.list_scripts_changed(since=since_str)
        records = [_restlet_to_script_record(it) for it in items]
        logger.info("Fetched %s scripts via RESTlet, syncing to Supabase...", len(records))
        stats = store.bulk_sync(
            table="scripts",
            entity_type="script",
            records=records,
            run_id=run_id,
            hash_keys=SCRIPT_HASH_KEYS,
        )
        logger.info("Scripts done: %s", stats)
        return stats

    # ---- Mode incremental via SuiteQL (fallback) -------------------------
    if modified_since is not None:
        ts_literal = _format_since_for_suiteql(modified_since)
        logger.info("Fetching scripts modified since %s (SuiteQL fallback)...", modified_since)
        date_candidates = ["datemodified", "lastmodified", "lastmodifieddate", "lastmoddate"]
        variants = []
        for date_col in date_candidates:
            for v in SCRIPTS_QUERY_VARIANTS:
                variants.append(
                    v.rstrip().rstrip(";") + f"\nWHERE s.{date_col} >= {ts_literal}\n"
                )
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
        hash_keys=SCRIPT_HASH_KEYS,
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
    metadata_client=None,
) -> dict[str, int]:
    # ---- Mode incremental via RESTlet (recommandé) -----------------------
    if modified_since is not None and metadata_client is not None:
        from datetime import datetime, timezone
        ts = modified_since
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        since_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        logger.info(
            "Fetching script deployments modified since %s (via RESTlet)...",
            since_str,
        )
        items = metadata_client.list_script_deployments_changed(since=since_str)
        records = [_restlet_to_deployment_record(it) for it in items]
        logger.info(
            "Fetched %s deployments via RESTlet, syncing to Supabase...",
            len(records),
        )
        stats = store.bulk_sync(
            table="script_deployments",
            entity_type="script_deployment",
            records=records,
            run_id=run_id,
            label_keys=("title", "deployment_id"),
            hash_keys=SCRIPT_DEPLOYMENT_HASH_KEYS,
        )
        logger.info("Script deployments done: %s", stats)
        return stats

    # ---- Mode incremental via SuiteQL (fallback) -------------------------
    if modified_since is not None:
        ts_literal = _format_since_for_suiteql(modified_since)
        logger.info(
            "Fetching script deployments modified since %s (SuiteQL fallback)...",
            modified_since,
        )
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
        hash_keys=SCRIPT_DEPLOYMENT_HASH_KEYS,
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
