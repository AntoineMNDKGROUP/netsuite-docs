"""OAuth 1.0 Token-Based Authentication pour NetSuite.

NetSuite exige HMAC-SHA256 (pas HMAC-SHA1 par défaut) et un realm header.
"""
from __future__ import annotations

from requests_oauthlib import OAuth1

from .config import Settings


def build_oauth(settings: Settings) -> OAuth1:
    """Construit un objet OAuth1 prêt à être passé en `auth=` à requests."""
    return OAuth1(
        client_key=settings.ns_consumer_key,
        client_secret=settings.ns_consumer_secret,
        resource_owner_key=settings.ns_token_id,
        resource_owner_secret=settings.ns_token_secret,
        signature_method="HMAC-SHA256",
        signature_type="auth_header",
        realm=settings.ns_realm,
    )
