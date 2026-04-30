"""Génération automatique de documentation IA pour les scripts.

Logique :
- On itère sur les scripts qui ont un script_source_file en base.
- Pour chacun, on génère une doc UNIQUEMENT si :
    1. Aucune doc n'existe ENCORE → on génère.
    2. Une doc existe, est ai_generated=true, status != 'published',
       et le SHA256 du fichier source a changé depuis la dernière génération.
- On NE TOUCHE PAS aux docs avec status='published' (rédigées/validées par un humain).

Coût/perf : ~3-5s par appel Claude. Avec 8 workers parallèles → ~5-10 min pour 2244 scripts.
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from ..anthropic_client import AnthropicClient
from ..supabase_client import SupabaseStore

logger = logging.getLogger(__name__)

PARALLEL_WORKERS = 1  # Free tier 5 RPM => 1 worker suffit. Override via ANTHROPIC_WORKERS env var.
MAX_CODE_CHARS = 30000  # tronque le code trop long pour limiter le coût


SYSTEM_PROMPT = """Tu es un expert NetSuite SuiteScript chargé de documenter le code d'un compte client.
On te donne le code source d'un script SuiteScript et son contexte (type, métadonnées, JSDoc tags extraits).
Tu réponds en français, en JSON strict avec ces clés exactement :
{
  "business_purpose": "1-2 phrases : à quoi sert ce script du point de vue métier (français)",
  "technical_summary": "3-6 lignes : comment il fonctionne techniquement (modules N/ utilisés, logique principale, points d'attention techniques)",
  "usage_notes": "1-3 phrases : quand il tourne, qui doit s'en occuper, points d'attention",
  "tags": ["tag1", "tag2"]
}
Sois concret et factuel. Si tu n'es pas sûr, marque "(à confirmer)" plutôt que d'inventer.
Pas de commentaires en dehors du JSON. Pas de markdown. JSON uniquement."""


def _build_user_message(script: dict[str, Any], src: dict[str, Any]) -> str:
    code = src.get("content") or ""
    if len(code) > MAX_CODE_CHARS:
        code = code[:MAX_CODE_CHARS] + "\n... (code tronqué)"

    return f"""Voici le contexte d'un script NetSuite et son code source.

# Métadonnées
- Nom : {script.get('name')}
- Script ID : {script.get('script_id')}
- Type : {script.get('script_type')}
- API Version : {script.get('api_version') or '—'}
- Fichier : {src.get('file_name')}
- JSDoc tags extraits : {json.dumps(src.get('jsdoc') or {})}

# Code source
```javascript
{code}
```

Génère la doc demandée au format JSON."""


def _parse_response(text: str) -> dict[str, Any]:
    """Parse le JSON renvoyé par Claude (peut avoir un peu de texte autour)."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"Pas de JSON trouvé: {text[:200]}")
    return json.loads(m.group(0))


