#!/usr/bin/env bash
# Usuwa z GitHub Release assety starsze niż KEEP_VERSIONS ostatnich wersji semver.
# Użycie: ./scripts/prune-github-release-assets.sh [TAG] [KEEP]
#   TAG  — tag release (domyślnie 1.0)
#   KEEP — ile ostatnich wersji zostawić (domyślnie 2)
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-djdamsza/njr-konwerter}"
TAG="${1:-1.0}"
KEEP="${2:-2}"
TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}"

if [ -z "$TOKEN" ]; then
  echo "Brak GH_TOKEN / GITHUB_TOKEN — pomijam prune." >&2
  exit 0
fi

python3 - "$REPO" "$TAG" "$KEEP" "$TOKEN" <<'PY'
import json, re, sys, urllib.error, urllib.request

repo, tag, keep, token = sys.argv[1:5]
keep = int(keep)
pat = re.compile(r"NJR-konwerter-(\d+\.\d+\.\d+)-")

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "njr-konwerter-prune",
}

req = urllib.request.Request(
    f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
    headers=headers,
)
try:
    with urllib.request.urlopen(req, timeout=60) as resp:
        release = json.loads(resp.read().decode())
except urllib.error.HTTPError as e:
    print(f"Release {tag} niedostępny ({e.code}) — pomijam.", file=sys.stderr)
    sys.exit(0)

assets = release.get("assets") or []
by_ver: dict[str, list[dict]] = {}
for a in assets:
    m = pat.search(a.get("name") or "")
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
        aid = a["id"]
        name = a["name"]
        print(f"  delete {name} ({aid})")
        del_req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/assets/{aid}",
            method="DELETE",
            headers=headers,
        )
        with urllib.request.urlopen(del_req, timeout=60):
            pass
PY

echo "Gotowe."
