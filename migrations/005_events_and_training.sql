-- 005_events_and_training.sql
-- Madde 6: "Durağa ulaştı" olayının V1 tanımı.
-- Madde 7: ETA ground-truth training örnekleri.

CREATE TABLE arrival_events (
    id                      BIGSERIAL PRIMARY KEY,
    vehicle_id              TEXT NOT NULL,
    line_no                 TEXT NOT NULL,
    direction               SMALLINT NOT NULL CHECK (direction IN (0, 1)),
    stop_id                 BIGINT NOT NULL REFERENCES stops(id),

    approach_started_at     TIMESTAMPTZ NOT NULL,  -- doğru hat/yönde + durağa yaklaşma başladı
    arrival_observed_at     TIMESTAMPTZ NOT NULL,  -- yakınlık alanına girdiği gözlemlenen an (bizim gözlemimiz)
    passed_at               TIMESTAMPTZ,            -- durak sonrasına ilerlediği an (varsa)

    minimum_distance_m      DOUBLE PRECISION NOT NULL,  -- durağa en yakın gözlemlenen mesafe

    arrival_confidence      arrival_confidence NOT NULL,
    validation_source       TEXT NOT NULL,  -- 'gps_only' | 'gps_plus_support_api'
    quality_flags           TEXT[] NOT NULL DEFAULT '{}',

    -- Kaynak gözlemlere iz sürülebilirlik için:
    triggering_observation_id BIGINT REFERENCES vehicle_observations(id),

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_arrival_events_vehicle_time ON arrival_events(vehicle_id, arrival_observed_at);
CREATE INDEX idx_arrival_events_stop ON arrival_events(stop_id);
CREATE INDEX idx_arrival_events_line_dir ON arrival_events(line_no, direction);

COMMENT ON COLUMN arrival_events.arrival_observed_at IS
    'API''de source timestamp olmadığı için bu bizim gözlem zamanımızdır; '
    '±collector_interval kadar belirsizlik içerir (bkz. data_quality_events / dokümantasyon).';

COMMENT ON TABLE arrival_events IS
    'Sadece "50m içine girdi" yeterli değildir: doğru hat/yön + yaklaşma + yakınlık alanı + '
    'sonrasında ilerleme birlikte sağlanmalıdır (madde 6).';

CREATE TABLE eta_training_samples (
    id                      BIGSERIAL PRIMARY KEY,
    vehicle_id              TEXT NOT NULL,
    line_no                 TEXT NOT NULL,
    direction               SMALLINT NOT NULL CHECK (direction IN (0, 1)),
    target_stop_id          BIGINT NOT NULL REFERENCES stops(id),
    arrival_event_id        BIGINT NOT NULL REFERENCES arrival_events(id),
    source_observation_id   BIGINT NOT NULL REFERENCES vehicle_observations(id),  -- T0

    observed_at             TIMESTAMPTZ NOT NULL,      -- T0
    actual_arrival_at       TIMESTAMPTZ NOT NULL,       -- T1
    actual_eta_seconds      DOUBLE PRECISION NOT NULL,  -- T1 - T0, yalnızca label üretiminde kullanılır

    -- T0 anında bilinen feature'lar (geleceğe bakmaz):
    distance_remaining_m    DOUBLE PRECISION NOT NULL,
    progress_along_route    DOUBLE PRECISION NOT NULL,
    recent_speed_mps        DOUBLE PRECISION,
    hour_of_day             SMALLINT NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
    day_of_week             SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),

    label_quality           label_quality NOT NULL,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- future leakage koruması: T0, T1'den önce olmalı
    CONSTRAINT chk_no_future_leakage CHECK (observed_at < actual_arrival_at)
);

CREATE INDEX idx_eta_training_line_dir ON eta_training_samples(line_no, direction);
CREATE INDEX idx_eta_training_stop ON eta_training_samples(target_stop_id);
CREATE INDEX idx_eta_training_quality ON eta_training_samples(label_quality);

COMMENT ON CONSTRAINT chk_no_future_leakage ON eta_training_samples IS
    'Madde 7: model girdisi gelecekte oluşan bilgiyi feature olarak kullanamaz; '
    'actual_eta yalnızca label üretiminde geleceğe bakabilir.';
