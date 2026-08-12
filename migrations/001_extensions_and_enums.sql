-- 001_extensions_and_enums.sql
-- PostGIS ve pgcrypto (SHA-256 / UUID üretimi için) eklentileri.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- GPS nokta kalite sınıflandırması (madde 1)
-- "İlk nokta güncel noktadır" varsayımı YAPILMAZ; her nokta ayrı değerlendirilir.
CREATE TYPE position_quality AS ENUM (
    'CURRENT_POSITION',   -- KalanDurakSayisi/zaman ile tutarlı, güncel kabul edilebilir
    'STALE_POSITION',     -- aynı koordinat tekrar ediyor veya zaman/ilerleme ile tutarsız
    'UNKNOWN_POSITION'    -- kesin sınıflandırma yapılamıyor, açıkça belirsiz
);

-- Map-matching kalite bayrağı (madde 4)
CREATE TYPE map_match_quality AS ENUM (
    'GOOD',        -- rotaya yakın, güvenilir projeksiyon
    'DEGRADED',     -- rotaya makul ama şüpheli mesafede
    'REJECTED'      -- rotadan anormal uzak, kullanılmamalı
);

-- Varış olayı güven seviyesi (madde 6)
CREATE TYPE arrival_confidence AS ENUM (
    'HIGH',     -- GPS + support API zaman serisi birlikte doğruluyor
    'MEDIUM',   -- yalnızca GPS bazlı, tutarlı ilerleme
    'LOW'       -- tek kaynaklı / zayıf kanıt, eğitim için kullanılmamalı
);

-- Training label kalite seviyesi (madde 7)
CREATE TYPE label_quality AS ENUM (
    'GOLD',     -- HIGH confidence arrival event'ten türetildi
    'SILVER',   -- MEDIUM confidence arrival event'ten türetildi
    'REJECTED'  -- LOW confidence, eğitimde kullanılmamalı ama şeffaflık için saklanıyor
);

-- Veri kalitesi olay şiddeti (madde 10 / genel raporlama)
CREATE TYPE quality_severity AS ENUM ('INFO', 'WARNING', 'ERROR');