def _select_candidates(store: SupabaseStore, force_all: bool = False) -> list[dict[str, Any]]:
    """Sélectionne les scripts qui ont besoin d'une doc IA.

    Stratégie :
    - On récupère TOUS les scripts qui ont un fichier source.
    - On récupère TOUTES les docs existantes (en parallèle).
    - On filtre côté Python : besoin de doc si pas de doc, ou si SHA changé et pas published.
    """
    # Tous les scripts avec un fichier source (paginé pour contourner la limite Supabase)
    all_scripts: dict[str, dict[str, Any]] = {}
    offset = 0
    PAGE = 1000
    while True:
        scripts_res = (
            store.client.table("scripts")
            .select("ns_internal_id,script_id,name,script_type,api_version,is_inactive")
            .eq("is_inactive", False)
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        batch = scripts_res.data or []
        for s in batch:
            all_scripts[s["ns_internal_id"]] = s
        if len(batch) < PAGE:
            break
        offset += PAGE

    # Tous les fichiers source (paginé — contient le code donc lourd)
    files_by_script: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        files_res = (
            store.client.table("script_source_files")
            .select("script_ns_id,file_name,content,jsdoc,content_sha256")
            .not_.is_("script_ns_id", "null")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        batch = files_res.data or []
        for f in batch:
            files_by_script[f["script_ns_id"]] = f
        if len(batch) < PAGE:
            break
        offset += PAGE

    # Toutes les docs existantes (paginé)
    docs_by_script: dict[str, dict[str, Any]] = {}
    offset = 0
    while True:
        docs_res = (
            store.client.table("script_docs")
            .select("script_ns_id,status,ai_generated,source_sha256_at_generation")
            .range(offset, offset + PAGE - 1)
            .execute()
        )
        batch = docs_res.data or []
        for d in batch:
            docs_by_script[d["script_ns_id"]] = d
        if len(batch) < PAGE:
            break
        offset += PAGE

    # Filtre : pour chaque script avec un fichier, doit-on (re)générer ?
    candidates = []
    for script_id, script in all_scripts.items():
        src = files_by_script.get(script_id)
        if not src or not src.get("content"):
            continue  # pas de code source -> rien à analyser

        existing = docs_by_script.get(script_id)

        if force_all:
            need = True
        elif not existing:
            need = True  # pas de doc -> on crée
        elif existing.get("status") == "published":
            need = False  # validé humain -> intouchable
        elif existing.get("ai_generated"):
            # IA-generated → re-gen seulement si SHA changé
            prev_sha = existing.get("source_sha256_at_generation")
            need = prev_sha != src.get("content_sha256")
        else:
            need = False  # doc humaine non-published, on laisse

        if need:
            candidates.append({"script": script, "src": src, "existing": existing})

    return candidates


def _generate_one(
    client: AnthropicClient,
    script: dict[str, Any],
    src: dict[str, Any],
) -> dict[str, Any] | None:
    """Appelle Claude et retourne le payload prêt à être sauvegardé."""
    user_msg = _build_user_message(script, src)
    try:
        text, usage = client.call(system=SYSTEM_PROMPT, user_message=user_msg, max_tokens=800)
    except Exception as e:
        logger.warning("  Claude error for %s: %s", script.get("name"), str(e)[:120])
        return None

    try:
        parsed = _parse_response(text)
    except Exception as e:
        logger.warning("  parse error for %s: %s; raw: %s", script.get("name"), e, text[:200])
        return None

    return {
        "script_ns_id": script["ns_internal_id"],
        "business_purpose": parsed.get("business_purpose"),
        "technical_summary": parsed.get("technical_summary"),
        "usage_notes": parsed.get("usage_notes"),
        "tags": parsed.get("tags") or [],
        "status": "draft",
        "ai_generated": True,
        "ai_model": client.model,
        "source_sha256_at_generation": src.get("content_sha256"),
        "last_ai_generated_at": datetime.now(timezone.utc).isoformat(),
        "ai_tokens_used": (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) if usage else None,
    }


def extract_ai_docs(
    client: AnthropicClient,
    store: SupabaseStore,
    run_id: str,
    *,
    limit: int | None = None,
    force_all: bool = False,
) -> dict[str, int]:
    """Génère ou met à jour les docs IA pour les scripts qui en ont besoin."""
    logger.info("Selecting candidates for AI doc generation...")
    candidates = _select_candidates(store, force_all=force_all)
    logger.info("Found %s scripts needing AI doc", len(candidates))

    if limit is not None:
        candidates = candidates[:limit]
        logger.info("Limiting to %s for this run", limit)

    if not candidates:
        return {"seen": 0, "generated": 0, "failed": 0, "skipped": 0}

    stats = {"seen": len(candidates), "generated": 0, "failed": 0, "skipped": 0, "tokens_total": 0}
    payloads: list[dict[str, Any]] = []
    completed = 0

    workers = int(os.getenv("ANTHROPIC_WORKERS", str(PARALLEL_WORKERS)))
    logger.info("Using %s parallel worker(s) — rate limit gere par AnthropicClient", workers)

    INCREMENTAL_BATCH = 5  # upsert par paquets de 5 pour voir l'avancement en direct
    pending: list[dict[str, Any]] = []

    def flush_pending():
        nonlocal pending
        if pending:
            try:
                store.client.table("script_docs").upsert(
                    pending, on_conflict="script_ns_id"
                ).execute()
                logger.info("  💾 sauvegardé %s docs (total %s)", len(pending), stats["generated"])
            except Exception as e:
                logger.error("  ❌ flush failed: %s — gardé en mémoire pour le prochain flush", e)
                return
            payloads.extend(pending)
            pending = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(_generate_one, client, c["script"], c["src"]): c
            for c in candidates
        }
        for fut in as_completed(futures):
            c = futures[fut]
            completed += 1
            try:
                payload = fut.result()
            except Exception as e:
                stats["failed"] += 1
                logger.warning("  generation crash on %s: %s", c["script"].get("name"), e)
                continue

            if payload is None:
                stats["failed"] += 1
                continue

            stats["generated"] += 1
            stats["tokens_total"] += payload.get("ai_tokens_used") or 0
            pending.append(payload)

            # Flush périodique pour voir les résultats sans attendre la fin
            if len(pending) >= INCREMENTAL_BATCH:
                flush_pending()

            if completed % 10 == 0 or completed == len(candidates):
                logger.info(
                    "  %s/%s — generated=%s failed=%s tokens=%s",
                    completed, len(candidates),
                    stats["generated"], stats["failed"], stats["tokens_total"],
                )

    # Final flush au cas où il reste des items
    flush_pending()

    logger.info("AI docs done: %s", stats)
    return stats
