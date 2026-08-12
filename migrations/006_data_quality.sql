-- 006_data_quality.sql
-- Tüm pipeline boyunca (map-matching, arrival detection, label üretimi, collector restart vb.)
-- ortaya çıkan kalite sorunlarının merkezi kaydı.

CREATE TABLE data_quality_events (
    id              BIGSERIAL PRIMARY KEY,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    stage           TEXT NOT NULL,   -- 'ingestion' | 'map_matching' | 'stop_sequencing' |
                                       -- 'arrival_detection' | 'label_generation' | 'collector_restart'
    severity        quality_severity NOT NULL,
    ingestion_run_id BIGINT REFERENCES ingestion_runs(id),
    vehicle_id      TEXT,
    line_no         TEXT,
    stop_id         BIGINT REFERENCES stops(id),
    description     TEXT NOT NULL,
    context         JSONB   -- ilgili ham değerler / debug bilgisi
);

CREATE INDEX idx_dqe_stage_severity ON data_quality_events(stage, severity);
CREATE INDEX idx_dqe_run ON data_quality_events(ingestion_run_id);
CREATE INDEX idx_dqe_occurred_at ON data_quality_events(occurred_at);

COMMENT ON TABLE data_quality_events IS
    'Madde 1, 4, 5, 6, 8, 10 kapsamındaki tüm belirsizlik/anomali raporlamaları buraya yazılır: '
    'örn. UNKNOWN_POSITION sınıflaması, REJECTED map-match, spatial_only durak sırası, '
    'LOW confidence arrival event, collector restart sonrası gap.';
