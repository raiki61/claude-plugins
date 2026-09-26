#!/bin/sh
cd "$(dirname "$0")/.." && PYTHONDONTWRITEBYTECODE=1 exec uv run --no-project --with pyyaml python3 -m unittest discover -s tests -p 'test_*.py' "$@"
