#!/usr/bin/env bash
# Zaten ayakta olan bir postgis container'ına migration dosyalarını sırayla uygular.
# Not: docker-compose.yml'deki docker-entrypoint-initdb.d mekanizması SADECE
# ilk kez (boş volume ile) çalışır. Şema değişikliği sonrası tekrar uygulamak
# için bu scripti kullan, ya da `docker compose down -v` ile volume'u sıfırlayıp
# `docker compose up -d` ile temiz kurulumu tetikle.

set -euo pipefail

CONTAINER_NAME="izmir_bus_eta_db"
DB_USER="eta_user"
DB_NAME="izmir_bus_eta"
MIGRATIONS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../migrations" && pwd)"

for f in "$MIGRATIONS_DIR"/*.sql; do
    echo ">> Uygulanıyor: $(basename "$f")"
    docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" < "$f"
done

echo ">> Tüm migration'lar uygulandı."
