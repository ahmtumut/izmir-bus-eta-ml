#!/usr/bin/env bash
# Faz 2 kabul kriteri: "temiz ortamda tek komutla database oluşturulabilmeli"
# Bu script mevcut volume'u siler ve sıfırdan kurar (TÜM VERİYİ SİLER — dikkat).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo ">> Mevcut container ve volume siliniyor (varsa)..."
docker compose down -v

echo ">> Yeniden ayağa kaldırılıyor (migrations otomatik uygulanacak)..."
docker compose up -d postgis

echo ">> PostgreSQL hazır olana kadar bekleniyor..."
until docker exec izmir_bus_eta_db pg_isready -U eta_user -d izmir_bus_eta > /dev/null 2>&1; do
    sleep 1
done

echo ">> Hazır. Tabloları doğrulamak için:"
echo "   docker exec -it izmir_bus_eta_db psql -U eta_user -d izmir_bus_eta -c '\\dt'"
