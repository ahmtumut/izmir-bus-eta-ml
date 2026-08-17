"""
Faz 3: eta_features CSV'sini (bkz. app/ml/features.py) train/validation/test
DataFrame'lerine ayirir ve model feature/target kolonlarini tanimlar.

vehicle_id, id, arrival_event_id, source_observation_id, route_id,
observed_at, label_quality, dataset_split: KIMLIK/METADATA kolonlaridir,
MODEL_FEATURE_COLUMNS icinde DEGILDIR.
actual_eta_seconds: TARGET (label) - feature olarak kullanilmaz.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd

CATEGORICAL_FEATURES = ["line_no", "direction", "target_stop_id"]
NUMERIC_FEATURES = [
    "distance_remaining_m", "progress_along_route", "recent_speed_mps",
    "hour_of_day", "day_of_week", "distance_to_route_m",
    "time_since_previous_obs_s", "speed_avg_last3_mps",
    "speed_std_last3_mps", "speed_avg_5min_mps",
]
MODEL_FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES
TARGET_COLUMN = "actual_eta_seconds"


def load_features(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["observed_at"])
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("category")
    return df


def split_dataframe(df: pd.DataFrame):
    """dataset_split kolonuna gore train/validation/test DataFrame'lerine ayirir.
    Kategori kodlari (line_no/direction/target_stop_id) TUM veri uzerinden
    tanimlanir (split'ten sonra degil) - boylece train'de gorulmeyen bir
    kategori test'te "unknown code" olarak degil, dogru kategorik deger
    olarak temsil edilir (XGBoost native categorical bunu NaN olarak
    kabul eder, hata vermez, ama tutarlilik icin kategoriler birlikte
    tanimlaniyor)."""
    train = df[df["dataset_split"] == "train"].reset_index(drop=True)
    val = df[df["dataset_split"] == "validation"].reset_index(drop=True)
    test = df[df["dataset_split"] == "test"].reset_index(drop=True)
    return train, val, test


def get_X_y(df: pd.DataFrame):
    X = df[MODEL_FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]
    return X, y
