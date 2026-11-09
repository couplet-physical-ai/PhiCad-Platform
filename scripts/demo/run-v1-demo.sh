#!/usr/bin/env bash
# Run the reproducible PhiCad V1 demo.  The Python harness owns the fresh run directory,
# command transcript, tool versions, structured outputs, diagnostics, and SHA-256 manifest.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" "$ROOT/scripts/demo/v1_demo.py" "$@"
