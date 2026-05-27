#!/usr/bin/env bash
set -euo pipefail
# Run the remote_control package using the project's .venv Python so ONNX GPU
# providers are available. Sources the local ROS install if present.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f install/setup.bash ]; then
    # source ROS/workspace environment (non-fatal if missing)
    # shellcheck disable=SC1091
    source install/setup.bash || true
fi

if [ -x ".venv/bin/python" ]; then
    echo "Launching with .venv Python (.venv/bin/python)"
    exec .venv/bin/python -m remote_control.command_api "$@"
else
    echo ".venv Python not found or not executable — falling back to system python"
    exec python3 -m remote_control.command_api "$@"
fi
