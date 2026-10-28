#!/bin/sh
# Copy the Django backend + uv into src-tauri/backend-stage/, which is bundled into the app's Resources.
set -e
cd "$(dirname "$0")/.."
STAGE=src-tauri/backend-stage
rm -rf "$STAGE" && mkdir -p "$STAGE/bin"
rsync -a --exclude '.venv' --exclude '.data' --exclude '__pycache__' --exclude '*.pyc' --exclude 'tests.py' backend/ "$STAGE/backend/"
UV=${UV_BIN:-$(command -v uv || echo "$HOME/.local/bin/uv")}
cp "$UV" "$STAGE/bin/uv"
chmod +x "$STAGE/bin/uv"
echo "Staged backend + $("$STAGE/bin/uv" --version)"
