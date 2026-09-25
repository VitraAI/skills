#!/bin/bash
# Pack a skill folder in this directory into a distributable zip, excluding
# build artifacts and secrets. The zip is what a partner agent runtime consumes
# (unzip into its skills directory).
#
# Usage:  ./pack-skill.sh <skill-name>
# Example: ./pack-skill.sh video-dubbing

set -euo pipefail

cd "$(dirname "$0")"

SKILL_NAME="${1:-}"
if [ -z "${SKILL_NAME}" ]; then
  echo "Usage: $0 <skill-name>" >&2
  exit 2
fi

BUILDS_DIR=".builds"
OUTPUT_FILE="${BUILDS_DIR}/${SKILL_NAME}.zip"

if [ ! -d "${SKILL_NAME}" ]; then
  echo "Error: ${SKILL_NAME}/ not found in $(pwd)" >&2
  exit 1
fi

# Shared helpers are vendored from _lib/; refuse to ship a stale copy.
./sync-lib.sh --check

mkdir -p "${BUILDS_DIR}"
rm -f "${OUTPUT_FILE}"

# listing.yaml is the Skill Library page copy (webapp), not part of the skill.
zip -r "${OUTPUT_FILE}" "${SKILL_NAME}" \
  -x \
  "${SKILL_NAME}/.DS_Store" \
  "${SKILL_NAME}/**/.DS_Store" \
  "${SKILL_NAME}/__pycache__/*" \
  "${SKILL_NAME}/**/__pycache__/*" \
  "${SKILL_NAME}/*.pyc" \
  "${SKILL_NAME}/**/*.pyc" \
  "${SKILL_NAME}/.env" \
  "${SKILL_NAME}/.env.local" \
  "${SKILL_NAME}/**/.env" \
  "${SKILL_NAME}/**/.env.local" \
  "${SKILL_NAME}/listing.yaml"

SIZE=$(du -h "${OUTPUT_FILE}" | cut -f1)
echo "packed -> ${OUTPUT_FILE} (${SIZE})"

# Fail loudly if anything sensitive or noisy slipped in.
if unzip -l "${OUTPUT_FILE}" | grep -E "/\.env($|[^.])|__pycache__|\.pyc|\.DS_Store" >/dev/null; then
  echo "ERROR: packed zip contains excluded files" >&2
  unzip -l "${OUTPUT_FILE}" | grep -E "/\.env($|[^.])|__pycache__|\.pyc|\.DS_Store" >&2
  exit 1
fi
