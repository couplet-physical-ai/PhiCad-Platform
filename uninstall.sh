#!/bin/sh
# Remove only files named by the install manifest; never remove Phi config.
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    PYTHON=$(command -v python)
else
    echo "ERROR: Python 3.10+ is required to read the install manifest." >&2
    exit 2
fi

exec "$PYTHON" "$SCRIPT_DIR/scripts/install/installer.py" uninstall "$@"
