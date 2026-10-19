#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ "$#" -eq 0 ]; then
    python3 scripts/acquire.py
    set -- .demo/zlib-1.3.1
fi
exec python3 -m atlas "$@"
