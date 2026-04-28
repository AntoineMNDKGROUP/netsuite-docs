"""Client minimaliste pour l'API Anthropic (Messages API) avec rate limiting."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import requests

from .config import Settings

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"


class _RateLimiter:
    """Token bucket simple pour limiter le rythme de requêtes."""

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self.min_interval = 60.0 / self.rpm
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            sleep_for = self.min_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_call = time.monotonic()


class AnthropicClient:
    def __init__(self, settings: Settings, timeout: int = 90):
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY manquante dans .env")
        self.api_key = settings.anthropic_api_key
        self.model = settings.anthropic_model
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        # Rate limit configurable via env var (Free=5 RPM, Tier1=50, Tier2=1000+)
        rpm = int(os.getenv("ANTHROPIC_RPM", "5"))
        self.rate_limiter = _RateLimiter(rpm=rpm)
        logger.info("AnthropicClient: model=%s rate=%s rpm", self.model, rpm)

    def call(
        self,
        *,
        system: str,
        user_message: str,
        max_tokens: int = 1024,
        max_retries: int = 4,
    ) -> tuple[str, dict[str, Any]]:
        """Appelle l'API avec rate limit + retry sur 429/5xx. Renvoie (text, usage)."""
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_message}],
        }

        for attempt in range(1, max_retries + 1):
            self.rate_limiter.wait()
            try:
                resp = self.session.post(API_URL, json=payload, timeout=self.timeout)
            except requests.exceptions.RequestException as e:
                if attempt >= max_retries:
                    raise
                wait = min(2 ** attempt, 30)
                logger.warning("network err %s, retry %s/%s in %ss", e, attempt, max_retries, wait)
                time.sleep(wait)
                continue

            if resp.status_code == 429:
                # Respecte le retry-after si présent
                retry_after = int(resp.headers.get("retry-after", "0") or 0)
                wait = max(retry_after, min(2 ** attempt, 60))
                logger.warning("Anthropic 429 rate limit, sleep %ss (attempt %s/%s)",
                              wait, attempt, max_retries)
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                if attempt >= max_retries:
                    raise RuntimeError(f"Anthropic {resp.status_code}: {resp.text[:300]}")
                wait = min(2 ** attempt, 30)
                logger.warning("Anthropic %s, retry in %ss", resp.status_code, wait)
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                raise RuntimeError(f"Anthropic {resp.status_code}: {resp.text[:300]}")

            data = resp.json()
            try:
                text = data["content"][0]["text"]
            except Exception:
                raise RuntimeError(f"Réponse inattendue: {json.dumps(data)[:300]}")
            usage = data.get("usage", {})
            return text, usage

        raise RuntimeError(f"Anthropic: max retries {max_retries} dépassés")
