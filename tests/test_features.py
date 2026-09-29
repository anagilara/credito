from pathlib import Path

import joblib
import pandas as pd
import pytest
from fastapi.testclient import TestClient


from src.features import MODEL_INPUT_COLUMNS, build_features
from src import score as score_api
from src.train import train_model


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

def valid_row() -> dict:
    return {
        "entidad": "Banco Demo A",
        "mora_1m": 0,
        "mora_2m": 1,
        "mora_3m": 2,
        "mora_4m": 3,
        "mora_5m": 4,
        "mora_6m": 5,
        "ingreso_mensual": 4_000_000,
        "saldo_credito": 8_000_000,
        "antiguedad_meses": 24,
        "num_productos": 2,
    }


def test_calcula_promedio_mora_seis_meses() -> None:
    result = build_features(pd.DataFrame([valid_row()]))

    assert result.loc[0, "promedio_mora_6m"] == pytest.approx(2.5)
    assert result.columns.tolist() == MODEL_INPUT_COLUMNS


def test_rechaza_columnas_faltantes() -> None:
    row = valid_row()
    del row["mora_6m"]

    with pytest.raises(ValueError, match="mora_6m"):
        build_features(pd.DataFrame([row]))


def test_rechaza_mora_negativa() -> None:
    row = valid_row()
    row["mora_3m"] = -1

    with pytest.raises(ValueError, match="no pueden ser negativos"):
        build_features(pd.DataFrame([row]))


def test_entrenamiento_supera_umbral_documentado() -> None:
    _, auc = train_model(
        REPOSITORY_ROOT / "data" / "sample_clientes_nomina.csv",
        model_version="test",
    )

    assert auc >= 0.78


def test_api_entrega_version_y_metricas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, _ = train_model(
        REPOSITORY_ROOT / "data" / "sample_clientes_nomina.csv",
        model_version="test-api",
    )
    model_path = tmp_path / "model.joblib"
    joblib.dump(artifact, model_path)
    monkeypatch.setattr(score_api, "MODEL_PATH", model_path)

    with TestClient(score_api.app) as client:
        response = client.post("/score", json=valid_row())
        metrics = client.get("/metrics")

    assert response.status_code == 200
    assert response.json()["model_version"] == "test-api"
    assert 0 <= response.json()["churn_probability"] <= 1
    assert metrics.status_code == 200
    assert "churn_scoring_requests_total" in metrics.text
