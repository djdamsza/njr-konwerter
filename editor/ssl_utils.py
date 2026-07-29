"""
HTTPS helpers for PyInstaller onefile builds.

Bundled apps often lack system CA certificates; urllib then fails with
CERTIFICATE_VERIFY_FAILED and Tidal checks falsely report every track as unavailable.
"""
from __future__ import annotations

import os
import ssl
import urllib.request
from typing import Optional


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def configure_ssl_env() -> None:
    """Set CA bundle env vars before any HTTPS (urllib, requests, etc.)."""
    try:
        import certifi

        path = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", path)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", path)
    except ImportError:
        pass


def urlopen(req, timeout: float = 10, context: Optional[ssl.SSLContext] = None):
    if context is None:
        context = ssl_context()
    return urllib.request.urlopen(req, timeout=timeout, context=context)
