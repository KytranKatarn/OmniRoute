#!/bin/sh
# Fetch the DB-IP ip-to-country-lite MMDB (free, CC-BY, no API key) into config/geoip/.
# Run on each nameserver node (and locally for validation). Schedule monthly via cron.
#   0 4 1 * *  /opt/archie-edge/geodns/fetch-geoip.sh
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)/config/geoip"
mkdir -p "$DIR"
DEST="$DIR/dbip-country-lite.mmdb"

# DB-IP publishes a fresh file each month: dbip-country-lite-YYYY-MM.mmdb.gz
YM="$(date +%Y-%m)"
URL="https://download.db-ip.com/free/dbip-country-lite-${YM}.mmdb.gz"

echo "Fetching $URL"
TMP="$(mktemp)"
# Fall back to last month near the 1st (the new file can lag a day).
if ! wget -qO "$TMP" "$URL"; then
  YM="$(date -d 'last month' +%Y-%m 2>/dev/null || date -v-1m +%Y-%m)"
  URL="https://download.db-ip.com/free/dbip-country-lite-${YM}.mmdb.gz"
  echo "Retry $URL"
  wget -qO "$TMP" "$URL"
fi

gunzip -c "$TMP" > "$DEST"
rm -f "$TMP"
echo "Wrote $DEST ($(wc -c < "$DEST") bytes, $YM)"
