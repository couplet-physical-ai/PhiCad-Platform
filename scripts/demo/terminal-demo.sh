#!/usr/bin/env bash
# Stable, low-noise terminal sequence for a later GIF/video recording.
# Set PHICAD_ENGINE_CMD to a pinned local engine (or use the default resolver) and optionally set
# PHICAD_DEMO_RUN_DIR to a new, not-yet-existing directory for a predictable capture destination.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export CI=1
export NO_COLOR=1
export PYTHONHASHSEED=0

printf '\033[2J\033[H'
printf 'PHICAD\n'
printf 'V1 SMALL-BOARD / RESISTOR + LED\n'
printf '%s\n\n' 'capture sequence: source -> engine check -> build + PhiCad Verify'

args=()
if [[ -n "${PHICAD_DEMO_RUN_DIR:-}" ]]; then
  args+=(--run-dir "$PHICAD_DEMO_RUN_DIR")
fi
"${PYTHON:-python3}" "$ROOT/scripts/demo/v1_demo.py" "${args[@]}"
