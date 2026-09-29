"""Entrenamiento determinista para la demostración Churn Radar."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

try:
    from src.features import MODEL_INPUT_COLUMNS, build_features, require_columns
except ModuleNotFoundError:
    from features import MODEL_INPUT_COLUMNS, build_features, require_columns

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = REPOSITORY_ROOT / "data" / "sample_clientes_nomina.csv"
DEFAULT_MODEL_PATH = REPOSITORY_ROOT / "artifacts" / "model.joblib"


def train_model(
    data_path: Path = DEFAULT_DATA_PATH,
    model_version: str | None = None,
) -> tuple[dict, float]:
    data = pd.read_csv(data_path)
    require_columns(data, ["churn"])
    if data["churn"].isnull().any():
        raise ValueError("La columna churn no puede contener valores nulos")
    if not set(data["churn"].unique()).issubset({0, 1}):
        raise ValueError("La columna churn solo puede contener 0 y 1")

    features = build_features(data)
    target = data["churn"].astype(int)

    numeric_columns = [column for column in MODEL_INPUT_COLUMNS if column != "entidad"]
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), numeric_columns),
            (
                "entity",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                ["entidad"],
            ),
        ]
    )
    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            (
                "classifier",
                LogisticRegression(
                    random_state=42,
                    max_iter=500,
                    class_weight="balanced",
                ),
            ),
        ]
    )

    x_train, x_test, y_train, y_test = train_test_split(
        features,
        target,
        test_size=0.25,
        random_state=42,
        stratify=target,
    )
    pipeline.fit(x_train, y_train)
    auc = float(roc_auc_score(y_test, pipeline.predict_proba(x_test)[:, 1]))

    baseline = (
        features.assign(churn_score=pipeline.predict_proba(features)[:, 1])
        .groupby("entidad", observed=True)
        .agg(
            promedio_mora_6m=("promedio_mora_6m", "mean"),
            score_mean=("churn_score", "mean"),
            score_std=("churn_score", "std"),
        )
        .fillna(0.0)
        .to_dict(orient="index")
    )
    artifact = {
        "pipeline": pipeline,
        "metadata": {
            "model_version": model_version
            or os.getenv("MODEL_VERSION")
            or "local-demo",
            "trained_at": datetime.now(UTC).isoformat(),
            "auc": auc,
            "input_columns": MODEL_INPUT_COLUMNS,
            "baseline_by_entity": baseline,
        },
    }
    return artifact, auc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--check-auc", type=float)
    parser.add_argument("--model-version")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact, auc = train_model(args.data, args.model_version)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.output)
    print(
        json.dumps(
            {
                "auc": round(auc, 4),
                "model_version": artifact["metadata"]["model_version"],
                "artifact": str(args.output),
            },
            ensure_ascii=False,
        )
    )

    if args.check_auc is not None and auc < args.check_auc:
        print(
            f"AUC {auc:.4f} inferior al umbral requerido {args.check_auc:.4f}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
