#!/bin/bash
# Copy the shared helpers in _lib/ into every skill that uses them.
#
# Each skill must stay a self-contained directory (Agent Skills spec), so the
# helpers are vendored as real files, never symlinked. _lib/ is the single
# source: edit there, then run this script.
#
# Usage:  ./sync-lib.sh           # write the copies
#         ./sync-lib.sh --check   # exit 1 if any copy differs (CI / pack-skill.sh)

set -euo pipefail

cd "$(dirname "$0")"

CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

# "<source in _lib> <destination>" — the dub skill keeps its own _common.py
# (run manifest) and imports the shared one as _core.
TARGETS=(
  "_http.py image-creator/scripts/_http.py"
  "_common.py image-creator/scripts/_common.py"
  "_http.py image-resize/scripts/_http.py"
  "_common.py image-resize/scripts/_common.py"
  "_http.py image-translation/scripts/_http.py"
  "_common.py image-translation/scripts/_common.py"
  "_http.py video-dubbing/scripts/_http.py"
  "_common.py video-dubbing/scripts/_core.py"
  "_tm.py image-translation/scripts/_tm.py"
  "_tm.py video-dubbing/scripts/_tm.py"
)

DRIFT=0
for pair in "${TARGETS[@]}"; do
  read -r SRC DEST <<<"${pair}"
  if [ "${CHECK}" -eq 1 ]; then
    if [ -L "${DEST}" ] || ! cmp -s "_lib/${SRC}" "${DEST}"; then
      echo "out of sync: ${DEST} (run ./sync-lib.sh)" >&2
      DRIFT=1
    fi
  else
    rm -f "${DEST}"
    cp "_lib/${SRC}" "${DEST}"
  fi
done

if [ "${CHECK}" -eq 1 ] && [ "${DRIFT}" -ne 0 ]; then
  exit 1
fi
[ "${CHECK}" -eq 1 ] && echo "shared helpers in sync" || echo "synced ${#TARGETS[@]} files from _lib/"
