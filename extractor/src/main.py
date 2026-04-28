"""Orchestrateur principal de l'extraction NetSuite → Supabase."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from .anthropic_client import AnthropicClient
from .config import load_settings, setup_logging
from .extractors.ai_docs import extract_ai_docs
from .extractors.custom_records import extract_custom_record_types
from .extractors.fields import extract_custom_fields
from .extractors.saved_searches import extract_saved_searches
from .extractors.script_files import extract_script_files
from .extractors.scripts import extract_scripts, extract_script_deployments
from .extractors.system_notes import extract_system_notes
from .extractors.update_docs import extract_update_docs
from .extractors.workflows import extract_workflows
from .file_cabinet import FileCabinetClient
from .metadata import MetadataClient
from .saved_search_client import SavedSearchClient
from .suiteql import SuiteQLClient
from .supabase_client import SupabaseStore

logger = logging.getLogger("extractor")


def cmd_ping(args: argparse.Namespace) -> int:
    settings = load_settings()
    setup_logging(settings.log_level)

    logger.info("=== PING test ===")
    logger.info("Account: %s", settings.ns_account_id)
    logger.info("REST base URL: %s", settings.ns_rest_base_url)

    suiteql = SuiteQLClient(settings)
    try:
        result = suiteql.ping()
        logger.info("✅ Connexion NetSuite (SuiteQL) OK: %s", result)
    except Exception as e:
        logger.error("❌ Connexion NetSuite KO: %s", e)
        return 2

    try:
        store = SupabaseStore(settings)
        run_id = store.start_sync_run(mode="ping", triggered_by="cli")
        store.finish_sync_run(
            run_id, status="success", stats={"ping": True},
            started_at=datetime.now(timezone.utc),
        )
        logger.info("✅ Connexion Supabase OK")
    except Exception as e:
        logger.error("❌ Connexion Supabase KO: %s", e)
        return 3

    logger.info("✅ Tout est OK, prêt pour une extraction.")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    settings = load_settings()
    setup_logging(settings.log_level)

    suiteql = SuiteQLClient(settings)
    metadata_client = MetadataClient(settings)
    file_client = FileCabinetClient(settings)
    store = SupabaseStore(settings)

    started = datetime.now(timezone.utc)
    run_id = store.start_sync_run(mode=args.mode, triggered_by=args.triggered_by)
    stats: dict[str, dict[str, int]] = {}
    errors: list[str] = []
    limit = args.limit

    # En mode incremental, on ne refetch que ce qui a été modifié depuis le
    # dernier run réussi. Le filtre est appliqué INDÉPENDAMMENT à 3 niveaux :
    #   1. script.lastmodifieddate     → record script (rename, status…)
    #   2. scriptdeployment.lastmodifieddate → audience, log_level…
    #   3. file.lastmodifieddate       → vraie modif du source code
    # En mode full, modified_since=None → on tire tout (et on détecte les
    # suppressions).
    modified_since = None
    if args.mode == "incremental":
        modified_since = store.get_last_successful_run_at()
        if modified_since is None:
            logger.info(
                "Mode incremental mais aucun run réussi précédent : on bascule en full extract"
            )
        else:
            logger.info("Mode incremental : modifs depuis %s", modified_since.isoformat())

    def safe(name: str, fn, *fn_args, **fn_kwargs):
        try:
            stats[name] = fn(*fn_args, **fn_kwargs)
        except Exception as e:
            logger.exception("❌ Échec de l'extraction %s: %s", name, e)
            errors.append(f"{name}: {e}")
            stats[name] = {"error": str(e)}

    if args.scripts:
        safe("scripts", extract_scripts, suiteql, store, run_id,
             limit=limit, modified_since=modified_since)
        safe("script_deployments", extract_script_deployments, suiteql, store, run_id,
             limit=limit, modified_since=modified_since)

    if args.script_files:
        safe("script_files", extract_script_files, file_client, store, run_id,
             limit=limit, modified_since=modified_since, suiteql=suiteql)

    if args.fields:
        safe("custom_fields", extract_custom_fields, suiteql, metadata_client, store, run_id, limit=limit)

    if args.custom_records:
        safe("custom_record_types", extract_custom_record_types, suiteql, store, run_id, limit=limit)

    if args.system_notes:
        safe(
            "system_notes",
            extract_system_notes,
            suiteql, store, run_id,
            days_back=args.system_notes_days, limit=limit,
        )

    if args.saved_searches:
        if not (settings.ns_search_reader_script_id and settings.ns_search_reader_deploy_id):
            logger.warning(
                "⚠️  --saved-searches activé mais NS_SEARCH_READER_SCRIPT_ID/_DEPLOY_ID "
                "manquants dans .env. Voir extractor/netsuite/DEPLOY_SAVED_SEARCH_RESTLET.md. "
                "Skip de l'extraction des saved searches."
            )
        else:
            search_client = SavedSearchClient(settings)
            safe(
                "saved_searches",
                extract_saved_searches,
                search_client, store, run_id,
                limit=limit,
                only_ndk=not args.saved_searches_all,
                force=args.saved_searches_force,
            )

    if args.workflows:
        safe(
            "workflows",
            extract_workflows,
            suiteql, store, run_id,
            limit=limit,
        )

    if args.ai_docs:
        if not settings.anthropic_api_key:
            logger.warning("⚠️  --ai-docs activé mais ANTHROPIC_API_KEY manquante, skip")
        else:
            anthropic = AnthropicClient(settings)
            safe(
                "ai_docs",
                extract_ai_docs,
                anthropic, store, run_id,
                limit=limit, force_all=args.ai_docs_force,
            )

    if args.update_docs:
        if not settings.anthropic_api_key:
            logger.warning("⚠️  --update-docs activé mais ANTHROPIC_API_KEY manquante, skip")
        else:
            anthropic = AnthropicClient(settings)
            safe(
                "update_docs",
                extract_update_docs,
                anthropic, store, run_id,
                limit=limit,
                # En mode incremental, on ne traite que les changes du run courant
                since_run_id=run_id if args.mode == "incremental" else None,
            )

    final_status = "success" if not errors else ("partial" if stats else "failed")
    store.finish_sync_run(
        run_id, status=final_status, stats=stats,
        error_message="; ".join(errors) if errors else None,
        started_at=started,
    )

    if errors:
        logger.warning("⚠️ Extraction terminée avec %s erreur(s):", len(errors))
        for err in errors:
            logger.warning("  - %s", err)
    else:
        logger.info("✅ Extraction terminée: %s", stats)

    return 0 if not errors else 1


def cmd_saved_searches(args: argparse.Namespace) -> int:
    """Sous-commande dédiée à l'extraction des saved searches.

    Pratique en dev/test pour itérer rapidement sans relancer toute la chaîne.
    """
    settings = load_settings()
    setup_logging(settings.log_level)

    if not (settings.ns_search_reader_script_id and settings.ns_search_reader_deploy_id):
        logger.error(
            "❌ NS_SEARCH_READER_SCRIPT_ID et NS_SEARCH_READER_DEPLOY_ID manquants dans .env. "
            "Voir extractor/netsuite/DEPLOY_SAVED_SEARCH_RESTLET.md."
        )
        return 2

    store = SupabaseStore(settings)
    search_client = SavedSearchClient(settings)

    started = datetime.now(timezone.utc)
    run_id = store.start_sync_run(
        mode="saved_searches",
        triggered_by=args.triggered_by,
    )

    try:
        stats = extract_saved_searches(
            search_client, store, run_id,
            limit=args.limit,
            only_ndk=not args.all,
            force=args.force,
            list_only=args.list_only,
        )
        store.finish_sync_run(
            run_id, status="success", stats={"saved_searches": stats},
            started_at=started,
        )
        logger.info("✅ saved-searches: %s", stats)
        return 0
    except Exception as e:
        logger.exception("❌ saved-searches a échoué: %s", e)
        store.finish_sync_run(
            run_id, status="failed", stats={},
            error_message=str(e),
            started_at=started,
        )
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extractor")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ping = sub.add_parser("ping", help="Test de connexion NetSuite + Supabase")
    p_ping.set_defaults(func=cmd_ping)

    p_extract = sub.add_parser("extract", help="Lancer une extraction")
    p_extract.add_argument("--mode", default="full", choices=["full", "incremental"])
    p_extract.add_argument("--triggered-by", default="manual")
    p_extract.add_argument("--limit", type=int, default=None,
                           help="Limiter chaque extraction à N lignes")

    # Switches par type d'objet (tous activés par défaut)
    p_extract.add_argument("--scripts", action="store_true", default=True)
    p_extract.add_argument("--no-scripts", dest="scripts", action="store_false")
    p_extract.add_argument("--fields", action="store_true", default=True)
    p_extract.add_argument("--no-fields", dest="fields", action="store_false")
    p_extract.add_argument("--custom-records", action="store_true", default=True)
    p_extract.add_argument("--no-custom-records", dest="custom_records", action="store_false")
    p_extract.add_argument("--system-notes", action="store_true", default=True)
    p_extract.add_argument("--no-system-notes", dest="system_notes", action="store_false")
    p_extract.add_argument("--saved-searches", action="store_true", default=True,
                           help="Extraire les définitions de saved searches via RESTlet")
    p_extract.add_argument("--no-saved-searches", dest="saved_searches", action="store_false")
    p_extract.add_argument("--saved-searches-all", action="store_true", default=False,
                           help="Extraire TOUTES les saved searches (par défaut: customs NDK uniquement)")
    p_extract.add_argument("--saved-searches-force", action="store_true", default=False,
                           help="Re-fetch les définitions même si content_sha256 inchangé")
    p_extract.add_argument("--script-files", action="store_true", default=True,
                           help="Télécharger le contenu des fichiers JS")
    p_extract.add_argument("--no-script-files", dest="script_files", action="store_false")
    p_extract.add_argument("--ai-docs", action="store_true", default=True,
                           help="Générer la doc IA pour les scripts qui en ont besoin")
    p_extract.add_argument("--no-ai-docs", dest="ai_docs", action="store_false")
    p_extract.add_argument("--ai-docs-force", action="store_true", default=False,
                           help="Re-générer la doc IA pour TOUS les scripts (même ceux déjà documentés)")
    p_extract.add_argument("--update-docs", action="store_true", default=True,
                           help="Générer la doc IA d'update pour les scripts modifiés")
    p_extract.add_argument("--no-update-docs", dest="update_docs", action="store_false")
    p_extract.add_argument("--workflows", action="store_true", default=True,
                           help="Extraire la liste des workflows via SuiteQL")
    p_extract.add_argument("--no-workflows", dest="workflows", action="store_false")
    p_extract.add_argument("--system-notes-days", type=int, default=30,
                           help="Profondeur d'extraction des system notes (jours)")

    p_extract.set_defaults(func=cmd_extract)

    # ---------------- Sous-commande dédiée: saved-searches --------------------
    p_ss = sub.add_parser(
        "saved-searches",
        help="Extraire uniquement les saved searches (pratique en dev/test)",
    )
    p_ss.add_argument("--limit", type=int, default=None,
                      help="Limiter à N saved searches (utile en test)")
    p_ss.add_argument("--all", action="store_true", default=False,
                      help="Extraire TOUTES les SS (défaut: customs NDK uniquement)")
    p_ss.add_argument("--force", action="store_true", default=False,
                      help="Re-fetch même si content_sha256 inchangé")
    p_ss.add_argument("--list-only", action="store_true", default=False,
                      help="Ne fait QUE le listing + breakdown par préfixe + échantillon "
                           "(pas de fetch, pas d'insert). Utile pour valider le périmètre.")
    p_ss.add_argument("--triggered-by", default="manual")
    p_ss.set_defaults(func=cmd_saved_searches)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
