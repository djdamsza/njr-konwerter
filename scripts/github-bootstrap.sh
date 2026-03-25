#!/usr/bin/env bash
# Tworzy repozytorium na GitHubie, składa katalog (szablon NJR + editor z vdj-database-editor),
# robi pierwszy commit i push. Token: zmienna GITHUB_TOKEN lub bezpieczne wpisanie po uruchomieniu.
#
# Wymagania: git, curl, python3, rsync. Token: klasyczny PAT z zakresem „repo” (prywatne repo).
#
# Użycie:
#   ./scripts/github-bootstrap.sh
#   ./scripts/github-bootstrap.sh --name moj-njr --public
#   ./scripts/github-bootstrap.sh --org moja-firma --name njr-konwerter
#   GITHUB_TOKEN=ghp_... ./scripts/github-bootstrap.sh --name njr-konwerter
#   ./scripts/github-bootstrap.sh --vdj-dir /ścieżka/do/katalogu-z-njr.spec
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NJR_TEMPLATE="$(cd "$SCRIPT_DIR/.." && pwd)"
VOTEBATTLE_ROOT="$(cd "$NJR_TEMPLATE/.." && pwd)"
DEFAULT_VDJ="$VOTEBATTLE_ROOT/tools/vdj-database-editor"

REPO_NAME="njr-konwerter"
VISIBILITY="private"
ORG=""
VDJ_DIR=""
CLONE_TO=""
DRY_RUN=0

usage() {
  sed -n '1,20p' "$0" | tail -n +2
  echo "
Opcje:
  --name NAZWA       Nazwa repozytorium na GitHubie (domyślnie: njr-konwerter)
  --public           Repozytorium publiczne (domyślnie: prywatne)
  --org ORG          Utwórz w organizacji ORG (w przeciwnym razie na koncie zalogowanym tokenem)
  --vdj-dir ŚCIEŻKA  Źródła konwertera z njr.spec (domyślnie: ../tools/vdj-database-editor względem szablonu)
  --clone-to ŚCIEŻKA Po sukcesie skopiuj repo tutaj (masz gotowy katalog z .git — usuń .git jeśli chcesz tylko pliki)
  --dry-run          Tylko pokaż plan, bez API i bez pusha
  -h, --help         Ta pomoc
"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --name) REPO_NAME="$2"; shift 2 ;;
    --public) VISIBILITY="public"; shift ;;
    --org) ORG="$2"; shift 2 ;;
    --vdj-dir) VDJ_DIR="$2"; shift 2 ;;
    --clone-to) CLONE_TO="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Nieznana opcja: $1" >&2; usage; exit 1 ;;
  esac
done

if [ -z "$VDJ_DIR" ]; then
  VDJ_DIR="$DEFAULT_VDJ"
fi
if [ ! -d "$VDJ_DIR" ] || [ ! -f "$VDJ_DIR/njr.spec" ]; then
  echo "Brak katalogu ze źródłami lub njr.spec: $VDJ_DIR" >&2
  echo "Podaj --vdj-dir do katalogu z narzędziem (np. tools/vdj-database-editor)." >&2
  exit 1
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/njr-github-XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

copy_clone_to() {
  [ -z "$CLONE_TO" ] && return 0
  mkdir -p "$CLONE_TO"
  rsync -a "$WORK/" "$CLONE_TO/"
  echo "Skopiowano katalog roboczy (z .git) do: $CLONE_TO"
}

echo "Składam katalog roboczy w: $WORK"

rsync -a \
  --exclude '.git' \
  --exclude 'editor' \
  "$NJR_TEMPLATE/" "$WORK/"

mkdir -p "$WORK/editor"
rsync -a \
  --exclude '.git' \
  --exclude 'dist/' \
  --exclude 'build/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '*.pyc' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '*.egg-info/' \
  "$VDJ_DIR/" "$WORK/editor/"

if [ -f "$WORK/README.md" ]; then
  export _NJ_README_TRIM="$WORK/README.md"
  python3 <<'PY'
import pathlib, os
p = pathlib.Path(os.environ["_NJ_README_TRIM"])
t = p.read_text(encoding="utf-8")
marker = "\n---\n\n**Szablon w repozytorium Quiz (VoteBattle):**"
if marker in t:
    p.write_text(t.split(marker)[0].rstrip() + "\n", encoding="utf-8")
PY
  unset _NJ_README_TRIM
fi

