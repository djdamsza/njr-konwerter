#!/usr/bin/env python3
"""
Test end-to-end aktualizacji NJR:
  - sprawdza GitHub (baseline 1.0.0 → oczekuje nowszej, np. 1.0.3)
  - pobiera asset dla bieżącej platformy
  - instaluje do katalogu tymczasowego (bez /Applications, bez relaunch)

Uruchomienie:
  cd editor && python3 test_updater.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# editor/ na sys.path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import updater  # noqa: E402


def main() -> int:
    print("=== NJR updater test ===")
    print(f"platform: {sys.platform} / {updater.platform.machine()}")
    suffix = updater.platform_asset_suffix()
    print(f"asset suffix: {suffix}")

    # 1) Find update newer than 1.0.0
    baseline = os.environ.get("NJR_TEST_BASELINE", "1.0.0").strip() or "1.0.0"
    print(f"\n[1] Szukam nowszej wersji niż {baseline}…")
    asset = updater.find_latest_asset(baseline, suffix=suffix)
    if not asset:
        print("FAIL: nie znaleziono nowszego assetu na GitHub")
        return 1
    print(f"OK: {asset['name']} ({asset['version']}) size={asset['size']}")
    assert asset["url"], "brak download URL"

    # 2) Download (sync via start_download + poll)
    print("\n[2] Pobieranie…")
    updater.start_download(asset["url"], asset["version"], asset["name"])
    deadline = time.time() + 600
    path = ""
    while time.time() < deadline:
        st = updater.get_status()
        if st["status"] == "ready" and st.get("path"):
            path = st["path"]
            print(f"OK: pobrano {path} ({st.get('progress')}%)")
            break
        if st["status"] == "error":
            print(f"FAIL: {st.get('error') or st.get('message')}")
            return 1
        print(f"  … {st.get('status')} {st.get('progress', 0)}%")
        time.sleep(2)
    else:
        print("FAIL: timeout pobierania")
        return 1

    pkg = Path(path)
    if not pkg.is_file() or pkg.stat().st_size < 1000:
        print(f"FAIL: plik za mały lub brak: {pkg}")
        return 1
    print(f"  rozmiar: {pkg.stat().st_size} bajtów")

    # 3) Install to temp dir (no relaunch, no /Applications)
    print("\n[3] Instalacja do katalogu testowego…")
    with tempfile.TemporaryDirectory(prefix="njr-update-test-") as td:
        if suffix.endswith(".dmg"):
            target = Path(td) / "NJR-konwerter"
        else:
            target = Path(td) / "NJR-konwerter.exe"
        result = updater.install_update(
            package_path=str(pkg),
            target_path=str(target),
            relaunch=False,
        )
        print(f"  result: {result}")
        if not result.get("ok"):
            print(f"FAIL: {result.get('error')}")
            return 1
        installed = Path(result["installedPath"])
        if not installed.is_file():
            print(f"FAIL: brak pliku po instalacji: {installed}")
            return 1
        size = installed.stat().st_size
        print(f"OK: zainstalowano {installed} ({size} bajtów)")
        if size < 1000:
            print("FAIL: zainstalowany plik za mały")
            return 1
        if sys.platform == "darwin" and not os.access(installed, os.X_OK):
            print("FAIL: brak bitów wykonywalnych")
            return 1

    # 4) check_for_updates z aktualną wersją powinno zwrócić available=False
    print("\n[4] check_for_updates przy wersji assetu (oczekiwane: brak nowszej)…")
    # chwilowo wyczyść force baseline
    os.environ.pop("NJR_FORCE_UPDATE_BASELINE", None)
    r = updater.check_for_updates(asset["version"])
    if r.get("available"):
        print(f"UWAGA: available=True mimo wersji {asset['version']}: {r}")
        # nie fail — może być nowsza na GitHub
    else:
        print(f"OK: {r.get('message')}")

    print("\n=== ALL PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
