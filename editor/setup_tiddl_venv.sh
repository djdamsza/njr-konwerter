#!/usr/bin/env bash
# Bundled tiddl for Tidal → Serato (Python 3.12 + tiddl 2.8.0 + auth patch).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv-tiddl"

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "Wymagany Python 3.12 (brew install python@3.12)" >&2
  exit 1
fi

if [[ ! -d "$VENV" ]]; then
  python3.12 -m venv "$VENV"
fi

"$VENV/bin/pip" install -U pip
"$VENV/bin/pip" install 'tiddl==2.8.0'

AUTH="$VENV/lib/python3.12/site-packages/tiddl/models/auth.py"
if [[ -f "$AUTH" ]]; then
  python3 - <<PY
from pathlib import Path
p = Path("$AUTH")
text = p.read_text(encoding="utf-8")
if "facebookUid: int" in text:
    p.write_text(text.replace("facebookUid: int", "facebookUid: Optional[int] = None", 1), encoding="utf-8")
    print("Patch auth: facebookUid optional")
else:
    print("Patch auth: already applied")
PY
fi

echo "OK: $VENV/bin/tiddl"
echo "Login: $VENV/bin/tiddl auth login"
