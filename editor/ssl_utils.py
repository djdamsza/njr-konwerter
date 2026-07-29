"""
HTTPS helpers for PyInstaller onefile builds.

Bundled apps often lack system CA certificates; urllib then fails with
CERTIFICATE_VERIFY_FAILED and Tidal checks falsely report every track as unavailable.
"""
from __future__ import annotations

import os
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Optional


def _certifi_cafile() -> Optional[str]:
    try:
        import certifi

        path = certifi.where()
        if os.path.isfile(path):
            return path
    except ImportError:
        pass

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        for candidate in (
            Path(meipass) / "certifi" / "cacert.pem",
            Path(meipass) / "cacert.pem",
        ):
            if candidate.is_file():
                return str(candidate)
    return None


def ssl_context() -> ssl.SSLContext:
    cafile = _certifi_cafile()
    if cafile:
        return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def configure_ssl_env() -> None:
    """Set CA bundle env vars before any HTTPS (urllib, requests, etc.)."""
    cafile = _certifi_cafile()
    if cafile:
        os.environ.setdefault("SSL_CERT_FILE", cafile)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", cafile)


def urlopen(req, timeout: float = 10, context: Optional[ssl.SSLContext] = None):
    if context is None:
        context = ssl_context()
    return urllib.request.urlopen(req, timeout=timeout, context=context)
