"""Client Supabase avec opérations batch (évite les limites HTTP/2 streams)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from supabase import create_client, Client

from .config import Settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 500


def _stable_hash(
    payload: dict[str, Any],
    include_keys: Iterable[str] | None = None,
) -> str:
    """Hash stable d'un dict pour la détection de changements.

    - Si `include_keys` est fourni, le hash ne porte QUE sur ces colonnes
      (whitelist). Utilisé pour les entités où on ne veut tracker que les
      changements métier significatifs (ex: scripts → name, owner, etc.)
      et ignorer le bruit du `raw` jsonb.
    - Sinon, hash sur tout le payload sauf les colonnes purement temporelles.
    """
    if include_keys is not None:
        allow = set(include_keys)
        cleaned = {k: v for k, v in payload.items() if k in allow}
    else:
        skipped = {"last_seen_at", "first_seen_at"}
        cleaned = {k: v for k, v in payload.items() if k not in skipped}
    canonical = json.dumps(cleaned, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _compute_diff(prev: dict[str, Any] | None, curr: dict[str, Any]) -> dict[str, Any]:
    if prev is None:
        return {"created": True, "fields": list(curr.keys())}

    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, dict[str, Any]] = {}

    keys = set(prev.keys()) | set(curr.keys())
    ignore = {"last_seen_at", "first_seen_at"}

    for k in keys - ignore:
        if k not in prev:
            added[k] = curr[k]
        elif k not in curr:
            removed[k] = prev[k]
        elif prev[k] != curr[k]:
            changed[k] = {"from": prev[k], "to": curr[k]}

    return {"added": added, "removed": removed, "changed": changed}


def _chunked(seq: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


class SupabaseStore:
    def __init__(self, settings: Settings):
        self.client: Client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

    # ---- Sync runs ----------------------------------------------------------
    def get_last_successful_run_at(self, *, exclude_modes: tuple[str, ...] = ("ping",)) -> datetime | None:
        """Renvoie le `started_at` du dernier run réussi.

        Utilisé en mode incremental pour ne re-fetcher que les entités
        modifiées depuis cette date côté NetSuite.

        Exclut par défaut le mode 'ping' (qui est juste un test de connexion).

        Returns:
            datetime UTC du dernier run réussi, ou None si aucun.
        """
        query = (
            self.client.table("sync_runs")
            .select("started_at")
            .eq("status", "success")
            .order("started_at", desc=True)
            .limit(50)  # on en prend plusieurs pour pouvoir filtrer ensuite
        )
        res = query.execute()
        rows = res.data or []
        for row in rows:
            # on parse pas seulement on filtre les modes exclus
            mode = row.get("mode")
            if mode in exclude_modes:
                continue
            ts = row.get("started_at")
            if not ts:
                continue
            # Postgres timestamptz arrive en string ISO. Parse en datetime aware.
            try:
                # Format Supabase : "2026-04-28T13:33:03.151499+00:00"
                if isinstance(ts, str):
                    ts = ts.replace("Z", "+00:00")
                    return datetime.fromisoformat(ts)
                return ts
            except Exception:
                continue
        return None

    def start_sync_run(self, mode: str, triggered_by: str = "manual") -> str:
        res = self.client.table("sync_runs").insert({
            "mode": mode,
            "status": "running",
            "triggered_by": triggered_by,
        }).execute()
        run_id = res.data[0]["id"]
        logger.info("Started sync_run %s (mode=%s)", run_id, mode)
        return run_id

    def finish_sync_run(
        self,
        run_id: str,
        *,
        status: str,
        stats: dict[str, Any],
        error_message: str | None = None,
        started_at: datetime | None = None,
    ) -> None:
        finished = datetime.now(timezone.utc)
        duration_ms = None
        if started_at is not None:
            duration_ms = int((finished - started_at).total_seconds() * 1000)
        self.client.table("sync_runs").update({
            "status": status,
            "finished_at": finished.isoformat(),
            "duration_ms": duration_ms,
            "stats": stats,
            "error_message": error_message,
        }).eq("id", run_id).execute()
        logger.info(
            "Finished sync_run %s status=%s duration=%sms stats=%s",
            run_id, status, duration_ms, stats,
        )

    # ---- Bulk sync ----------------------------------------------------------
    def bulk_sync(
        self,
        *,
        table: str,
        entity_type: str,
        records: list[dict[str, Any]],
        run_id: str,
        label_keys: tuple[str, ...] = ("name", "title", "label"),
        hash_keys: tuple[str, ...] | None = None,
    ) -> dict[str, int]:
        """Sync un ensemble d'entités en mode batch.

        Étapes (constant-time en nombre d'appels HTTP, ne dépend pas du nombre d'entités) :
        1. Upsert des records dans la table métier (par chunks).
        2. Fetch des dernières snapshots existantes pour ces entités.
        3. Comparaison hashes -> détermine created / updated / unchanged.
        4. Insert des nouvelles snapshots (par chunks).
        5. Insert des changes correspondants (par chunks).
        """
        stats = {"seen": len(records), "created": 0, "updated": 0, "unchanged": 0}
        if not records:
            return stats

        now_iso = datetime.now(timezone.utc).isoformat()
        for r in records:
            r["last_seen_at"] = now_iso

        # 1. Upsert table métier par chunks
        for chunk in _chunked(records, CHUNK_SIZE):
            self.client.table(table).upsert(
                chunk, on_conflict="ns_internal_id"
            ).execute()

        # 2. Calcul des hashes locaux
        hashes = {
            r["ns_internal_id"]: _stable_hash(r, include_keys=hash_keys)
            for r in records
        }
        ns_ids = list(hashes.keys())

        # 3. Fetch snapshots existantes (par chunks pour limiter la taille de l'URL)
        existing_latest: dict[str, dict[str, Any]] = {}
        for chunk in _chunked(ns_ids, 200):
            res = (
                self.client.table("snapshots")
                .select("ns_internal_id,content_hash,payload,captured_at")
                .eq("entity_type", entity_type)
                .in_("ns_internal_id", chunk)
                .order("captured_at", desc=True)
                .execute()
            )
            # On veut le plus récent par ns_internal_id, l'API renvoie déjà ordonné desc
            for row in res.data or []:
                ns_id = row["ns_internal_id"]
                if ns_id not in existing_latest:
                    existing_latest[ns_id] = row

        # 4. Tri created / updated / unchanged
        new_snapshots: list[dict[str, Any]] = []
        new_changes: list[dict[str, Any]] = []
        for r in records:
            ns_id = r["ns_internal_id"]
            new_hash = hashes[ns_id]
            existing = existing_latest.get(ns_id)
            if existing and existing.get("content_hash") == new_hash:
                stats["unchanged"] += 1
                continue
            kind = "updated" if existing else "created"
            stats[kind] += 1

            new_snapshots.append({
                "entity_type": entity_type,
                "ns_internal_id": ns_id,
                "payload": r,
                "content_hash": new_hash,
                "sync_run_id": run_id,
                "captured_at": now_iso,
            })
            label = next((r.get(k) for k in label_keys if r.get(k)), None)
            prev_payload = existing.get("payload") if existing else None
            new_changes.append({
                "entity_type": entity_type,
                "ns_internal_id": ns_id,
                "entity_label": label,
                "kind": kind,
                "diff": _compute_diff(prev_payload, r),
                "changed_at": now_iso,
                "sync_run_id": run_id,
            })

        # 5. Inserts batch (snapshots + changes)
        # On utilise upsert avec on_conflict sur la contrainte uq_snapshots_dedup
        # pour gérer les rollbacks (un fichier qui repasse par un hash déjà vu).
        # Dans ce cas, on rafraîchit juste captured_at + sync_run_id pour que
        # le snapshot existant redevienne "le plus récent".
        for chunk in _chunked(new_snapshots, CHUNK_SIZE):
            self.client.table("snapshots").upsert(
                chunk,
                on_conflict="entity_type,ns_internal_id,content_hash",
            ).execute()
        for chunk in _chunked(new_changes, CHUNK_SIZE):
            self.client.table("changes").insert(chunk).execute()

        return stats

    def detect_deletions(
        self,
        *,
        table: str,
        entity_type: str,
        seen_ns_ids: list[str],
        run_id: str,
        label_column: str = "name",
    ) -> dict[str, int]:
        """Marque comme `is_deleted=true` les entités présentes en base mais
        ABSENTES de la liste actuelle (= elles n'ont pas été remontées par
        l'extractor cette fois-ci).

        À appeler APRÈS un extract complet pour le même type d'entité.
        Ne fait rien si `seen_ns_ids` est vide (sécurité — évite de tout
        deleter en cas de bug d'extraction qui ne remonte rien).

        Args:
            table: nom de la table métier (ex: 'scripts', 'saved_searches')
            entity_type: valeur enum entity_type (ex: 'script', 'saved_search')
            seen_ns_ids: liste des ns_internal_id vus dans l'extraction courante
            run_id: id du sync_run en cours
            label_column: colonne à lire pour l'entity_label dans `changes`
                (ex: 'name', 'title', 'label')

        Returns:
            stats dict {newly_deleted, total_deleted}
        """
        stats = {"newly_deleted": 0, "total_deleted": 0}
        if not seen_ns_ids:
            logger.warning(
                "detect_deletions(%s): liste vide, skip pour éviter de tout deleter",
                table,
            )
            return stats

        now_iso = datetime.now(timezone.utc).isoformat()
        seen_set = set(str(x) for x in seen_ns_ids)

        # 1. Récupère TOUS les ns_internal_id de la table métier qui ne sont pas
        #    encore marqués deleted, par chunks pour gérer les grandes tables.
        not_yet_deleted: list[dict[str, Any]] = []
        page_size = 1000
        offset = 0
        while True:
            res = (
                self.client.table(table)
                .select(f"ns_internal_id,{label_column}")
                .eq("is_deleted", False)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            page = res.data or []
            not_yet_deleted.extend(page)
            if len(page) < page_size:
                break
            offset += page_size

        # 2. Diff : ce qui est en base et pas dans seen_ns_ids = supprimé
        to_delete = [r for r in not_yet_deleted if r["ns_internal_id"] not in seen_set]
        stats["newly_deleted"] = len(to_delete)
        if not to_delete:
            return stats

        logger.info(
            "detect_deletions(%s): %d entité(s) marquée(s) supprimée(s)",
            table, len(to_delete),
        )

        # 3. Update is_deleted=true + deleted_at
        ids_to_delete = [r["ns_internal_id"] for r in to_delete]
        for chunk in _chunked(ids_to_delete, 200):
            self.client.table(table).update({
                "is_deleted": True,
                "deleted_at": now_iso,
            }).in_("ns_internal_id", chunk).execute()

        # 4. Log dans `changes` (kind='deleted')
        change_rows = []
        for r in to_delete:
            change_rows.append({
                "entity_type": entity_type,
                "ns_internal_id": r["ns_internal_id"],
                "entity_label": r.get(label_column),
                "kind": "deleted",
                "diff": {"deleted": True},
                "changed_at": now_iso,
                "sync_run_id": run_id,
            })
        for chunk in _chunked(change_rows, CHUNK_SIZE):
            self.client.table("changes").insert(chunk).execute()

        # 5. Total deleted dans la table après l'update
        res_count = (
            self.client.table(table)
            .select("ns_internal_id", count="exact")
            .eq("is_deleted", True)
            .execute()
        )
        stats["total_deleted"] = res_count.count or 0

        return stats
