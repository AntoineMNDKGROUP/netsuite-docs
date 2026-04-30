"""Pipeline IA pour générer un résumé court (1-2 phrases) de chaque update
de source code de script.

Logique :
1. Trouver les script_source_file qui ont AU MOINS 2 snapshots (= ils ont changé
   au moins une fois). On prend le dernier change détecté côté `changes` pour
   savoir lesquels sont des candidats récents.
2. Pour chaque candidat, charger les 2 derniers snapshots (par captured_at desc).
3. Skipper si on a déjà une entrée dans `script_update_docs` avec la même paire
   (sha_before, sha_after) — déduplication.
4. Computer le diff (unified_diff) sur les 2 versions du content.
5. Envoyer à Claude avec un prompt court demandant un résumé en 1-2 phrases.
6. Insérer dans `script_update_docs`.

Le pipeline est idempotent : on peut le relancer sans risque, il skip les
paires déjà documentées via le UNIQUE INDEX `uq_update_docs_dedup`.
"""
from __future__ import annotations

import difflib
import logging
from datetime import datetime, timezone
from typing import Any

from ..anthropic_client import AnthropicClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)


# Prompt système : court, ciblé, en français
SYSTEM_PROMPT = """Tu es un assistant qui résume en français les changements
apportés à un script SuiteScript NetSuite. Tu reçois un diff unifié entre 2
versions consécutives. Tu produis un résumé TRÈS COURT (1-2 phrases maximum,
50-200 caractères) qui décrit la nature du changement de manière concrète.

Style attendu :
- Va à l'essentiel : ce qui change métier ou techniquement.
- Pas de phrases d'amorce du genre "Ce diff montre que…" — commence directement.
- Si c'est juste de la mise en forme / refactor mineur, dis-le brièvement.
- Si c'est un nouveau check, une nouvelle fonctionnalité, un bug fix, dis-le.
- Mentionne les ID custom (custbody_xxx, custscript_xxx) ou IDs hardcodés
  modifiés s'ils sont pertinents.

Exemples de bons résumés :
- "Ajout d'un check sur custbody_credit_hold avant submit + nouvel email
  d'alerte aux ops US."
- "Refactor : extraction de la logique de pricing dans une fonction helper.
  Pas de changement fonctionnel."
- "Bug fix : la condition `subsidiary == 5` était inversée, plante en sub NUS."
- "Ajout du support des items footwear (brand IDs 34, 35, 36) au parsing."
"""


# Prompt pour le PREMIER indexage (pas de version précédente).
SYSTEM_PROMPT_INITIAL = """Tu es un assistant qui résume en français le rôle
d'un script SuiteScript NetSuite que l'on indexe pour la PREMIÈRE FOIS. Tu
reçois le code source et tu produis un résumé TRÈS COURT (1-2 phrases maximum,
50-200 caractères) qui décrit ce que fait ce script.

Style attendu :
- Va à l'essentiel : le rôle métier ou technique du script.
- Préfixe ta réponse par "Premier indexage : ".
- Pas de phrases d'amorce du genre "Ce script…" — commence directement après
  le préfixe.
- Mentionne le type de script (User Event, Suitelet, Map/Reduce, etc.) si
  pertinent.

Exemples :
- "Premier indexage : User Event sur Sales Order qui propage le tax code header sur les lignes."
- "Premier indexage : Suitelet d'export d'invoices vers SFTP pour audit fiscal."
- "Premier indexage : Map/Reduce qui synchronise les statuts d'expédition depuis l'ERP externe."
"""


# Limite de code source envoyée pour la doc initiale (limite coût Claude).
INITIAL_MAX_CODE_CHARS = 8000



