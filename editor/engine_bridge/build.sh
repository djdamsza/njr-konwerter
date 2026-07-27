#!/usr/bin/env bash
# Buduje njr-engine-export (libdjinterop) — wymaga cmake 3.16+.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/editor/engine_bridge"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 4)"
echo "OK: $(find build -name 'njr-engine-export*' -type f 2>/dev/null | head -1)"
