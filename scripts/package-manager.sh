#!/usr/bin/env bash

if command -v npm >/dev/null 2>&1; then
  echo "npm"
elif command -v pnpm >/dev/null 2>&1; then
  echo "pnpm"
else
  echo "No npm or pnpm executable found on PATH." >&2
  exit 1
fi
