"""
PyInstaller runtime hook — ustaw certyfikaty CA zanim załadują się moduły HTTPS.
"""
import os
import sys
from pathlib import Path


def _bootstrap_certifi() -> None:
    cafile = None
    try:
        import certifi

        cafile = certifi.where()
        if not os.path.isfile(cafile):
            cafile = None
    except ImportError:
        cafile = None

    if not cafile and getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        for candidate in (
            Path(meipass) / "certifi" / "cacert.pem",
            Path(meipass) / "cacert.pem",
        ):
            if candidate.is_file():
                cafile = str(candidate)
                break

    if cafile:
        os.environ["SSL_CERT_FILE"] = cafile
        os.environ["REQUESTS_CA_BUNDLE"] = cafile


_bootstrap_certifi()
