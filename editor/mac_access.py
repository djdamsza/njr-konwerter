"""Prośba o dostęp do folderu biblioteki DJ na macOS."""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def offer_library_access(folder: Path, label: str) -> None:
    """Pokazuje okno: otwórz folder biblioteki albo ustawienia Pełnego dostępu do dysku."""
    if platform.system() != "Darwin":
        return
    if os.environ.get("NJR_NO_PRIVACY_PROMPT") == "1":
        return
    folder = Path(folder)
    safe_folder = str(folder).replace("\\", "\\\\").replace('"', '\\"')
    safe_label = label.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
set folderPath to "{safe_folder}"
set choice to button returned of (display dialog "NJR Konwerter nie może odczytać biblioteki {safe_label} w:" & return & folderPath & return & return & "Zamknij ten program DJ (Cmd+Q). Jeśli system nie zapytał o zgodę, włącz Pełny dostęp do dysku dla Terminala albo aplikacji, z której uruchamiasz NJR." buttons {{"Anuluj", "Otwórz folder", "Otwórz ustawienia"}} default button "Otwórz ustawienia" with title "Dostęp do biblioteki")
if choice is "Otwórz folder" then
  do shell script "open " & quoted form of folderPath
else if choice is "Otwórz ustawienia" then
  try
    do shell script "open \\"x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_AllFiles\\""
  on error
    do shell script "open \\"x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles\\""
  end try
end if
'''
    try:
        subprocess.run(
            ["osascript", "-"],
            input=script,
            text=True,
            timeout=180,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
