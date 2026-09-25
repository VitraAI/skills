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

# What each skill vendors from _lib/. The dub skill keeps its own _common.py
# (run manifest) and imports the shared one as _core (see RENAMES).
BASE="_http.py _common.py _access.py"
VIDEO="_tm.py _tv.py _jobs.py _progress.py _cards.py _cue.py list_languages.py list_tms.py list_providers.py"
SUBTITLES="start_subtitles.py inspect_subtitles.py edit_subtitles.py add_subtitle_language.py download_subtitles.py retry_subtitles.py translate_subtitles.py"

SKILL_FILES=(
  "image-creator|${BASE}"
  "image-resize|${BASE}"
  "image-translation|${BASE} _tm.py list_tms.py list_providers.py"
  "video-dubbing|_http.py _access.py ${VIDEO} download_export.py edit_subtitles.py"
  "video-subtitles|${BASE} ${VIDEO} ${SUBTITLES} burn_subtitles.py download_export.py"
  "subtitle-translation|${BASE} ${VIDEO} ${SUBTITLES}"
  "document-translation|${BASE} _tm.py _state.py list_tms.py list_providers.py"
  "text-to-speech|${BASE} _state.py list_voices.py list_languages.py"
  "voice-cloning|${BASE} _state.py list_languages.py"
  "lip-sync|${BASE} _state.py list_languages.py"
  "translation-memory|${BASE} _tm.py list_tms.py list_providers.py"
  "content-compliance|${BASE}"
  "translation-quality|${BASE} _tm.py list_tms.py"
  "hyperlocal-campaigns|${BASE} _state.py"
  "workflows|${BASE} _state.py"
)
RENAMES=("_common.py video-dubbing/scripts/_core.py")

# (bash 3.2 on macOS has no associative arrays: "skill|files" pairs.)
TARGETS=("${RENAMES[@]}")
for entry in "${SKILL_FILES[@]}"; do
  skill="${entry%%|*}"
  for f in ${entry#*|}; do
    TARGETS+=("${f} ${skill}/scripts/${f}")
  done
done

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
