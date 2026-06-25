#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_MANAGER="$("$ROOT_DIR/scripts/package-manager.sh")"
COMMAND="${1:-dev}"

cd "$ROOT_DIR/frontend"

case "$COMMAND" in
  dev)
    "$PKG_MANAGER" run dev -- --port 5173
    ;;
  build)
    "$PKG_MANAGER" run build
    ;;
  typecheck)
    "$PKG_MANAGER" run typecheck
    ;;
  *)
    echo "Unknown frontend command: $COMMAND" >&2
    exit 1
    ;;
esac
