-- 003_stops_and_routes.sql
-- Resmi ESHOT durak ve güzergah verileri (madde 3 + 4).

CREATE TABLE data_sources (
    id              BIGSERIAL PRIMARY KEY,
    source_name     TEXT NOT NULL,          -- 'ESHOT_Otobus_Duraklari' | 'ESHOT_Otobus_Hat_Guzergahlari'
    source_url      TEXT NOT NULL,
    downloaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_sha256  TEXT NOT NULL,
    UNIQUE (source_name, content_sha256)
);

COMMENT ON TABLE data_sources IS
    'Dış kaynaklardan indirilen resmi verilerin izlenebilirliği: URL, indirilme zamanı, SHA-256.';

CREATE TABLE stops (
    id              BIGSERIAL PRIMARY KEY,
    stop_id         TEXT NOT NULL UNIQUE,   -- ESHOT durak ID
    stop_name       TEXT NOT NULL,
    geom            geography(Point, 4326) NOT NULL,
    lines_through   TEXT[],                 -- duraktan geçen hatlar (ham liste, hızlı filtre için)
    data_source_id  BIGINT REFERENCES data_sources(id)
);

CREATE INDEX idx_stops_geom ON stops USING GIST(geom);
CREATE INDEX idx_stops_lines_through ON stops USING GIN(lines_through);

CREATE TABLE routes (
    id              BIGSERIAL PRIMARY KEY,
    line_no         TEXT NOT NULL,
    direction       SMALLINT NOT NULL CHECK (direction IN (0, 1)),  -- 0 = gidiş, 1 = dönüş
    shape_geom      geography(LineString, 4326) NOT NULL,           -- madde 4: hat+yön LineString
    total_length_m  DOUBLE PRECISION,
    data_source_id  BIGINT REFERENCES data_sources(id),
    UNIQUE (line_no, direction)
);

CREATE INDEX idx_routes_geom ON routes USING GIST(shape_geom);
CREATE INDEX idx_routes_line ON routes(line_no);

-- Ham sıralı güzergah noktaları — LineString'i oluşturmadan önceki kaynak veri.
-- Sıra hatası ayıklaması gerekirse ham noktalara geri dönebilmek için tutulur.
CREATE TABLE route_shape_points (
    id              BIGSERIAL PRIMARY KEY,
    route_id        BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,       -- kaynaktaki orijinal sıra
    geom            geography(Point, 4326) NOT NULL,
    UNIQUE (route_id, seq)
);

CREATE INDEX idx_route_shape_points_route ON route_shape_points(route_id, seq);

-- Durakların hat+yön üzerindeki sırası (madde 5).
-- stops <-> routes çoka-çok ilişkisini, güzergah üzerindeki projeksiyonla birlikte tutar.
CREATE TABLE route_stop_sequence (
    id                      BIGSERIAL PRIMARY KEY,
    route_id                BIGINT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    stop_id                 BIGINT NOT NULL REFERENCES stops(id) ON DELETE CASCADE,
    sequence_order          INTEGER NOT NULL,            -- güzergah boyunca sıralama
    distance_along_route_m  DOUBLE PRECISION NOT NULL,    -- projeksiyon sonucu
    validation_method       TEXT,        -- 'manual_pilot_sample' | 'kalan_durak_sayisi' | 'spatial_only'
    is_verified             BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (route_id, stop_id),
    UNIQUE (route_id, sequence_order)
);

CREATE INDEX idx_route_stop_sequence_route ON route_stop_sequence(route_id, sequence_order);

COMMENT ON COLUMN route_stop_sequence.validation_method IS
    'Sadece mekansal yakınlıkla (spatial_only) sıraya giren duraklar şüpheli kabul edilmeli; '
    'pilot hatlarda manual_pilot_sample veya kalan_durak_sayisi ile çapraz doğrulanmalı.';
