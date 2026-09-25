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
  "_access.py image-creator/scripts/_access.py"
  "_access.py image-resize/scripts/_access.py"
  "_access.py image-translation/scripts/_access.py"
  "_access.py video-dubbing/scripts/_access.py"
  "_jobs.py video-dubbing/scripts/_jobs.py"
  "_progress.py video-dubbing/scripts/_progress.py"
  "_cards.py video-dubbing/scripts/_cards.py"
  "_http.py video-subtitles/scripts/_http.py"
  "_common.py video-subtitles/scripts/_common.py"
  "_access.py video-subtitles/scripts/_access.py"
  "_tm.py video-subtitles/scripts/_tm.py"
  "_jobs.py video-subtitles/scripts/_jobs.py"
  "_progress.py video-subtitles/scripts/_progress.py"
  "_cards.py video-subtitles/scripts/_cards.py"
  "_tv.py video-subtitles/scripts/_tv.py"
  "_tv.py video-dubbing/scripts/_tv.py"
  "download_export.py video-dubbing/scripts/download_export.py"
  "download_export.py video-subtitles/scripts/download_export.py"
  "list_languages.py video-dubbing/scripts/list_languages.py"
  "list_languages.py video-subtitles/scripts/list_languages.py"
  "list_tms.py video-dubbing/scripts/list_tms.py"
  "list_tms.py video-subtitles/scripts/list_tms.py"
  "list_tms.py image-translation/scripts/list_tms.py"
  "list_providers.py video-dubbing/scripts/list_providers.py"
  "list_providers.py video-subtitles/scripts/list_providers.py"
  "list_providers.py image-translation/scripts/list_providers.py"
  "_cue.py video-dubbing/scripts/_cue.py"
  "_cue.py video-subtitles/scripts/_cue.py"
  "edit_subtitles.py video-dubbing/scripts/edit_subtitles.py"
  "edit_subtitles.py video-subtitles/scripts/edit_subtitles.py"
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
