#!/bin/sh
# Local-only PhiCad Platform developer-preview installer.
# It deliberately does not download or execute a remote script.
set -eu

SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
    PYTHON=$(command -v python3)
elif command -v python >/dev/null 2>&1; then
    PYTHON=$(command -v python)
else
    echo "ERROR: Python 3.9+ is required; install it for your user account (sudo is never used)." >&2
    exit 2
fi

case "${1-}" in
    install|update|doctor|check|uninstall)
        command=$1
        shift
        ;;
    --check)
        command=check
        shift
        ;;
    --update)
        command=update
        shift
        ;;
    *)
        command=install
        ;;
esac

exec "$PYTHON" "$SCRIPT_DIR/scripts/install/installer.py" "$command" "$@"