def _build_unified_diff(old_content: str, new_content: str, file_name: str = "") -> str:
    """Construit un diff unifié court (max ~200 lignes) entre 2 versions."""
    old_lines = (old_content or "").splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)
    diff_iter = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=f"a/{file_name or 'file'}",
        tofile=f"b/{file_name or 'file'}",
        lineterm="",
        n=3,  # 3 lignes de contexte
    )
    diff_lines = list(diff_iter)
    # Limite à ~400 lignes pour ne pas exploser le prompt (et donc le coût IA)
    MAX_LINES = 400
    if len(diff_lines) > MAX_LINES:
        head = diff_lines[: MAX_LINES // 2]
        tail = diff_lines[-MAX_LINES // 2 :]
        diff_lines = head + ["…", "(diff tronqué — trop long pour être inclus en entier)", "…"] + tail
    return "\n".join(diff_lines)


def _count_diff_lines(diff_text: str) -> tuple[int, int]:
    """Compte les lignes ajoutées/retirées dans un diff unifié.
    Ignore les headers `+++` et `---` qui ne sont pas de vrais ajouts/retraits.
    """
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return added, removed


def _resolve_script_ns_id(store: SupabaseStore, file_id: str) -> str | None:
    """Trouve le script_ns_id qui référence ce script_source_file.
    Si plusieurs scripts pointent sur le même fichier (libs partagées), prend le
    premier. Si aucun, renvoie None.
    """
    res = (
        store.client.table("scripts")
        .select("ns_internal_id")
        .eq("script_file", file_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if rows:
        return rows[0]["ns_internal_id"]
    return None


def extract_update_docs(
    anthropic: AnthropicClient,
    store: SupabaseStore,
    run_id: str,
    *,
    limit: int | None = None,
    since_run_id: str | None = None,
) -> dict[str, int]:
    """Génère les docs IA d'update pour les scripts dont le source code a changé.

    Args:
        anthropic: client API Anthropic
        store: client Supabase
        run_id: id du sync_run en cours (pour traçabilité)
        limit: nombre max de docs à générer dans cette passe (utile en test)
        since_run_id: si défini, ne traite que les changes de ce run-là.
            Si None, prend tous les `kind='updated'` détectés sur les
            script_source_file qui n'ont PAS encore de doc d'update.

    Returns:
        stats dict {seen_changes, eligible, generated, skipped_dup, errors,
                    no_prev_snapshot, ai_tokens_used}
    """
    stats = {
        "seen_changes": 0,
        "eligible": 0,
        "generated": 0,
        "skipped_dup": 0,
        "errors": 0,
        "no_prev_snapshot": 0,
        "ai_tokens_used": 0,
    }

    # 1. Liste les changes script_source_file de type 'updated' à traiter
    query = (
        store.client.table("changes")
        .select("ns_internal_id,entity_label,changed_at,sync_run_id")
        .eq("entity_type", "script_source_file")
        .eq("kind", "updated")
        .order("changed_at", desc=True)
    )
    if since_run_id:
        query = query.eq("sync_run_id", since_run_id)
    res = query.execute()
    changes = res.data or []
    stats["seen_changes"] = len(changes)

    if not changes:
        logger.info("update_docs: aucun change script_source_file 'updated' à traiter")
        return stats

    # On dédoublonne par file_id (on prend juste le change le plus récent par
    # fichier, vu que la clé de dédup `script_update_docs` est sur sha pas date)
    seen_files: dict[str, dict[str, Any]] = {}
    for c in changes:
        fid = c["ns_internal_id"]
        if fid not in seen_files:
            seen_files[fid] = c
    candidates = list(seen_files.values())
    stats["eligible"] = len(candidates)
    logger.info(
        "update_docs: %d change(s) total, %d fichier(s) unique(s) à traiter",
        stats["seen_changes"], stats["eligible"],
    )

    if limit:
        candidates = candidates[:limit]
        logger.info("  --limit appliqué : %d à traiter", len(candidates))

    # 2. Pour chaque candidat, fetch les 2 derniers snapshots
    for idx, change in enumerate(candidates, 1):
        file_id = change["ns_internal_id"]
        file_name = change.get("entity_label") or "(unknown)"

        snap_res = (
            store.client.table("snapshots")
            .select("payload,content_hash,captured_at")
            .eq("entity_type", "script_source_file")
            .eq("ns_internal_id", file_id)
            .order("captured_at", desc=True)
            .limit(2)
            .execute()
        )
        snaps = snap_res.data or []

        if len(snaps) == 0:
            # Pas de snapshot du tout — bug ou data manquante (impossible
            # normalement car on est arrivé ici via un change row)
            logger.warning(
                "[%d/%d] %s : aucun snapshot trouvé (data inconsistante)",
                idx, len(candidates), file_name,
            )
            stats["errors"] += 1
            continue

        if len(snaps) == 1:
            # Premier indexage du fichier — pas de version précédente, on
            # génère quand même un résumé "initial" qui décrit le rôle du
            # script. Ça permet à /ns-recent-updates de ne plus avoir de
            # trou pour les nouveaux scripts.
            stats["no_prev_snapshot"] += 1
            new_snap = snaps[0]
            new_sha = new_snap["content_hash"]
            new_content = (new_snap.get("payload") or {}).get("content") or ""

            if not new_content:
                logger.warning(
                    "[%d/%d] %s : snapshot sans content (skip initial)",
                    idx, len(candidates), file_name,
                )
                stats["errors"] += 1
                continue

            # Skip si déjà documenté (sha256_before NULL + sha256_after =
            # match via COALESCE dans uq_update_docs_dedup).
            script_ns_id = _resolve_script_ns_id(store, file_id) or file_id
            existing = (
                store.client.table("script_update_docs")
                .select("id")
                .eq("script_ns_id", script_ns_id)
                .is_("sha256_before", "null")
                .eq("sha256_after", new_sha)
                .limit(1)
                .execute()
            )
            if existing.data:
                stats["skipped_dup"] += 1
                continue

            code_to_send = new_content
            if len(code_to_send) > INITIAL_MAX_CODE_CHARS:
                code_to_send = code_to_send[:INITIAL_MAX_CODE_CHARS] + "\n... (code tronqué)"

            user_msg = (
                f"Fichier : {file_name}\n"
                f"Premier indexage du script (pas de version précédente).\n\n"
                f"Code source :\n```javascript\n{code_to_send}\n```\n\n"
                'Résume en 1-2 phrases (50-200 caractères) le rôle de ce script. '
                'Préfixe ta réponse par "Premier indexage : ".'
            )
            try:
                summary, usage = anthropic.call(
                    system=SYSTEM_PROMPT_INITIAL,
                    user_message=user_msg,
                    max_tokens=200,
                )
                tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
                stats["ai_tokens_used"] += tokens
            except Exception as e:
                logger.warning(
                    "[%d/%d] %s : échec IA (initial) : %s",
                    idx, len(candidates), file_name, e,
                )
                stats["errors"] += 1
                continue

            total_lines = len(new_content.splitlines())
            try:
                store.client.table("script_update_docs").insert({
                    "script_ns_id": script_ns_id,
                    "source_file_ns_id": file_id,
                    "sha256_before": None,  # premier indexage : pas de prev
                    "sha256_after": new_sha,
                    "summary": summary.strip(),
                    "diff_lines_added": total_lines,
                    "diff_lines_removed": 0,
                    "sync_run_id": run_id,
                    "ai_model": anthropic.model,
                    "ai_tokens_used": tokens,
                }).execute()
                stats["generated"] += 1
            except Exception as e:
                logger.debug(
                    "[%d/%d] %s : insert (initial) échec (probable dup) : %s",
                    idx, len(candidates), file_name, e,
                )
                stats["skipped_dup"] += 1

            if idx % 10 == 0:
                logger.info(
                    "  [%d/%d] (initial) generated=%d skipped_dup=%d errors=%d tokens=%d",
                    idx, len(candidates),
                    stats["generated"], stats["skipped_dup"],
                    stats["errors"], stats["ai_tokens_used"],
                )
            continue

        new_snap, old_snap = snaps[0], snaps[1]
        new_sha = new_snap["content_hash"]
        old_sha = old_snap["content_hash"]
        if new_sha == old_sha:
            # Bizarre — 2 snapshots avec même hash. Skip.
            stats["skipped_dup"] += 1
            continue

        # 3. Vérifie si on a déjà une entrée pour cette paire
        script_ns_id = _resolve_script_ns_id(store, file_id) or file_id  # fallback file_id
        existing = (
            store.client.table("script_update_docs")
            .select("id")
            .eq("script_ns_id", script_ns_id)
            .eq("sha256_after", new_sha)
            .limit(1)
            .execute()
        )
        if (existing.data or []):
            # Déjà documenté
            stats["skipped_dup"] += 1
            continue

        # 4. Compute diff
        new_content = (new_snap.get("payload") or {}).get("content") or ""
        old_content = (old_snap.get("payload") or {}).get("content") or ""
        if not new_content and not old_content:
            stats["errors"] += 1
            logger.warning("[%d/%d] %s : pas de content dans les snapshots", idx, len(candidates), file_name)
            continue

        diff_text = _build_unified_diff(old_content, new_content, file_name=file_name)
        added, removed = _count_diff_lines(diff_text)

        # 5. Appel IA
        user_msg = (
            f"Fichier : {file_name}\n"
            f"Lignes ajoutées : {added}, retirées : {removed}\n\n"
            f"Diff unifié :\n```diff\n{diff_text}\n```\n\n"
            "Résume en 1-2 phrases (50-200 caractères) ce qui a changé."
        )
        try:
            summary, usage = anthropic.call(
                system=SYSTEM_PROMPT,
                user_message=user_msg,
                max_tokens=200,
            )
            tokens = (usage.get("input_tokens", 0) or 0) + (usage.get("output_tokens", 0) or 0)
            stats["ai_tokens_used"] += tokens
        except Exception as e:
            logger.warning("[%d/%d] %s : échec IA : %s", idx, len(candidates), file_name, e)
            stats["errors"] += 1
            continue

        # 6. Insertion (avec gestion conflit unique)
        try:
            store.client.table("script_update_docs").insert({
                "script_ns_id": script_ns_id,
                "source_file_ns_id": file_id,
                "sha256_before": old_sha,
                "sha256_after": new_sha,
                "summary": summary.strip(),
                "diff_lines_added": added,
                "diff_lines_removed": removed,
                "sync_run_id": run_id,
                "ai_model": anthropic.model,
                "ai_tokens_used": tokens,
            }).execute()
            stats["generated"] += 1
        except Exception as e:
            # Probablement violation de l'unique index (race condition) — pas grave
            logger.debug("[%d/%d] %s : insert échec (probable dup) : %s", idx, len(candidates), file_name, e)
            stats["skipped_dup"] += 1

        if idx % 10 == 0:
            logger.info(
                "  [%d/%d] generated=%d skipped_dup=%d no_prev=%d errors=%d tokens=%d",
                idx, len(candidates),
                stats["generated"], stats["skipped_dup"],
                stats["no_prev_snapshot"], stats["errors"], stats["ai_tokens_used"],
            )

    logger.info("✅ update_docs: %s", stats)
    return stats
