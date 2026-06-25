#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_MANAGER="$("$ROOT_DIR/scripts/package-manager.sh")"

python3 -m pip install -r "$ROOT_DIR/backend/requirements.txt"

cd "$ROOT_DIR/frontend"
"$PKG_MANAGER" install --legacy-peer-deps
