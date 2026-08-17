-- 008_dataset_split.sql
-- Faz 3: Train/Validation/Test split ataması.
--
-- Split, arrival_event_id bazında yapılır (bir event'in tüm T0 satırları
-- AYNI split'e düşer - satır bazlı rastgele split data leakage'a yol açar,
-- çünkü aynı yolculuğun farklı T0 anları hem train hem test'e sızabilir).
-- Split zamansal sıralıdır: erken dönem -> train, sonraki -> validation,
-- en son -> test (bkz. app/ml/split.py).

CREATE TYPE dataset_split AS ENUM ('train', 'validation', 'test');

ALTER TABLE eta_training_samples
    ADD COLUMN dataset_split dataset_split,
    ADD COLUMN split_assigned_at TIMESTAMPTZ;

CREATE INDEX idx_eta_training_split ON eta_training_samples(dataset_split);

COMMENT ON COLUMN eta_training_samples.dataset_split IS
    'app/ml/split.py tarafından atanır. NULL = henüz split edilmemiş veya '
    'label_quality=REJECTED (split disi tutulur). Ayni arrival_event_id''nin '
    'TUM satirlari ayni split degerini tasir (event bazinda atama).';
