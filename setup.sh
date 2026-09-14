#!/usr/bin/env bash
# Create a local venv and install the one build dependency (markdown).
# Keeps everything self-contained; does not touch system Python.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet "markdown>=3.5,<4"
echo "Setup complete. Build with:  ./.venv/bin/python build.py"
