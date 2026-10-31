#!/bin/sh
# One backup: PostgreSQL dump + avatars and attachments, taken together so a restore
# keeps files and database records in sync. Used by the backup services in compose.yaml.
#   BACKUP_DIR (default /backups), BACKUP_KEEP_DAYS (default 14), PG* variables for pg_dump.
set -eu
dir="${BACKUP_DIR:-/backups}"
keep="${BACKUP_KEEP_DAYS:-14}"
stamp="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$dir"
# Write under a temporary name first: a half-written file is never mistaken for a backup.
pg_dump -Fc -f "$dir/.room_booking_$stamp.dump.part"
tar -czf "$dir/.room_booking_files_$stamp.tar.gz.part" -C /files uploads attachments
# A dump that pg_restore cannot read is a failed backup, not a backup.
pg_restore --list "$dir/.room_booking_$stamp.dump.part" > /dev/null
mv "$dir/.room_booking_$stamp.dump.part" "$dir/room_booking_$stamp.dump"
mv "$dir/.room_booking_files_$stamp.tar.gz.part" "$dir/room_booking_files_$stamp.tar.gz"
date -Iseconds > "$dir/LAST_SUCCESS"
find "$dir" -maxdepth 1 -name 'room_booking_*' -mtime +"$keep" -delete
echo "Backup $stamp done"
