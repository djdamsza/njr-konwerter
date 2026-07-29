#!/usr/bin/env bash
# Usuwa z GitHub Release assety starsze niż KEEP_VERSIONS ostatnich wersji semver.
# Użycie: ./scripts/prune-github-release-assets.sh [TAG] [KEEP]
#   TAG  — tag release (domyślnie 1.0)
#   KEEP — ile ostatnich wersji zostawić (domyślnie 2)
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-djdamsza/njr-konwerter}"
TAG="${1:-1.0}"
KEEP="${2:-2}"

if ! command -v gh >/dev/null 2>&1; then
  echo "Wymagane: gh CLI" >&2
  exit 1
fi

python3 - "$REPO" "$TAG" "$KEEP" <<'PY'
import json, re, subprocess, sys

repo, tag, keep = sys.argv[1:4]
keep = int(keep)

raw = subprocess.check_output(
    ["gh", "release", "view", tag, "--repo", repo, "--json", "assets"],
    text=True,
)
assets = json.loads(raw)["assets"]
pat = re.compile(r"NJR-konwerter-(\d+\.\d+\.\d+)-")

by_ver: dict[str, list[dict]] = {}
for a in assets:
    m = pat.search(a["name"])
    if not m:
        continue
    by_ver.setdefault(m.group(1), []).append(a)

def ver_key(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))

versions = sorted(by_ver.keys(), key=ver_key, reverse=True)
drop = versions[keep:]
print(f"Wersje na release {tag}: {', '.join(versions)}")
print(f"Zostawiam: {versions[:keep]}")
print(f"Usuwam assety wersji: {drop or '(brak)'}")

for v in drop:
    for a in by_ver[v]:
        print(f"  delete {a['name']} ({a['id']})")
        subprocess.run(
            ["gh", "api", "-X", "DELETE", f"/repos/{repo}/releases/assets/{a['id']}"],
            check=True,
        )
PY

echo "Gotowe."
