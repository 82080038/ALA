#!/usr/bin/env bash
# Backup seluruh data runtime ALA (Postgres, Neo4j, ChromaDB) ke satu tar.gz.
# Gunakan untuk memindahkan state persis antar mesin pengembang.
#   ./scripts/backup_volumes.sh [output.tar.gz]
set -euo pipefail

OUT="${1:-ala-data-backup-$(date +%Y%m%d-%H%M%S).tar.gz}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

VOLUMES=(
  ala_postgres_data
  ala_neo4j_data
  ala_chroma_data
)

# Temukan nama volume aktual (compose memberi prefix nama proyek)
for v in "${VOLUMES[@]}"; do
  real="$(docker volume ls --format '{{.Name}}' | grep -E "(^|_)${v}$" | head -1 || true)"
  real="${real:-$v}"
  if ! docker volume inspect "$real" >/dev/null 2>&1; then
    echo "SKIP: volume $real tidak ditemukan"
    continue
  fi
  echo "Backup $real …"
  docker run --rm -v "$real:/data" -v "$TMP:/backup" alpine \
    tar czf "/backup/${v}.tar.gz" -C /data .
done

tar czf "$OUT" -C "$TMP" .
echo "Selesai → $OUT"
