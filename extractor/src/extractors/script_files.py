"""Extraction du contenu des fichiers JS des scripts.

Pour chaque script qui a un scriptfile (FK vers le File Cabinet) :
1. Télécharge la metadata + le contenu via REST
2. Compute SHA256
3. Parse les JSDoc tags (@NApiVersion, @NScriptType, etc.)
4. Upsert dans script_source_files
5. Si le hash a changé depuis le précédent snapshot → log un change
"""
from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from ..file_cabinet import FileCabinetClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)

PARALLEL_WORKERS = 8
CHUNK_SIZE = 200  # taille des batches d'upsert

# Regex pour parser les JSDoc tags. NetSuite utilise notamment :
# @NApiVersion, @NScriptType, @NModuleScope, @description, @author, @since, @deprecated, @summary
_JSDOC_TAG_RE = re.compile(r"@(N\w+|\w+)\s+([^\n*@]+)", re.MULTILINE)
_JSDOC_BLOCK_RE = re.compile(r"/\*\*([\s\S]*?)\*/")


def parse_jsdoc(content: str) -> dict[str, Any]:
    """Extrait les @tags du premier bloc JSDoc trouvé dans le fichier."""
    if not content:
        return {}
    block = _JSDOC_BLOCK_RE.search(content)
    if not block:
        return {}
    raw = block.group(1)
    tags: dict[str, Any] = {}
    for m in _JSDOC_TAG_RE.finditer(raw):
        key = m.group(1)
        val = m.group(2).strip().rstrip("*").strip()
        if key in tags:
            existing = tags[key]
            if isinstance(existing, list):
                existing.append(val)
            else:
                tags[key] = [existing, val]
        else:
            tags[key] = val
    return tags


def _classify_error(err_msg: str) -> str:
    """Classifie un message d'erreur pour décider de la stratégie de retry."""
    msg = err_msg.lower()
    if "do not have access" in msg or "permission" in msg or "not allowed" in msg:
        return "access_denied"
    if "not found" in msg or "invalid" in msg:
        return "not_found"
    return "error"


