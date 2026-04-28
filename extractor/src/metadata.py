"""Client REST pour l'endpoint metadata-catalog de NetSuite.

Stratégie :
1. List endpoint en JSON léger (pas de swagger complet) pour énumérer les record types.
2. Pour chaque record, GET du swagger individuel (timeout long, response volumineuse).
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from .auth import build_oauth
from .config import Settings

logger = logging.getLogger(__name__)


class MetadataClient:
    # Catalog complet → très lourd à générer côté NetSuite. Pour individuel : ~quelques sec.
    LIST_TIMEOUT = 300
    DETAIL_TIMEOUT = 90

    def __init__(self, settings: Settings):
        self.settings = settings
        self.auth = build_oauth(settings)
        self.base_url = (
            f"{settings.ns_rest_base_url}/services/rest/record/v1/metadata-catalog"
        )
        self.session = requests.Session()

    def list_record_types(self) -> list[str]:
        """Liste les record types via le format JSON léger (pas le swagger complet).

        Le format JSON par défaut (sans Accept: swagger+json) renvoie la liste des records
        en quelques secondes. Le swagger complet, lui, peut prendre 5+ minutes côté NetSuite.
        """
        # On demande explicitement JSON, pas Swagger
        headers = {"Accept": "application/json"}
        logger.info("GET %s (timeout=%ss)", self.base_url, self.LIST_TIMEOUT)
        resp = self.session.get(
            self.base_url,
            auth=self.auth,
            headers=headers,
            timeout=self.LIST_TIMEOUT,
        )
        if resp.status_code >= 400:
            body = (resp.text or "")[:500]
            logger.error("metadata-catalog list failed %s: %s", resp.status_code, body)
            resp.raise_for_status()

        data = resp.json()

        # Format possible 1 : {"items": [{"name": "customer", ...}, ...]}
        if isinstance(data, dict) and "items" in data:
            return [item.get("name") for item in data["items"] if item.get("name")]

        # Format possible 2 : Swagger (definitions au top-level)
        if isinstance(data, dict) and "definitions" in data:
            return list(data["definitions"].keys())

        # Format possible 3 : liste directe
        if isinstance(data, list):
            return [item.get("name") for item in data if isinstance(item, dict) and item.get("name")]

        logger.warning("Unexpected metadata-catalog response shape: %s", type(data).__name__)
        return []

    def get_record_metadata(self, record_type: str) -> dict[str, Any]:
        """Renvoie la définition Swagger d'un record type spécifique."""
        url = f"{self.base_url}/{record_type}"
        headers = {"Accept": "application/swagger+json"}
        resp = self.session.get(
            url,
            auth=self.auth,
            headers=headers,
            timeout=self.DETAIL_TIMEOUT,
        )
        if resp.status_code >= 400:
            body = (resp.text or "")[:500]
            logger.error(
                "metadata-catalog/%s failed %s: %s",
                record_type, resp.status_code, body,
            )
            resp.raise_for_status()
        return resp.json()
