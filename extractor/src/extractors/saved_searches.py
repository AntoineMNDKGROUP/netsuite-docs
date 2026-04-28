"""Extraction des saved searches via le RESTlet `saved_search_reader`.

Approche :
1. Liste toutes les saved searches accessibles à l'user `Documentation Reader`
   (RESTlet endpoint `?action=list`).
2. Filtre les "customs NDK" — par défaut, tout ce qui matche les préfixes
   NSA / NUS / LPS / LUS / MU dans le title OU dans le scriptid (cohérent avec
   le filtre utilisé pour les scripts).
3. Pour chaque SS qualifiée, fetch la définition complète (filters + columns
   + filter_expression) via `?action=get&id=...`.
4. Insert/update en base via `bulk_sync` (avec snapshot + change tracking).

Les SS qui n'ont pas changé (même `content_sha256`) sont skippées au niveau
fetch pour économiser les appels RESTlet, sauf si `force=True`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..saved_search_client import SavedSearchClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Filtre "custom NDK"
# ---------------------------------------------------------------------------

# Préfixes des saved searches custom NDK. On match :
#   - title : "NSA - …", "NUS - …", "LPS - …", "LUS - …", "MU - …", "NSA/LPS - …"
#   - scriptid : customsearch_nsa_xxx, customsearch_nus_xxx, …, ou
#     customsearch_ndk_xxx
NDK_TITLE_PREFIX_RE = re.compile(
    r"^(NSA|NUS|LPS|LUS|MU)(?:[\s\-/_]|$)",
    re.IGNORECASE,
)
NDK_SCRIPTID_PREFIX_RE = re.compile(
    r"^customsearch_(nsa|nus|lps|lus|mu|ndk|nall|nsalps|nuslus)\b",
    re.IGNORECASE,
)


def is_ndk_custom(item: dict[str, Any]) -> bool:
    """True si la saved search est une custom NDK (à documenter)."""
    title = (item.get("title") or "").strip()
    scriptid = (item.get("scriptid") or "").strip()
    if NDK_TITLE_PREFIX_RE.match(title):
        return True
    if NDK_SCRIPTID_PREFIX_RE.match(scriptid):
        return True
    return False


# ---------------------------------------------------------------------------
# Normalisation pour le content_sha256
# ---------------------------------------------------------------------------

def _content_sha256(definition: dict[str, Any]) -> str:
    """Hash stable de la définition pour détecter les changements.

    On exclut les champs purement métadonnées (last_modified, etc.) pour ne
    capturer que ce qui change *réellement* dans la définition.
    """
    keep = {
        "title",
        "recordtype",
        "is_public",
        "filter_expression",
        "filters",
        "columns",
    }
    cleaned = {k: definition.get(k) for k in keep}
    canonical = json.dumps(cleaned, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# Le RESTlet renvoie les dates au format NetSuite us-locale ("MM/DD/YYYY") ou,
# selon la locale du compte, "DD/MM/YYYY". On essaie les deux pour être robuste.
_DATE_FORMATS = ("%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d")


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    logger.debug("Date non parsable: %r", s)
    return None


# ---------------------------------------------------------------------------
# Extractor principal
# ---------------------------------------------------------------------------

def extract_saved_searches(
    client: SavedSearchClient,
    store: SupabaseStore,
    run_id: str,
    *,
    limit: int | None = None,
    only_ndk: bool = True,
    force: bool = False,
    list_only: bool = False,
    modified_since=None,
) -> dict[str, int]:
    """Extrait et synchronise les saved searches.

    Args:
        client: client RESTlet saved_search_reader
        store: client Supabase
        run_id: id de la sync_run en cours
        limit: si défini, ne traite que les N premières SS qualifiées (utile en test)
        only_ndk: si True, ne garde que les customs NDK (défaut : True)
        force: si True, refetch les définitions même si le content_sha256 est inchangé
        list_only: si True, ne fait QUE le listing (pas de fetch ni d'insert).
            Utile pour valider le périmètre avant de lancer un run complet.
            Logge un échantillon de 30 candidats + un breakdown par préfixe.

    Returns:
        stats dict {seen, qualified, fetched, skipped_unchanged, errors,
                    created, updated, unchanged}
    """
    stats = {
        "seen": 0,
        "qualified": 0,
        "fetched": 0,
        "skipped_unchanged": 0,
        "errors": 0,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
    }

    # 1. Lister toutes les SS accessibles
    #    En mode incremental, le RESTlet filtre côté NetSuite via formula
    #    datemodified >= since → on ne reçoit que les SS modifiées depuis le
    #    dernier run. Énorme gain de perf (passe de 9 800 SS listées à
    #    typiquement <50/jour).
    since_str: str | None = None
    if modified_since is not None:
        ts = modified_since
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        since_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        logger.info("Listing saved searches modifiées depuis %s (mode incremental)...", since_str)
    else:
        logger.info("Listing toutes les saved searches via RESTlet...")

    all_items = client.list_all(since=since_str)
    stats["seen"] = len(all_items)
    logger.info("  %d saved searches accessibles", stats["seen"])

    # 2. Filtre custom NDK
    if only_ndk:
        candidates = [it for it in all_items if is_ndk_custom(it)]
    else:
        candidates = list(all_items)
    stats["qualified"] = len(candidates)
    logger.info("  %d qualifiées (only_ndk=%s)", stats["qualified"], only_ndk)

    if list_only:
        logger.info("=" * 60)
        logger.info("LIST-ONLY mode (pas de fetch). Aperçu des candidats :")
        logger.info("=" * 60)
        # Breakdown par préfixe pour repérer les gros blocs (NSA, NUS, LPS...)
        prefix_counts: dict[str, int] = {}
        for c in candidates:
            title = (c.get("title") or "").strip()
            prefix = title.split(" ", 1)[0].split("-", 1)[0].split("/", 1)[0].upper()
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        sorted_prefixes = sorted(prefix_counts.items(), key=lambda x: -x[1])
        for p, n in sorted_prefixes[:25]:
            logger.info("  %-15s : %d", p, n)
        logger.info("---")
        # Premier échantillon de 30 SS
        for i, c in enumerate(candidates[:30], 1):
            logger.info(
                "  [%3d] %s | %r | type=%s owner=%r inactive=%s",
                i,
                c.get("scriptid") or "(no scriptid)",
                c.get("title"),
                c.get("recordtype"),
                c.get("owner"),
                c.get("is_inactive"),
            )
        if len(candidates) > 30:
            logger.info("  ... et %d autres", len(candidates) - 30)
        return stats

    if limit:
        candidates = candidates[:limit]
        logger.info("  --limit appliqué : %d à traiter", len(candidates))

    if not candidates:
        return stats

    # 3. Récupérer les SHA existants pour skip les inchangés
    existing_shas: dict[str, str] = {}
    if not force:
        ns_ids = [str(c.get("internalid")) for c in candidates if c.get("internalid")]
        # Fetch par chunks pour ne pas exploser la taille d'URL
        chunk_size = 200
        for i in range(0, len(ns_ids), chunk_size):
            chunk = ns_ids[i : i + chunk_size]
            res = (
                store.client.table("saved_searches")
                .select("ns_internal_id,content_sha256")
                .in_("ns_internal_id", chunk)
                .execute()
            )
            for row in res.data or []:
                existing_shas[row["ns_internal_id"]] = row.get("content_sha256") or ""

    # 4. Fetch définitions + build records (avec flush intermédiaire tous les
    #    FLUSH_BATCH_SIZE pour ne pas perdre tout en cas de crash sur un long run)
    FLUSH_BATCH_SIZE = 100
    records: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    def _flush(records_to_flush: list[dict[str, Any]]) -> None:
        """Flush intermédiaire : envoie le batch courant en base et accumule les stats."""
        if not records_to_flush:
            return
        sync_stats = store.bulk_sync(
            table="saved_searches",
            entity_type="saved_search",
            records=records_to_flush,
            run_id=run_id,
            label_keys=("title",),
        )
        for k in ("created", "updated", "unchanged"):
            stats[k] += sync_stats.get(k, 0)

    started_fetch = datetime.now(timezone.utc)

    for idx, item in enumerate(candidates, 1):
        internal_id = str(item.get("internalid") or "").strip()
        if not internal_id:
            logger.warning("SS sans internalid, skip: %r", item)
            stats["errors"] += 1
            continue

        scriptid = item.get("scriptid") or ""
        title = item.get("title") or ""

        try:
            definition = client.get_definition(internal_id)
        except Exception as e:
            logger.warning(
                "[%d/%d] Échec fetch %s (%s): %s",
                idx, len(candidates), internal_id, title, e,
            )
            stats["errors"] += 1
            continue

        sha = _content_sha256(definition)

        # Skip si inchangé (sauf force) — précieux en mode resume après crash
        if not force and existing_shas.get(internal_id) == sha:
            stats["skipped_unchanged"] += 1
            # On log la progression même sur les skipped pour avoir un ETA fiable
            if idx % 100 == 0:
                _log_progress(idx, len(candidates), stats, started_fetch)
            continue

        stats["fetched"] += 1

        record = {
            "ns_internal_id": internal_id,
            "search_id": scriptid or definition.get("scriptid") or None,
            "title": title or definition.get("title") or "(unnamed)",
            "search_type": item.get("recordtype") or definition.get("recordtype"),
            "is_public": bool(definition.get("is_public", item.get("is_public", False))),
            "is_inactive": bool(item.get("is_inactive", False)),
            "owner": item.get("owner"),
            "description": item.get("description"),
            "filters": definition.get("filters") or [],
            "columns": definition.get("columns") or [],
            "filter_expression": (
                json.dumps(definition.get("filter_expression"))
                if definition.get("filter_expression") is not None
                else None
            ),
            "date_created": _parse_date(item.get("date_created")).isoformat()
                if _parse_date(item.get("date_created")) else None,
            "last_modified": _parse_date(item.get("date_modified")).isoformat()
                if _parse_date(item.get("date_modified")) else None,
            "raw": {
                "list_item": item,
                "definition": definition,
            },
            "content_sha256": sha,
            "last_extracted_at": now_iso,
        }
        records.append(record)

        # Flush intermédiaire dès qu'on atteint la taille de batch
        if len(records) >= FLUSH_BATCH_SIZE:
            logger.info(
                "  💾 flush %d SS en base (cumul: created=%d updated=%d unchanged=%d)",
                len(records), stats["created"], stats["updated"], stats["unchanged"],
            )
            _flush(records)
            records = []

        if idx % 25 == 0:
            _log_progress(idx, len(candidates), stats, started_fetch)

    # Flush final pour les <FLUSH_BATCH_SIZE restants
    if records:
        logger.info("  💾 flush final de %d SS en base", len(records))
        _flush(records)

    # Détection des suppressions : on compare la liste totale (TOUS les ns_id
    # vus, pas seulement les fetched/updated) à ce qui est en base. Marque
    # comme is_deleted=true les disparues. Ne le fait que si on n'avait pas de
    # filtre actif (sinon faux positifs).
    if not limit and not list_only and only_ndk is False:
        # only_ndk=False = on listait tout le compte
        seen_all_ns_ids = [str(it.get("internalid")) for it in all_items if it.get("internalid")]
        deletion_stats = store.detect_deletions(
            table="saved_searches",
            entity_type="saved_search",
            seen_ns_ids=seen_all_ns_ids,
            run_id=run_id,
            label_column="title",
        )
        stats["newly_deleted"] = deletion_stats["newly_deleted"]
        stats["total_deleted"] = deletion_stats["total_deleted"]

    logger.info("✅ saved_searches: %s", stats)
    return stats


def _log_progress(idx: int, total: int, stats: dict[str, int], started: datetime) -> None:
    """Log de progression avec ETA basé sur le rythme courant."""
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    rate = idx / elapsed if elapsed > 0 else 0
    remaining = total - idx
    eta_sec = (remaining / rate) if rate > 0 else 0
    eta_h = eta_sec / 3600
    logger.info(
        "  [%d/%d] rate=%.1f SS/s elapsed=%.0fs ETA=%.1fh "
        "(fetched=%d skipped=%d errors=%d created=%d updated=%d unchanged=%d)",
        idx, total, rate, elapsed, eta_h,
        stats["fetched"], stats["skipped_unchanged"], stats["errors"],
        stats["created"], stats["updated"], stats["unchanged"],
    )
