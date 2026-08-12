-- 004_observations.sql
-- Araç GPS gözlemleri (ana API) ve destekleyici API (KalanDurakSayisi) gözlemleri.
-- Madde 1: aynı OtobusId için tek response içindeki farklı koordinatlar KAYBEDİLMEZ,
-- her biri response_index ile ayrı satır olarak saklanır.

CREATE TABLE vehicle_observations (
    id                      BIGSERIAL PRIMARY KEY,
    raw_snapshot_id         BIGINT NOT NULL REFERENCES raw_snapshots(id) ON DELETE CASCADE,
    response_index          INTEGER NOT NULL,   -- aynı response içindeki sıra/konum indexi
    vehicle_id              TEXT NOT NULL,       -- OtobusId
    line_no                 TEXT NOT NULL,
    observed_at             TIMESTAMPTZ NOT NULL,  -- bizim gözlem zamanımız (koleksiyon anı)
    geom                    geography(Point, 4326) NOT NULL,
    raw_lat                 DOUBLE PRECISION NOT NULL,
    raw_lon                 DOUBLE PRECISION NOT NULL,

    -- Madde 1: kalite sınıflandırması, kesin kural yoksa UNKNOWN_POSITION kullanılır.
    position_quality        position_quality NOT NULL DEFAULT 'UNKNOWN_POSITION',
    position_quality_reason TEXT,   -- sınıflandırmanın nasıl yapıldığının kısa açıklaması

    -- Madde 4: map-matching sonuçları
    route_id                BIGINT REFERENCES routes(id),
    distance_to_route_m     DOUBLE PRECISION,
    progress_along_route    DOUBLE PRECISION,   -- 0.0 - 1.0 arası
    distance_along_route_m  DOUBLE PRECISION,
    map_match_quality       map_match_quality,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (raw_snapshot_id, response_index)
);

CREATE INDEX idx_vehicle_obs_vehicle_time ON vehicle_observations(vehicle_id, observed_at);
CREATE INDEX idx_vehicle_obs_line_time ON vehicle_observations(line_no, observed_at);
CREATE INDEX idx_vehicle_obs_geom ON vehicle_observations USING GIST(geom);
CREATE INDEX idx_vehicle_obs_route ON vehicle_observations(route_id);

COMMENT ON COLUMN vehicle_observations.position_quality IS
    'İlk nokta otomatik olarak CURRENT_POSITION varsayılmaz. Zaman/ilerleme tutarlılığına göre türetilir.';

-- Destekleyici API: KalanDurakSayisi zaman serisi (madde 8)
CREATE TABLE supporting_api_observations (
    id                  BIGSERIAL PRIMARY KEY,
    raw_snapshot_id     BIGINT NOT NULL REFERENCES raw_snapshots(id) ON DELETE CASCADE,
    response_index      INTEGER NOT NULL,
    vehicle_id          TEXT NOT NULL,
    line_no             TEXT NOT NULL,
    target_stop_id      TEXT,               -- API bu bilgiyi veriyorsa
    remaining_stop_count INTEGER NOT NULL,   -- KalanDurakSayisi
    observed_at         TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (raw_snapshot_id, response_index)
);

CREATE INDEX idx_support_obs_vehicle_time ON supporting_api_observations(vehicle_id, observed_at);

COMMENT ON TABLE supporting_api_observations IS
    'Madde 8: Tek response içindeki farklı araçların KalanDurakSayisi değerleri zaman serisi kanıtı '
    'olarak KABUL EDİLMEZ. Doğrulama için aynı vehicle_id''nin zaman içindeki azalan değerleri kullanılır.';
