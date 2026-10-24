#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -z "${PAR2:-}" ]; then
    python3 scripts/bootstrap.py
fi
exec python3 -m desk.server "$@"
