"""Centralisation des variables d'environnement et de la config."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Charge le .env situé à la racine du package extractor (un cran au-dessus de src/)
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)


@dataclass(frozen=True)
class Settings:
    # NetSuite
    ns_account_id: str
    ns_consumer_key: str
    ns_consumer_secret: str
    ns_token_id: str
    ns_token_secret: str

    # Supabase
    supabase_url: str
    supabase_service_role_key: str

    # RESTlet pour la lecture des fichiers (optionnel, configuré après déploiement)
    ns_file_reader_script_id: str = ""
    ns_file_reader_deploy_id: str = ""

    # RESTlet pour la lecture des saved searches (optionnel, configuré après déploiement)
    ns_search_reader_script_id: str = ""
    ns_search_reader_deploy_id: str = ""

    # Anthropic (génération de doc IA, optionnel)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Logging
    log_level: str = "INFO"

    @property
    def ns_realm(self) -> str:
        """Realm OAuth NetSuite — l'Account ID en MAJUSCULES, '_' transformé en '-' pour le sandbox."""
        # NetSuite veut l'Account ID en majuscules dans le realm.
        # Pour les sandbox: format "1234567_SB1" → "1234567_SB1" (avec underscore conservé).
        return self.ns_account_id.upper()

    @property
    def _domain_id(self) -> str:
        """ID de domaine NetSuite (account_id avec underscore → tiret, lowercase)."""
        return self.ns_account_id.replace("_", "-").lower()

    @property
    def ns_rest_base_url(self) -> str:
        """Base URL pour SuiteTalk (REST Web Services + SuiteQL + metadata-catalog)."""
        return f"https://{self._domain_id}.suitetalk.api.netsuite.com"

    @property
    def ns_restlet_base_url(self) -> str:
        """Base URL spécifique aux RESTlets (domaine séparé chez NetSuite).

        Ex: 'https://4817474-sb1.restlets.api.netsuite.com'.
        """
        return f"https://{self._domain_id}.restlets.api.netsuite.com"

    @property
    def suiteql_url(self) -> str:
        return f"{self.ns_rest_base_url}/services/rest/query/v1/suiteql"


def _required(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(
            f"Variable d'environnement manquante: {name}. "
            f"Vérifie le fichier extractor/.env"
        )
    return val


def load_settings() -> Settings:
    return Settings(
        ns_account_id=_required("NS_ACCOUNT_ID"),
        ns_consumer_key=_required("NS_CONSUMER_KEY"),
        ns_consumer_secret=_required("NS_CONSUMER_SECRET"),
        ns_token_id=_required("NS_TOKEN_ID"),
        ns_token_secret=_required("NS_TOKEN_SECRET"),
        supabase_url=_required("SUPABASE_URL"),
        supabase_service_role_key=_required("SUPABASE_SERVICE_ROLE_KEY"),
        ns_file_reader_script_id=os.getenv("NS_FILE_READER_SCRIPT_ID", "").strip(),
        ns_file_reader_deploy_id=os.getenv("NS_FILE_READER_DEPLOY_ID", "").strip(),
        ns_search_reader_script_id=os.getenv("NS_SEARCH_READER_SCRIPT_ID", "").strip(),
        ns_search_reader_deploy_id=os.getenv("NS_SEARCH_READER_DEPLOY_ID", "").strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
