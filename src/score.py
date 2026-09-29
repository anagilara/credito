"""API de scoring observable para Churn Radar."""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

try:
    from src.features import build_features
except ModuleNotFoundError:
    from features import build_features

LOGGER = logging.getLogger("churn-radar")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(message)s")

MODEL_PATH = Path(os.getenv("MODEL_PATH", "artifacts/model.joblib"))
DRIFT_WINDOW_SIZE = int(os.getenv("DRIFT_WINDOW_SIZE", "20"))
DRIFT_THRESHOLD = float(os.getenv("DRIFT_THRESHOLD", "0.15"))

REQUESTS = Counter(
    "churn_scoring_requests_total",
    "Solicitudes de scoring procesadas",
    ["model_version", "entity", "status"],
)
LATENCY = Histogram(
    "churn_scoring_latency_seconds",
    "Latencia de scoring",
    ["model_version", "entity"],
)
SCORES = Histogram(
    "churn_score_probability",
    "Distribución de probabilidades de churn",
    ["model_version", "entity"],
    buckets=(0.1, 0.25, 0.5, 0.75, 0.9, 1.0),
)


class ScoringRequest(BaseModel):
    entidad: str = Field(min_length=1)
    mora_1m: Annotated[float, Field(ge=0)]
    mora_2m: Annotated[float, Field(ge=0)]
    mora_3m: Annotated[float, Field(ge=0)]
    mora_4m: Annotated[float, Field(ge=0)]
    mora_5m: Annotated[float, Field(ge=0)]
    mora_6m: Annotated[float, Field(ge=0)]
    ingreso_mensual: Annotated[float, Field(gt=0)]
    saldo_credito: Annotated[float, Field(ge=0)]
    antiguedad_meses: Annotated[int, Field(ge=0)]
    num_productos: Annotated[int, Field(ge=1)]


class ScoringResponse(BaseModel):
    churn_probability: float
    churn_prediction: int
    model_version: str
    drift_alert: bool


def configure_azure_monitor() -> None:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        return
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor as configure

        configure(connection_string=connection_string)
    except Exception:
        LOGGER.exception("No se pudo configurar Azure Monitor")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_azure_monitor()
    if not MODEL_PATH.exists():
        raise RuntimeError(f"No existe el artefacto del modelo: {MODEL_PATH}")
    app.state.artifact = joblib.load(MODEL_PATH)
    app.state.score_windows = defaultdict(
        lambda: deque(maxlen=DRIFT_WINDOW_SIZE)
    )
    yield


app = FastAPI(
    title="Churn Radar API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "model_version": app.state.artifact["metadata"]["model_version"],
    }


@app.post("/score", response_model=ScoringResponse)
def score(request: ScoringRequest) -> ScoringResponse:
    started_at = time.perf_counter()
    artifact = app.state.artifact
    model_version = artifact["metadata"]["model_version"]
    entity = request.entidad.strip()
    status = "success"

    try:
        raw = pd.DataFrame([request.model_dump() | {"entidad": entity}])
        features = build_features(raw)
        probability = float(artifact["pipeline"].predict_proba(features)[0, 1])

        score_window = app.state.score_windows[entity]
        score_window.append(probability)
        baseline = artifact["metadata"]["baseline_by_entity"].get(entity)
        drift_alert = False
        if baseline and len(score_window) >= min(5, DRIFT_WINDOW_SIZE):
            observed_mean = sum(score_window) / len(score_window)
            drift_alert = abs(observed_mean - baseline["score_mean"]) >= DRIFT_THRESHOLD

        SCORES.labels(model_version=model_version, entity=entity).observe(probability)
        LOGGER.info(
            json.dumps(
                {
                    "event": "scoring",
                    "entity": entity,
                    "model_version": model_version,
                    "score": round(probability, 6),
                    "drift_alert": drift_alert,
                },
                ensure_ascii=False,
            )
        )
        return ScoringResponse(
            churn_probability=probability,
            churn_prediction=int(probability >= 0.5),
            model_version=model_version,
            drift_alert=drift_alert,
        )
    except ValueError as exc:
        status = "invalid"
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        status = "error"
        LOGGER.exception("Error inesperado durante el scoring")
        raise
    finally:
        latency = time.perf_counter() - started_at
        REQUESTS.labels(
            model_version=model_version,
            entity=entity,
            status=status,
        ).inc()
        LATENCY.labels(model_version=model_version, entity=entity).observe(latency)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
