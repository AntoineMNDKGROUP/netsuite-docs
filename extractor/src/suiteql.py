"""Client SuiteQL pour NetSuite (REST API).

SuiteQL est un dialecte SQL exposé via REST. On l'utilise pour requêter
les tables système (script, customfield, systemnote, etc.).

Doc: https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_158099303499.html
"""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests

from .auth import build_oauth
from .config import Settings

logger = logging.getLogger(__name__)


class SuiteQLClient:
    def __init__(self, settings: Settings, page_size: int = 1000):
        self.settings = settings
        self.page_size = page_size
        self.auth = build_oauth(settings)
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Indispensable pour SuiteQL : NetSuite refuse sans ce header
            "Prefer": "transient",
        })

    def query(
        self,
        sql: str,
        *,
        max_pages: int | None = None,
        max_retries: int = 3,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Exécute une requête SuiteQL et yield les lignes (auto-pagination).

        Si `limit` est fourni, s'arrête après avoir yielded `limit` lignes.
        """
        offset = 0
        page = 0
        yielded = 0
        # Si on a un limit explicite, on adapte la taille de page pour ne pas tirer trop
        page_size = min(self.page_size, limit) if limit else self.page_size
        while True:
            url = f"{self.settings.suiteql_url}?limit={page_size}&offset={offset}"
            payload = {"q": sql}

            attempt = 0
            while True:
                attempt += 1
                try:
                    resp = self.session.post(url, json=payload, auth=self.auth, timeout=60)

                    # 4xx -> erreur côté client, on ne retry pas. On log le body pour debug.
                    if 400 <= resp.status_code < 500 and resp.status_code != 429:
                        body_excerpt = (resp.text or "")[:1500]
                        logger.error(
                            "NetSuite %s on %s — body: %s",
                            resp.status_code, url, body_excerpt,
                        )
                        resp.raise_for_status()

                    if resp.status_code == 429:
                        wait = min(2 ** attempt, 30)
                        logger.warning("Rate limited by NetSuite, sleeping %ss", wait)
                        time.sleep(wait)
                        continue
                    if resp.status_code >= 500:
                        if attempt >= max_retries:
                            body_excerpt = (resp.text or "")[:1500]
                            logger.error("NetSuite 5xx, body: %s", body_excerpt)
                            resp.raise_for_status()
                        wait = min(2 ** attempt, 30)
                        logger.warning(
                            "NetSuite returned %s, retry %s/%s in %ss",
                            resp.status_code, attempt, max_retries, wait,
                        )
                        time.sleep(wait)
                        continue
                    resp.raise_for_status()
                    break
                except requests.exceptions.HTTPError:
                    raise  # On a déjà loggé le body, pas de retry sur 4xx
                except requests.exceptions.RequestException as e:
                    if attempt >= max_retries:
                        raise
                    logger.warning("Network error %s, retry %s/%s", e, attempt, max_retries)
                    time.sleep(2 ** attempt)

            data = resp.json()
            items = data.get("items", [])
            for row in items:
                yield row
                yielded += 1
                if limit is not None and yielded >= limit:
                    return

            has_more = data.get("hasMore", False)
            offset += page_size
            page += 1

            if not has_more:
                break
            if max_pages is not None and page >= max_pages:
                logger.info("Reached max_pages=%s, stopping", max_pages)
                break

    def query_all(self, sql: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Variante qui retourne directement une liste (pratique pour les petits volumes)."""
        return list(self.query(sql, **kwargs))

    def ping(self) -> dict[str, Any]:
        """Test rapide de la connexion : sélectionne une ligne de la table script.

        On utilise BUILTIN.DF() qui est une fonction SuiteQL native, sur la table
        `script` qui existe toujours dans NetSuite. Si y a aucun script (improbable),
        la requête réussit quand même avec 0 lignes.
        """
        try:
            row = next(
                self.query("SELECT id, name FROM script WHERE rownum <= 1"),
                None,
            )
            return {"ok": True, "sample": row}
        except StopIteration:
            return {"ok": True, "sample": None}
