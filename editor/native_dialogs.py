"""Natywne okna dialogowe systemu (wybór folderu / pliku bazy)."""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional


def pick_folder_native() -> Optional[str]:
    """Otwiera natywne okno wyboru folderu. Zwraca ścieżkę lub None."""
    try:
        sys_name = platform.system()
        if sys_name == 'Darwin':
            r = subprocess.run(
                ['osascript', '-e', 'return POSIX path of (choose folder with prompt "Wybierz folder z muzyką")'],
                capture_output=True, text=True, timeout=60
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            return None
        if sys_name == 'Windows':
            r = subprocess.run(
                ['powershell', '-STA', '-NoProfile', '-Command',
                 'Add-Type -AssemblyName System.Windows.Forms; $f = New-Object System.Windows.Forms.FolderBrowserDialog; $f.Description = "Wybierz folder z muzyką"; $f.ShowNewFolderButton = $true; if ($f.ShowDialog() -eq "OK") { $f.SelectedPath }'],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            return None
        for cmd in [['zenity', '--file-selection', '--directory', '--title=Wybierz folder z muzyką'],
                    ['kdialog', '--getexistingdirectory', str(Path.home())]]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except FileNotFoundError:
                continue
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askdirectory(title='Wybierz folder z muzyką')
            root.destroy()
            return path if path else None
        except Exception:
            pass
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return None


def pick_open_path_native() -> Optional[str]:
    """Natywne okno: dowolny plik bazy (w tym Serato database V2 bez rozszerzenia)."""
    try:
        sys_name = platform.system()
        if sys_name == 'Darwin':
            r = subprocess.run(
                ['osascript', '-e',
                 'return POSIX path of (choose file with prompt "Otwórz bazę DJ. Serato: wystarczy jeden z trzech ZIP-ów master/root/tidal z tej samej kopii")'],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            return None
        if sys_name == 'Windows':
            r = subprocess.run(
                ['powershell', '-STA', '-NoProfile', '-Command',
                 'Add-Type -AssemblyName System.Windows.Forms; '
                 '$d = New-Object System.Windows.Forms.OpenFileDialog; '
                 '$d.Title = "Otworz baze DJ"; '
                 '$d.Filter = "Wszystkie pliki (*.*)|*.*|ZIP (*.zip)|*.zip|XML (*.xml)|*.xml"; '
                 '$d.FilterIndex = 1; '
                 'if ($d.ShowDialog() -eq "OK") { $d.FileName }'],
                capture_output=True, text=True, timeout=120
            )
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            return None
        for cmd in [
            ['zenity', '--file-selection', '--title=Otwórz bazę DJ'],
            ['kdialog', '--getopenfilename', str(Path.home())],
        ]:
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout.strip()
            except FileNotFoundError:
                continue
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            path = filedialog.askopenfilename(
                title='Otwórz bazę DJ',
                filetypes=[
                    ('Wszystkie pliki', '*.*'),
                    ('ZIP', '*.zip'),
                    ('XML', '*.xml'),
                ],
            )
            root.destroy()
            return path if path else None
        except Exception:
            pass
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return None
