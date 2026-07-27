# NJR Konwerter

Open-source konwerter / edytor bibliotek DJ: **VirtualDJ ↔ Serato ↔ Engine DJ ↔ Rekordbox**.

Aktualnie projekt działa **bez blokad licencyjnych** — pełny eksport jest dostępny od razu.

## Szybki start (dev)

```bash
cd editor
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python launcher.py
```

## Build lokalny

```bash
chmod +x scripts/build-local.sh
./scripts/build-local.sh
```

## Najważniejsze katalogi

| Element | Opis |
|---|---|
| `editor/` | Backend Flask + frontend + eksporty |
| `scripts/` | Skrypty build/deploy |
| `releases/` | Artefakty build (nie commitować binarek) |
| `VERSION` | Wersja |
| `CHANGELOG.md` | Historia zmian |

## Licencja

Projekt jest udostępniany na licencji [MIT](LICENSE).
