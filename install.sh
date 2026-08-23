#!/usr/bin/env bash
# One-command / double-click installer for GoDeskio/Clawd-Code.
# Never clones any repository except https://github.com/GoDeskio/Clawd-Code.git
set -euo pipefail

REPO="https://github.com/GoDeskio/Clawd-Code.git"
DEST="${CLAWD_INSTALL_DIR:-${HOME}/Jonathan/Clawd-Code}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<EOF
Install Clawd Code (GoDeskio/Clawd-Code) onto this machine.

Usage:
  ./install.sh
  ./install.sh --yes
  CLAWD_INSTALL_DIR=/custom/path ./install.sh

Default folder: ~/Jonathan/Clawd-Code
EOF
  exit 0
fi

pick_python() {
  local candidate
  for candidate in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

if ! PY="$(pick_python)"; then
  echo "Python 3.10+ is required. Install it from https://www.python.org/downloads/ and re-run ./install.sh" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"

EXTRA=()
if [[ -f "$HERE/src/cli.py" ]]; then
  EXTRA+=(--from-local "$HERE")
  echo "Using local tree at $HERE and saving it to $DEST"
else
  EXTRA+=(--clone)
  echo "Cloning $REPO into $DEST"
fi

if [[ -d "$DEST/src" && -f "$DEST/src/cli.py" ]]; then
  cd "$DEST"
  exec "$PY" -m src.install --source-dir "$DEST" --yes --skip-desktop-deps "$@"
fi

# Bootstrap enough of the tree to run the in-repo wizard.
if [[ ! -d "$DEST/.git" ]]; then
  if [[ -f "$HERE/src/cli.py" ]]; then
    mkdir -p "$DEST"
  else
    git clone --origin origin "$REPO" "$DEST"
  fi
fi

# Prefer the destination tree once it exists.
if [[ -f "$DEST/src/cli.py" ]]; then
  cd "$DEST"
  exec "$PY" -m src.install --source-dir "$DEST" --yes --skip-desktop-deps "$@"
fi

cd "$HERE"
exec "$PY" -m src.install --source-dir "$DEST" "${EXTRA[@]}" --yes --skip-desktop-deps "$@"
