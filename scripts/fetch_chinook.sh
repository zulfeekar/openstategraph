#!/usr/bin/env bash
# Fetches the Chinook sample database used by workflows/chinook-nl-to-sql.
#
# The file is committed, so this is only needed if it was removed or is being
# refreshed. Source: https://github.com/lerocha/chinook-database (MIT).
set -euo pipefail
DEST="$(cd "$(dirname "$0")/.." && pwd)/workflows/chinook-nl-to-sql/data"
mkdir -p "$DEST"
URL="https://github.com/lerocha/chinook-database/releases/download/v1.4.5/Chinook_Sqlite.sqlite"
curl -fsSL --max-time 120 -o "$DEST/Chinook_Sqlite.sqlite" "$URL"
echo "Chinook downloaded to $DEST"
sqlite3 "$DEST/Chinook_Sqlite.sqlite" "SELECT 'Track rows: ' || COUNT(*) FROM Track;"
