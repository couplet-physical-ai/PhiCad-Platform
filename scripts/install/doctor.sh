#!/bin/sh
# Read-only prerequisite and install-health wrapper.
set -eu
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    PYTHON=$(command -v python)
else
    echo "ERROR: Python 3.9+ is required (sudo is never used)." >&2
    exit 2
fi
exec "$PYTHON" "$SCRIPT_DIR/installer.py" doctor "$@"
