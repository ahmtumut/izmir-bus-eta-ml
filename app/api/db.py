"""Faz 4: read-only DB baglanti yardimcisi (gorsellestirme API'si icin).

app/storage/db_storage.py sadece yazma (ingestion) fonksiyonlari icerir; bu
modul aynı DB_CONFIG'i kullanir ama sadece okuma amaclidir.
"""
import psycopg
from psycopg.rows import dict_row

from app.storage.db_storage import DB_CONFIG


def get_read_connection():
    return psycopg.connect(**DB_CONFIG, row_factory=dict_row)
