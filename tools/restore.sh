#!/bin/sh
# Restore one backup made by tools/backup.sh into the database and file volumes.
#   docker compose --profile ops run --rm restore 20261028_030000
# Stop the backend first (docker compose stop backend): it must not write meanwhile.
set -eu
stamp="${1:?Pass the backup stamp, e.g. 20261028_030000}"
dir="${BACKUP_DIR:-/backups}"
dump="$dir/room_booking_$stamp.dump"; files="$dir/room_booking_files_$stamp.tar.gz"
[ -f "$dump" ] && [ -f "$files" ] || { echo "No complete backup $stamp in $dir"; exit 1; }
pg_restore --clean --if-exists --no-owner -d "$PGDATABASE" "$dump"
rm -rf /files/uploads/* /files/attachments/*
tar -xzf "$files" -C /files
echo "Restored $stamp. Start the backend again: docker compose start backend"
