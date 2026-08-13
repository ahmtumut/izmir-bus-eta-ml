-- 007_direction_and_idempotency.sql
-- Faz 2 kapanis duzeltmeleri (Supervisor geri bildirimi):
-- 1. Kaynak API'den gelen yon bilgisini kalici olarak sakla (source_direction).
-- 2. Yon/geometry celiskisi icin quality_flags kolonu.
-- 3. arrival_events ve eta_training_samples uretiminin idempotent olmasi
--    icin unique constraint'ler (ayni run/veri uzerinde tekrar calistirma
--    duplicate satir uretmemeli).

ALTER TABLE vehicle_observations
    ADD COLUMN source_direction SMALLINT CHECK (source_direction IN (0, 1)),
    ADD COLUMN quality_flags TEXT[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN vehicle_observations.source_direction IS
    'Kaynak API''den gelen HAM yon bilgisi (0=gidis, 1=donus - routes.direction '
    'ile ayni konvansiyon). Map-matching''de once bu kullanilir; geometry ile '
    'celisirse DIRECTION_ROUTE_MISMATCH flag''i quality_flags''e eklenir, '
    'route_id yine de en yakin geometriye gore atanir (sessizce yon degistirilmez).';

-- arrival_events: ayni tetikleyici gozlem + ayni durak icin ikinci kez
-- event uretilmesini engeller (script tekrar calistirilabilir).
ALTER TABLE arrival_events
    ADD CONSTRAINT uq_arrival_events_trigger_stop
    UNIQUE (triggering_observation_id, stop_id);

-- eta_training_samples: ayni kaynak gozlem + ayni arrival_event icin
-- ikinci kez training satiri uretilmesini engeller.
ALTER TABLE eta_training_samples
    ADD CONSTRAINT uq_eta_training_source_event
    UNIQUE (source_observation_id, arrival_event_id);
