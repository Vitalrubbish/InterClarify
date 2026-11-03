#!/usr/bin/env bash
# Run one frozen formal arm through the shared bounded scheduler entry point.
set -euo pipefail
LANE="${NTF019_LANE:?set dual or single}"
[[ "$LANE" == dual || "$LANE" == single ]] || exit 2
export NTF_FRONTEND_GROUP="fdb-$LANE"
SCRIPT_ROOT="${BASH_SOURCE[0]%/*}"
exec bash "$SCRIPT_ROOT/run_native_frontend_probe.sh"