def _fetch_one(client: FileCabinetClient, script_ns_id: str, file_id: str) -> dict[str, Any] | None:
    """Télécharge et prépare une ligne `script_source_files` pour un script.

    Retourne toujours un dict (même en cas d'erreur), avec download_status
    classifié pour qu'on sache si on doit retenter ou non plus tard.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        content_bytes, meta = client.download_content(file_id)
    except Exception as e:
        err = str(e)[:200]
        status = _classify_error(err)
        logger.warning("  → script %s file %s [%s]: %s", script_ns_id, file_id, status, err[:100])
        return {
            "ns_internal_id": str(file_id),
            "script_ns_id": str(script_ns_id),
            "download_status": status,
            "last_error_at": now_iso,
            "raw": {"error": err},
            # tous les autres champs restent null
        }

    # Décodage texte
    try:
        content = content_bytes.decode("utf-8", errors="replace")
    except Exception:
        content = content_bytes.decode("latin-1", errors="replace")

    sha = hashlib.sha256(content_bytes).hexdigest()
    jsdoc = parse_jsdoc(content)

    return {
        "ns_internal_id": str(file_id),
        "script_ns_id": str(script_ns_id),
        "file_name": meta.get("name"),
        "file_path": _build_path(meta),
        "file_type": meta.get("fileType") or meta.get("filetype"),
        "mime_type": meta.get("mediaType") or meta.get("mimetype"),
        "encoding": meta.get("encoding"),
        "file_size": meta.get("filesize") or len(content_bytes),
        "ns_last_modified": meta.get("lastModifiedDate") or meta.get("lastmodifieddate"),
        "download_url": meta.get("url"),
        "content": content,
        "content_sha256": sha,
        "jsdoc": jsdoc,
        "raw": meta,
        "download_status": "success",
    }


def _build_path(meta: dict[str, Any]) -> str | None:
    """Reconstruit le chemin complet du fichier (Folder/Subfolder/file.js)."""
    folder = meta.get("folder")
    name = meta.get("name") or ""
    if isinstance(folder, dict):
        path = folder.get("name") or folder.get("refName")
        if path:
            return f"{path}/{name}"
    return name


def extract_script_files(
    file_client: FileCabinetClient,
    store: SupabaseStore,
    run_id: str,
    *,
    limit: int | None = None,
    only_changed: bool = False,
    modified_since=None,
    suiteql=None,
) -> dict[str, int]:
    """Télécharge le contenu des scripts ayant un scriptfile.

    Args:
        modified_since: si fourni (datetime), ne traite QUE les fichiers dont
            le `file.lastmodifieddate` côté NetSuite est >= modified_since.
            Indépendant de `script.last_modified` : on peut updater le source
            sans toucher au record script. Nécessite `suiteql` pour faire la
            query NetSuite.
        suiteql: client SuiteQL (requis si modified_since est fourni).
        only_changed: legacy, équivalent à modified_since='last_seen_at'.
    """
    # 1. Récupère la liste de TOUS les scripts avec script_file (paginé pour passer la limite de 1000)
    raw_candidates: list[dict[str, Any]] = []
    PAGE = 1000
    page_idx = 0
    while True:
        res = (
            store.client.table("scripts")
            .select("ns_internal_id,script_id,name,script_file")
            .not_.is_("script_file", "null")
            .order("ns_internal_id")
            .range(page_idx * PAGE, (page_idx + 1) * PAGE - 1)
            .execute()
        )
        chunk = res.data or []
        raw_candidates.extend(chunk)
        if len(chunk) < PAGE:
            break
        page_idx += 1
    logger.info("Scripts avec script_file: %s en base (paginé)", len(raw_candidates))

    # 1bis. Si modified_since fourni : query SuiteQL pour récupérer les file IDs
    #       modifiés côté NetSuite depuis cette date, puis intersection avec
    #       les script_files connus. C'est le filtre clé pour ne fetcher que
    #       les vraies modifs de code.
    if modified_since is not None:
        if suiteql is None:
            logger.warning(
                "modified_since fourni mais suiteql=None, on ignore le filtre"
            )
        else:
            from datetime import datetime, timezone
            ts = modified_since
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_str = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            ts_literal = f"TO_TIMESTAMP('{ts_str}', 'YYYY-MM-DD HH24:MI:SS')"

            logger.info(
                "Filtre incrémental : files dont lastmodifieddate >= %s",
                ts_str,
            )
            # On essaie 2 variantes (selon ce que ce compte expose)
            file_query_variants = [
                f"SELECT id, lastmodifieddate FROM file WHERE lastmodifieddate >= {ts_literal}",
                f"SELECT id, lastmodified AS lastmodifieddate FROM file WHERE lastmodified >= {ts_literal}",
            ]
            modified_file_ids: set[str] | None = None
            for q in file_query_variants:
                try:
                    rows = suiteql.query_all(q)
                    modified_file_ids = {str(r["id"]) for r in rows if r.get("id") is not None}
                    logger.info(
                        "  → %d fichiers modifiés côté NS depuis %s",
                        len(modified_file_ids), ts_str,
                    )
                    break
                except Exception as e:
                    logger.warning("File modifications query variant failed: %s", e)
                    continue

            if modified_file_ids is None:
                logger.warning(
                    "Impossible de récupérer la liste des files modifiés via SuiteQL — "
                    "on télécharge tous les candidats (fallback)."
                )
            else:
                # Intersection : on ne garde que les candidats dont script_file
                # est dans la liste des files modifiés
                before_count = len(raw_candidates)
                raw_candidates = [
                    c for c in raw_candidates
                    if str(c["script_file"]) in modified_file_ids
                ]
                logger.info(
                    "Filtre incrémental : %d → %d candidats (gardés ceux dont le file a été modifié)",
                    before_count, len(raw_candidates),
                )

    # 2. Charger les SHA + le download_status connus
    existing_sha: dict[str, str] = {}
    blocked_files: set[str] = set()
    if raw_candidates:
        ns_ids = [c["script_file"] for c in raw_candidates]
        for i in range(0, len(ns_ids), 200):
            chunk = ns_ids[i : i + 200]
            r = (
                store.client.table("script_source_files")
                .select("ns_internal_id,content_sha256,download_status")
                .in_("ns_internal_id", chunk)
                .execute()
            )
            for row in r.data or []:
                if row.get("content_sha256"):
                    existing_sha[row["ns_internal_id"]] = row["content_sha256"]
                # On skip définitivement les fichiers qu'on a déjà identifiés comme inaccessibles
                if row.get("download_status") in ("access_denied", "not_found"):
                    blocked_files.add(row["ns_internal_id"])

    # Filtre : on retire les fichiers qu'on sait inaccessibles (gain de temps + de quota)
    candidates = [c for c in raw_candidates if c["script_file"] not in blocked_files]
    skipped_blocked = len(raw_candidates) - len(candidates)
    if skipped_blocked > 0:
        logger.info("Skip %s fichiers déjà connus comme inaccessibles", skipped_blocked)

    if limit is not None:
        candidates = candidates[:limit]
    logger.info("Candidats à traiter : %s", len(candidates))

    # 3. Téléchargement parallélisé
    stats = {
        "seen": len(candidates), "downloaded": 0, "unchanged": 0, "failed": 0,
        "created": 0, "updated": 0, "access_denied": 0, "not_found": 0,
    }
    new_records: list[dict[str, Any]] = []
    new_changes: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        futures = {
            ex.submit(_fetch_one, file_client, c["ns_internal_id"], c["script_file"]): c
            for c in candidates
        }
        completed = 0
        for fut in as_completed(futures):
            c = futures[fut]
            completed += 1
            try:
                rec = fut.result()
            except Exception as e:
                stats["failed"] += 1
                logger.warning("  fetch crash: %s", e)
                continue

            if rec is None:
                stats["failed"] += 1
                continue

            file_id = rec["ns_internal_id"]
            status = rec.get("download_status", "success")

            if status == "access_denied":
                stats["access_denied"] += 1
                rec["last_seen_at"] = now_iso
                new_records.append(rec)
                continue
            if status == "not_found":
                stats["not_found"] += 1
                rec["last_seen_at"] = now_iso
                new_records.append(rec)
                continue
            if status != "success":
                stats["failed"] += 1
                rec["last_seen_at"] = now_iso
                new_records.append(rec)
                continue

            stats["downloaded"] += 1
            prev_sha = existing_sha.get(file_id)
            if prev_sha == rec["content_sha256"]:
                stats["unchanged"] += 1
                # Pas de rec_light : on ne touche pas aux records existants.
                # Le dédup gardait rec_light en dernier et wipait les autres colonnes.
                continue

            kind = "updated" if prev_sha else "created"
            stats[kind] += 1
            rec["last_seen_at"] = now_iso
            new_records.append(rec)
            new_changes.append({
                "entity_type": "script_source_file",
                "ns_internal_id": file_id,
                "entity_label": rec.get("file_name"),
                "kind": kind,
                "diff": {
                    "previous_sha256": prev_sha,
                    "new_sha256": rec["content_sha256"],
                    "size_bytes": rec.get("file_size"),
                },
                "changed_at": now_iso,
                "sync_run_id": run_id,
            })

            if completed % 100 == 0:
                logger.info(
                    "  %s/%s — created=%s updated=%s unchanged=%s denied=%s failed=%s",
                    completed, len(candidates),
                    stats["created"], stats["updated"], stats["unchanged"],
                    stats["access_denied"], stats["failed"],
                )

    # 4. Dédup : un fichier peut être référencé par plusieurs scripts
    # (libs partagées). On garde 1 ligne par ns_internal_id (la dernière vue).
    deduped_records: dict[str, dict[str, Any]] = {}
    for r in new_records:
        deduped_records[r["ns_internal_id"]] = r
    deduped_records_list = list(deduped_records.values())
    deduped_changes: dict[str, dict[str, Any]] = {}
    for c in new_changes:
        deduped_changes[c["ns_internal_id"]] = c
    deduped_changes_list = list(deduped_changes.values())

    if len(deduped_records_list) < len(new_records):
        logger.info(
            "Dédup script_source_files: %s lignes brutes -> %s uniques",
            len(new_records), len(deduped_records_list),
        )

    # 5. Bulk upsert
    if deduped_records_list:
        for i in range(0, len(deduped_records_list), CHUNK_SIZE):
            chunk = deduped_records_list[i : i + CHUNK_SIZE]
            store.client.table("script_source_files").upsert(
                chunk, on_conflict="ns_internal_id"
            ).execute()
    if deduped_changes_list:
        for i in range(0, len(deduped_changes_list), CHUNK_SIZE):
            chunk = deduped_changes_list[i : i + CHUNK_SIZE]
            store.client.table("changes").insert(chunk).execute()

    # 6. Snapshots : on conserve une copie complète du content à chaque changement
    #    (created OU updated) pour pouvoir générer plus tard la doc IA d'update via
    #    diff. La clé d'unicité est (entity_type, ns_internal_id, content_hash) qui
    #    évite les doublons si le même SHA est resnapshotté.
    snapshots_to_insert: list[dict[str, Any]] = []
    changed_ids = {c["ns_internal_id"] for c in deduped_changes_list}
    for r in deduped_records_list:
        file_id = r["ns_internal_id"]
        if file_id not in changed_ids:
            continue  # rien à snapshoter si pas de change détecté
        if not r.get("content_sha256") or not r.get("content"):
            continue  # pas de content (binaire / access_denied / not_found)
        snapshots_to_insert.append({
            "entity_type": "script_source_file",
            "ns_internal_id": file_id,
            "payload": {
                "file_name": r.get("file_name"),
                "file_path": r.get("file_path"),
                "file_size": r.get("file_size"),
                "content": r.get("content"),
                "jsdoc": r.get("jsdoc"),
                "ns_last_modified": r.get("ns_last_modified"),
            },
            "content_hash": r["content_sha256"],
            "sync_run_id": run_id,
        })

    if snapshots_to_insert:
        logger.info(
            "Inserting %d snapshots (script_source_file) for diff history",
            len(snapshots_to_insert),
        )
        for i in range(0, len(snapshots_to_insert), CHUNK_SIZE):
            chunk = snapshots_to_insert[i : i + CHUNK_SIZE]
            try:
                store.client.table("snapshots").insert(chunk).execute()
            except Exception as e:
                # uq_snapshots_dedup peut bloquer si on resnapshot le même SHA —
                # c'est attendu, on swallow et on continue
                logger.warning(
                    "Snapshot insert chunk failed (probable dedup OK): %s", e
                )

    logger.info("Script files done: %s", stats)
    return stats
