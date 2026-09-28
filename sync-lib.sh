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

# What each skill vendors from _lib/. Every skill is a thin guide over the
# Vitra server's tools: it signs in with login.py and calls tools with vitra.py,
# and keeps no API logic of its own.
BASE="_http.py _common.py login.py vitra.py"

SKILL_FILES=(
  "brand-kit|${BASE}"
  "compliance-markets|${BASE}"
  "content-compliance|${BASE}"
  "design-file-translation|${BASE}"
  "dita-translation|${BASE}"
  "document-translation|${BASE}"
  "drive|${BASE}"
  "hyperlocal-campaigns|${BASE}"
  "hyperlocal-contacts|${BASE}"
  "hyperlocal-templates|${BASE}"
  "image-creator|${BASE}"
  "image-resize|${BASE}"
  "image-translation|${BASE}"
  "lip-sync|${BASE}"
  "org-knowledge|${BASE}"
  "projects|${BASE}"
  "prompts-library|${BASE}"
  "terminology|${BASE}"
  "text-to-speech|${BASE}"
  "translate-video|${BASE}"
  "translation-memory|${BASE}"
  "translation-quality|${BASE}"
  "vitra|${BASE}"
  "voice-cloning|${BASE}"
  "workflows|${BASE}"
)

# (bash 3.2 on macOS has no associative arrays: "skill|files" pairs.)
TARGETS=()
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
