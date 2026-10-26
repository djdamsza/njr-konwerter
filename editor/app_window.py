"""Własne okno buildu. Serwer zostaje na tym komputerze, karty przeglądarki nie ma."""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import webbrowser
from pathlib import Path


def use_own_window() -> bool:
    """Build otwiera okno. Z kodu w Cursorze zostaje przeglądarka, chyba że NJR_WINDOW=1."""
    if os.environ.get("NJR_NO_BROWSER", "").strip().lower() in ("1", "true", "yes", "on"):
        return False
    forced = os.environ.get("NJR_WINDOW", "").strip().lower()
    if forced in ("1", "true", "yes", "on"):
        return True
    if forced in ("0", "false", "no", "off"):
        return False
    return bool(getattr(sys, "frozen", False))


class WindowApi:
    """Zapis plików i linki na zewnątrz. Okno nie umie tego samo."""

    def __init__(self) -> None:
        self._handle = None
        self._path: Path | None = None

    def clipboard_read(self) -> str:
        if sys.platform == "darwin":
            out = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
            return out.stdout or ""
        if sys.platform.startswith("win"):
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                check=False,
            )
            return out.stdout or ""
        return ""

    def clipboard_write(self, text: str) -> bool:
        data = "" if text is None else str(text)
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=data, text=True, check=False)
            return True
        if sys.platform.startswith("win"):
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ([Console]::In.ReadToEnd())"],
                input=data,
                text=True,
                check=False,
            )
            return True
        return False

    def open_external(self, url: str) -> bool:
        address = str(url or "").strip()
        if not (address.startswith("https://") or address.startswith("http://")):
            return False
        webbrowser.open(address)
        return True

    def begin_save(self, filename: str) -> str:
        self.finish_save()
        folder = Path.home() / "Downloads"
        folder.mkdir(parents=True, exist_ok=True)
        name = Path(str(filename or "plik")).name.replace("\x00", "").strip() or "plik"
        path = folder / name
        stem, suffix = path.stem, path.suffix
        number = 2
        while path.exists():
            path = folder / f"{stem}-{number}{suffix}"
            number += 1
        self._handle = path.open("wb")
        self._path = path
        return str(path)

    def write_chunk(self, payload: str) -> int:
        if self._handle is None:
            return 0
        raw = base64.b64decode(payload or "", validate=False)
        self._handle.write(raw)
        return len(raw)

    def finish_save(self) -> str:
        path = self._path
        if self._handle is not None:
            self._handle.close()
        self._handle = None
        self._path = None
        if path is None:
            return ""
        _reveal(path)
        return str(path)


def _reveal(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=False)
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", str(path)], check=False)
    except OSError:
        pass


def open_window(url: str) -> None:
    import webview

    api = WindowApi()
    if hasattr(webview, "settings"):
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(
        "Imprezja Playlist Pro",
        url,
        js_api=api,
        width=1440,
        height=900,
        min_size=(1024, 700),
        text_select=True,
    )
    webview.start()
