#!/usr/bin/env bash
# Interpreter for Raven CLIs. Skip Anaconda/conda (broken encodings on some Macs).
set -euo pipefail
try_py() {
  local c="$1"
  shift
  [[ -n "$c" && -x "$c" ]] || return 1
  case "$c" in *anaconda*|*miniconda*|*conda*) return 1 ;; esac
  "$c" -c "import encodings" 2>/dev/null || return 1
  exec "$c" "$@"
}
if [[ -n "${RAVEN_PYTHON:-}" ]]; then
  try_py "$RAVEN_PYTHON" "$@" || true
fi
for c in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  try_py "$c" "$@" || true
done
if command -v python3 >/dev/null 2>&1; then
  p="$(command -v python3)"
  try_py "$p" "$@" || true
fi
echo "raven-python.sh: no working python3 (refused Anaconda/conda)" >&2
exit 127
