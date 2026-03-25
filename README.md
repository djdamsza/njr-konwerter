# NJR Konwerter 1.0

**Osobny projekt** — konwerter / edytor bazy VirtualDJ (Flask), eksporty (Serato, Rekordbox, DJXML itd.) i licencjonowanie eksportu. **Nie jest częścią Imprezja Quiz** ani innych gier quizowych; utrzymuj go w **dedykowanym repozytorium Git** (np. `njr-konwerter`).

## Układ repozytorium (docelowy)

W **korzeniu** osobnego repo powinny być m.in.:

| Element | Opis |
|---------|------|
| `editor/` | Pełne źródła aplikacji (PyInstaller `njr.spec`, `launcher.py`, `static/`, moduły Python). Zawartość odpowiada wcześniejszemu katalogowi `tools/vdj-database-editor` — **przenieś ją tutaj** przy wydzieleniu z innego monorepo. Patrz [`editor/README.md`](editor/README.md). |
| [`BUILD.md`](BUILD.md) | Budowanie binarki |
| [`DEPLOY-SERVER.md`](DEPLOY-SERVER.md) | Wgranie na serwer |
| [`GITHUB.md`](GITHUB.md) | Repozytorium GitHub, tagi, release |
| [`scripts/build-local.sh`](scripts/build-local.sh) | Build → `releases/` |
| [`scripts/deploy-to-server.example.sh`](scripts/deploy-to-server.example.sh) | Szablon `rsync` |
| `releases/` | Artefakty buildu (nie commituj binarek — `.gitignore`) |
| `VERSION` | Wersja semantyczna (np. `1.0.0`) |

## Szybki start

1. Upewnij się, że w `editor/` leży komplet plików źródłowych konwertera (w tym `njr.spec`).
2. Z korzenia **tego** repozytorium:

```bash
chmod +x scripts/build-local.sh
./scripts/build-local.sh
```

Opcjonalnie: `export NJR_APP_DIR="/ścieżka/do/katalogu-z-njr.spec"` jeśli źródła nie są w `editor/`.

## Prawa

Prawa autorskie i polityka dystrybucji według właściciela projektu NJR (binaria, klucze licencyjne — zob. moduły licencji w kodzie `editor/`).