chmod +x "$WORK/scripts/build-local.sh" "$WORK/scripts/deploy-to-server.example.sh" 2>/dev/null || true
chmod +x "$WORK/scripts/github-bootstrap.sh" 2>/dev/null || true

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[dry-run] Pomijam token, API i push."
  if [ -n "$ORG" ]; then
    echo "Plan repozytorium: $ORG/$REPO_NAME ($VISIBILITY)"
  else
    echo "Plan repozytorium: <login z tokenu>/$REPO_NAME ($VISIBILITY)"
  fi
  echo "Zawartość katalogu (pierwsze poziomy):"
  (cd "$WORK" && find . -maxdepth 2 -type d | sort | head -50)
  exit 0
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Wklej token GitHub (Personal Access Token) — znaki nie będą widoczne:"
  read -r -s GITHUB_TOKEN
  echo ""
fi
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "Brak tokenu. Ustaw GITHUB_TOKEN lub uruchom interaktywnie." >&2
  exit 1
fi

api_get() {
  curl -sS -f -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" "$@"
}

api_post_json() {
  local url="$1"
  local body="$2"
  curl -sS -f -X POST -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" -H "X-GitHub-Api-Version: 2022-11-28" -H "Content-Type: application/json" -d "$body" "$url"
}

TOKEN_USER="$(api_get https://api.github.com/user | python3 -c "import sys,json; print(json.load(sys.stdin)['login'])")"
OWNER="$TOKEN_USER"
if [ -n "$ORG" ]; then
  OWNER="$ORG"
fi

echo "Konto API (token): $TOKEN_USER"
echo "Repozytorium docelowe: $OWNER/$REPO_NAME ($VISIBILITY)"

if api_get "https://api.github.com/repos/$OWNER/$REPO_NAME" >/dev/null 2>&1; then
  echo "Repozytorium $OWNER/$REPO_NAME już istnieje — usuń je ręcznie lub wybierz inną --name." >&2
  exit 1
fi

export _NJ_GH_REPO_NAME="$REPO_NAME"
if [ "$VISIBILITY" = "public" ]; then
  export _NJ_GH_PRIVATE=0
else
  export _NJ_GH_PRIVATE=1
fi
BODY=$(python3 -c "import json, os; print(json.dumps({'name': os.environ['_NJ_GH_REPO_NAME'], 'private': os.environ['_NJ_GH_PRIVATE'] == '1', 'description': 'NJR Konwerter — VirtualDJ / eksporty', 'auto_init': False}))")
unset _NJ_GH_REPO_NAME _NJ_GH_PRIVATE

if [ -n "$ORG" ]; then
  CREATE_URL="https://api.github.com/orgs/$ORG/repos"
else
  CREATE_URL="https://api.github.com/user/repos"
fi

echo "Tworzę repozytorium na GitHubie..."
RESP="$(api_post_json "$CREATE_URL" "$BODY")" || {
  echo "Nie udało się utworzyć repozytorium (sprawdź token, zakres „repo”, uprawnienia do org)." >&2
  exit 1
}

CLONE_URL="$(printf '%s' "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['clone_url'])")"
# https://github.com/owner/repo.git
AUTH_URL="$(printf '%s' "$CLONE_URL" | sed "s#https://#https://x-access-token:${GITHUB_TOKEN}@#")"

echo "Inicjalizacja git i pierwszy push..."
git -C "$WORK" init -b main
git -C "$WORK" add -A
git -C "$WORK" -c user.email="njr-bootstrap@local" -c user.name="NJR bootstrap" commit -m "NJR Konwerter — początek repozytorium (automatyczny import)"

git -C "$WORK" remote add origin "$AUTH_URL"
git -C "$WORK" push -u origin main

git -C "$WORK" remote set-url origin "$CLONE_URL"

copy_clone_to

echo ""
echo "Gotowe: $CLONE_URL"
if [ -z "$CLONE_TO" ]; then
  echo "Katalog tymczasowy zostanie usunięty — sklonuj repo u siebie:"
  echo "  git clone $CLONE_URL"
else
  echo "Dalsza praca: cd \"$CLONE_TO\" && git pull"
fi
echo ""
echo "Bezpieczeństwo: jeśli token wkleiłeś interaktywnie, rozważ unieważnienie go na GitHubie i utworzenie nowego tylko z zakresem „repo”."
echo "Nie commituj tokenu ani nie zapisuj go w plikach projektu."
