"""Client pour interroger le RESTlet `saved_search_reader` déployé dans NetSuite.

Voir extractor/netsuite/DEPLOY_SAVED_SEARCH_RESTLET.md pour la procédure
de déploiement du RESTlet.

Endpoints exposés :
  - GET ?action=list&offset=N&limit=M  → liste paginée des SS
  - GET ?action=get&id=<id|scriptid>   → définition complète d'une SS
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .auth import build_oauth
from .config import Settings

logger = logging.getLogger(__name__)


class SavedSearchClient:
    """Wrapper léger autour du RESTlet `saved_search_reader`."""

    DEFAULT_TIMEOUT = 90  # search.load peut être lent sur les SS complexes

    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.ns_search_reader_script_id or not settings.ns_search_reader_deploy_id:
            raise RuntimeError(
                "RESTlet saved_search_reader non configurée. "
                "Voir extractor/netsuite/DEPLOY_SAVED_SEARCH_RESTLET.md et ajouter "
                "NS_SEARCH_READER_SCRIPT_ID + NS_SEARCH_READER_DEPLOY_ID dans .env"
            )
        self.auth = build_oauth(settings)
        # Les RESTlets utilisent le domaine restlets.api.netsuite.com (cf. file_cabinet.py).
        self.restlet_url = f"{settings.ns_restlet_base_url}/app/site/hosting/restlet.nl"
        self.session = requests.Session()

    # ----------------------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------------------

    def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        full_params = {
            "script": self.settings.ns_search_reader_script_id,
            "deploy": self.settings.ns_search_reader_deploy_id,
            **params,
        }
        resp = self.session.get(
            self.restlet_url,
            params=full_params,
            auth=self.auth,
            headers={"Accept": "application/json"},
            timeout=self.DEFAULT_TIMEOUT,
        )
        if resp.status_code >= 400:
            body = (resp.text or "")[:500]
            raise RuntimeError(
                f"saved_search_reader RESTlet HTTP {resp.status_code}: {body}"
            )

        # 1er parse
        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(
                f"saved_search_reader RESTlet non-JSON: {resp.text[:200]}"
            )

        # Si data est une string (NetSuite enveloppe parfois un JSON.stringify), re-parse
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception as e:
                raise RuntimeError(
                    f"saved_search_reader RESTlet inner JSON invalid: {e}; got {data[:200]}"
                )

        if not isinstance(data, dict):
            raise RuntimeError(
                f"saved_search_reader RESTlet unexpected type: {type(data).__name__}"
            )

        # Le RESTlet renvoie HTTP 200 mais peut signaler une erreur applicative
        # via le champ `error` — on lève proprement
        if data.get("error"):
            raise RuntimeError(
                f"saved_search_reader RESTlet error: {data.get('error')} "
                f"(action={data.get('action')})"
            )

        return data

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def list_page(self, offset: int = 0, limit: int = 1000) -> dict[str, Any]:
        """Récupère une page de saved searches.

        Returns:
            dict avec {total, offset, limit, returned, items: [...]}
        """
        return self._call({"action": "list", "offset": str(offset), "limit": str(limit)})

    def list_all(self) -> list[dict[str, Any]]:
        """Itère sur toutes les pages et retourne la liste complète des SS.

        Le RESTlet pagine en interne par 1000 et expose `total` = nb total. On
        ré-appelle jusqu'à avoir tout récupéré.
        """
        page_size = 1000
        offset = 0
        all_items: list[dict[str, Any]] = []
        while True:
            page = self.list_page(offset=offset, limit=page_size)
            items = page.get("items", []) or []
            all_items.extend(items)
            total = int(page.get("total", 0))
            offset += len(items)
            if not items or offset >= total:
                break
            # Garde-fou anti-boucle infinie
            if offset > 100000:
                logger.warning("list_all: garde-fou 100k atteint, arrêt forcé")
                break
        return all_items

    def get_definition(self, id_or_scriptid: str | int) -> dict[str, Any]:
        """Récupère la définition complète d'une saved search.

        Args:
            id_or_scriptid: l'internal ID (numérique) ou le scriptid (text, ex
                "customsearch_xxx").

        Returns:
            dict complet : {internalid, scriptid, title, recordtype, is_public,
            filter_expression, filters: [...], columns: [...]}
        """
        return self._call({"action": "get", "id": str(id_or_scriptid)})
