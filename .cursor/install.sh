#!/usr/bin/env bash
# Idempotent bootstrap for the NJR Konwerter Flask app.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EDITOR_DIR="$REPO_ROOT/editor"
VENV_DIR="$EDITOR_DIR/.venv"

# The default base image ships Python 3 but not the venv/ensurepip module.
# Install it only when it is missing so the step stays idempotent and fast.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends python3-venv
fi

cd "$EDITOR_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt

python launcher.py --smoke-test
