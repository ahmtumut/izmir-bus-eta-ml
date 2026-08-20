"""Faz 4: FastAPI backend - GPS replay gorsellestirme API'si.

Calistirma:
    uvicorn app.api.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_data, replay, model_metrics, live

app = FastAPI(title="Izmir Bus ETA - Replay API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(routes_data.router)
app.include_router(replay.router)
app.include_router(model_metrics.router)
app.include_router(live.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
