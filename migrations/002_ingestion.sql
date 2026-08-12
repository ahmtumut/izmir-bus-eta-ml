-- 002_ingestion.sql
-- Her collector çalıştırması ve her API çağrısının ham cevabı.
-- Amaç: "her API çağrısı için ayrı JSON dosyası" yapısını ortadan kaldırmak.

CREATE TABLE ingestion_runs (
    id                  BIGSERIAL PRIMARY KEY,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at            TIMESTAMPTZ,
    collector_version   TEXT NOT NULL,          -- git commit SHA veya versiyon etiketi
    target_lines        TEXT[] NOT NULL,        -- örn. ARRAY['515','121']
    host_machine        TEXT,                   -- hangi makineden çalıştırıldı (debug için)
    notes               TEXT,
    -- restart senaryolarını test edebilmek için:
    is_resumed_run       BOOLEAN NOT NULL DEFAULT false,
    resumed_from_run_id  BIGINT REFERENCES ingestion_runs(id)
);

COMMENT ON TABLE ingestion_runs IS 'Her collector başlatma/durdurma döngüsünü temsil eder.';

CREATE TABLE raw_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    ingestion_run_id BIGINT NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
    source_api      TEXT NOT NULL,     -- 'main_api' | 'hattinyaklasanotobusleri' | 'stops' | 'routes'
    line_no         TEXT,              -- ilgiliyse (durak/route importu için NULL olabilir)
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    http_status     INTEGER,
    raw_response    JSONB NOT NULL,    -- ham response tamamı burada saklanır
    response_hash   TEXT NOT NULL,     -- sha256(raw_response::text), duplicate ingestion testleri için
    UNIQUE (ingestion_run_id, source_api, line_no, requested_at, response_hash)
);

CREATE INDEX idx_raw_snapshots_run ON raw_snapshots(ingestion_run_id);
CREATE INDEX idx_raw_snapshots_source_line_time ON raw_snapshots(source_api, line_no, requested_at);
CREATE INDEX idx_raw_snapshots_hash ON raw_snapshots(response_hash);

COMMENT ON COLUMN raw_snapshots.response_hash IS
    'Duplicate ingestion tespiti için sha256. Aynı hash + aynı run + aynı source tekrar geldiyse duplicate kabul edilir.';
