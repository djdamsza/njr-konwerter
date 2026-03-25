# Repozytorium GitHub — NJR Konwerter

Konwerter NJR to **osobny produkt** — trzymaj go w **osobnym** repozytorium (np. `twoja-org/njr-konwerter`), bez mieszania z Imprezja Quiz ani innymi aplikacjami.

## Automatycznie: utworzenie repo + pierwszy push (token)

Ze struktury **VoteBattle** (szablon `njr-konwerter-1.0` obok `tools/vdj-database-editor`):

```bash
cd /ścieżka/do/VoteBattle/njr-konwerter-1.0
./scripts/github-bootstrap.sh
```

Skrypt:

1. Poprosi o **Personal Access Token** (wpis jest ukryty), chyba że ustawisz `GITHUB_TOKEN`.
2. Utworzy **prywatne** repozytorium `njr-konwerter` na Twoim koncie (lub `--name` / `--org` / `--public` — patrz `./scripts/github-bootstrap.sh --help`).
3. Złoży katalog: szablon + pełne źródła z `tools/vdj-database-editor` w `editor/`.
4. Zrobi `git commit` i `git push` na `main`.

**Token na GitHubie:** [Settings → Developer settings → Personal access tokens](https://github.com/settings/tokens) — klasyczny PAT z zakresem **repo** (wystarczy do prywatnego repo). Nie wklejaj tokenu do plików w repozytorium.

Przydatne opcje:

```bash
./scripts/github-bootstrap.sh --name moj-njr --clone-to "$HOME/Projects/moj-njr"
./scripts/github-bootstrap.sh --org moja-firma --name njr-konwerter
./scripts/github-bootstrap.sh --dry-run
```

## Utworzenie repo ręcznie

1. Na GitHubie: **New repository** (np. `njr-konwerter`), bez domyślnego README jeśli masz już lokalne pliki.
2. Lokalnie — struktura z [`README.md`](README.md): korzeń repo = `README.md`, `editor/`, `scripts/`, `VERSION`, itd.

```bash
cd /ścieżka/do/njr-konwerter
git init -b main
git add .
git commit -m "NJR Konwerter — początek repozytorium"
git remote add origin git@github.com:TWOJ_USER/njr-konwerter.git
git push -u origin main
```

## CI

Workflow: [`.github/workflows/verify.yml`](.github/workflows/verify.yml) — sprawdza obecność dokumentacji i uprawnienia skryptów (bez pełnego buildu PyInstaller).

## Release

1. `git tag -a v1.0.0 -m "NJR Konwerter 1.0"` → `git push origin v1.0.0`
2. **Releases → Create release** — dołącz binaria z `releases/` jako **assets** (samych dużych plików nie commituj do gałęzi — patrz `.gitignore`).

### Prywatne vs publiczne

Zwykle **prywatne**, jeśli kod i binaria są produktem komercyjnym.
