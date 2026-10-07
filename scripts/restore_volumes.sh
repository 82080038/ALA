#!/usr/bin/env bash
# Restore data runtime ALA dari backup yang dibuat backup_volumes.sh.
# PERINGATAN: menimpa isi volume yang ada. Jalankan saat stack DOWN.
#   ./scripts/restore_volumes.sh ala-data-backup-YYYYMMDD-HHMMSS.tar.gz
set -euo pipefail

IN="${1:?Usage: $0 <backup.tar.gz>}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

tar xzf "$IN" -C "$TMP"

for f in "$TMP"/*.tar.gz; do
  v="$(basename "$f" .tar.gz)"
  real="$(docker volume ls --format '{{.Name}}' | grep -E "(^|_)${v}$" | head -1 || true)"
  real="${real:-$v}"
  docker volume create "$real" >/dev/null
  echo "Restore ke volume $real …"
  docker run --rm -v "$real:/data" -v "$TMP:/backup" alpine \
    sh -c "rm -rf /data/* 2>/dev/null; tar xzf /backup/$(basename "$f") -C /data"
done

echo "Restore selesai. Jalankan: docker compose up -d"
