#!/usr/bin/env bash
# Release a new add-on version: bumps config.yaml + APP_VERSION, prepends a
# changelog section, commits, tags and pushes.
#
#   ./release.sh patch "Fixed the add-item crash"
#   ./release.sh minor "Added barcode scanning"
#
set -euo pipefail
cd "$(dirname "$0")"

TYPE="${1:-}"
NOTE="${2:-}"
if [[ ! "$TYPE" =~ ^(patch|minor|major)$ ]] || [[ -z "$NOTE" ]]; then
  echo "usage: $0 patch|minor|major \"changelog line\"" >&2
  exit 1
fi

CFG="collect_and_go/config.yaml"
APP="collect_and_go/app/main.py"
LOG="collect_and_go/CHANGELOG.md"

CUR=$(grep -E '^version: ' "$CFG" | sed -E 's/version: "([^"]+)"/\1/')
IFS='.' read -r MA MI PA <<< "$CUR"
case "$TYPE" in
  patch) PA=$((PA+1));;
  minor) MI=$((MI+1)); PA=0;;
  major) MA=$((MA+1)); MI=0; PA=0;;
esac
NEW="$MA.$MI.$PA"
TODAY=$(date +%F)

sed -i -E "s/^version: \"$CUR\"$/version: \"$NEW\"/" "$CFG"
sed -i -E "s/^APP_VERSION = \"$CUR\"$/APP_VERSION = \"$NEW\"/" "$APP"

# Prepend a new section right below the header block of the changelog.
TMP=$(mktemp)
awk -v v="$NEW" -v d="$TODAY" -v n="$NOTE" '
  /^## \[/ && !done {
    print "## [" v "] — " d "\n\n### Changed\n\n- " n "\n"
    done=1
  }
  { print }
' "$LOG" > "$TMP" && mv "$TMP" "$LOG"

git add "$CFG" "$APP" "$LOG"
git commit -m "Release v$NEW: $NOTE"
git tag "v$NEW"
git push && git push --tags

echo "Released v$NEW"
