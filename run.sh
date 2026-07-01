#!/usr/bin/env bash
# VegeLink launcher — zero dependencies, Python 3 stdlib only.
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-8000}"

if [ "$1" = "test" ]; then
  exec python3 -m unittest discover -s tests -v
fi

if [ "$1" = "--reset" ]; then
  python3 seed.py
fi

echo "Starting VegeLink on http://localhost:$PORT"
PORT="$PORT" python3 server.py
