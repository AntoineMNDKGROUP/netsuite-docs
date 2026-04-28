"""Client pour télécharger des fichiers du File Cabinet NetSuite.

Stratégie : la RESTlet `file_reader_restlet.js` qu'on a déployée dans NetSuite.
Voir extractor/netsuite/DEPLOY_RESTLET.md pour la procédure.

L'endpoint :
  GET /app/site/hosting/restlet.nl?script={SCRIPT_ID}&deploy={DEPLOY_ID}&id={fileId}

Réponse JSON :
  { id, name, fileType, size, encoding, folder, description, url, isText, content }
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from .auth import build_oauth
from .config import Settings

logger = logging.getLogger(__name__)


class FileCabinetClient:
    DEFAULT_TIMEOUT = 60

    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.ns_file_reader_script_id or not settings.ns_file_reader_deploy_id:
            raise RuntimeError(
                "RESTlet file_reader non configurée. "
                "Voir extractor/netsuite/DEPLOY_RESTLET.md et ajouter "
                "NS_FILE_READER_SCRIPT_ID + NS_FILE_READER_DEPLOY_ID dans .env"
            )
        self.auth = build_oauth(settings)
        # ⚠️ Les RESTlets utilisent un domaine séparé : restlets.api.netsuite.com
        # (et non suitetalk.api.netsuite.com qui sert pour SuiteQL/Record Service).
        self.restlet_url = (
            f"{settings.ns_restlet_base_url}/app/site/hosting/restlet.nl"
        )
        self.session = requests.Session()

    def fetch_file(self, file_id: str | int) -> dict[str, Any]:
        """Appelle la RESTlet et retourne le JSON parsé.

        Sur ce compte NetSuite, le RESTlet renvoie `JSON.stringify(obj)` ;
        NetSuite enveloppe ça en JSON, donc on reçoit soit :
        - directement un dict (si NetSuite a bien décodé)
        - une string JSON (qu'il faut re-parser)
        On gère les deux cas.
        """
        import json
        params = {
            "script": self.settings.ns_file_reader_script_id,
            "deploy": self.settings.ns_file_reader_deploy_id,
            "id": str(file_id),
        }
        resp = self.session.get(
            self.restlet_url,
            params=params,
            auth=self.auth,
            headers={"Accept": "application/json"},
            timeout=self.DEFAULT_TIMEOUT,
        )
        if resp.status_code >= 400:
            body = (resp.text or "")[:500]
            raise RuntimeError(f"RESTlet file/{file_id} HTTP {resp.status_code}: {body}")

        # 1er parse
        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(f"RESTlet file/{file_id} non-JSON: {resp.text[:200]}")

        # Si data est une string, c'est notre JSON.stringify → on re-parse
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception as e:
                raise RuntimeError(f"RESTlet file/{file_id} invalid inner JSON: {e}; got {data[:200]}")

        if not isinstance(data, dict):
            raise RuntimeError(f"RESTlet file/{file_id} unexpected payload type: {type(data).__name__}")

        return data

    def download_content(self, file_id: str | int) -> tuple[bytes, dict[str, Any]]:
        """Compatibilité avec l'ancienne API : renvoie (bytes, metadata).

        La RESTlet renvoie le contenu en string déjà décodé. On reconverti en bytes
        pour que l'appelant calcule le SHA256 sur les bytes.
        """
        data = self.fetch_file(file_id)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"RESTlet error: {data['error']}")

        content_str = data.get("content") or ""
        # Encode en UTF-8 pour avoir des bytes (le SHA sera calculé sur bytes)
        content_bytes = content_str.encode("utf-8")

        return content_bytes, data
