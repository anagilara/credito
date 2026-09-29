"""Transformaciones compartidas por entrenamiento y scoring."""

from __future__ import annotations
from collections.abc import Iterable
import pandas as pd

MORA_COLUMNS = [f"mora_{month}m" for month in range(1, 7)]
NUMERIC_INPUT_COLUMNS = [
    *MORA_COLUMNS,
    "ingreso_mensual",
    "saldo_credito",
    "antiguedad_meses",
    "num_productos",
]
MODEL_INPUT_COLUMNS = [
    "promedio_mora_6m",
    "ingreso_mensual",
    "saldo_credito",
    "antiguedad_meses",
    "num_productos",
    "entidad",
]


def require_columns(data: pd.DataFrame, columns: Iterable[str]) -> None:
    """Comprueba que un DataFrame contenga todas las columnas solicitadas."""
    missing = sorted(set(columns) - set(data.columns))
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {', '.join(missing)}")


def build_features(data: pd.DataFrame) -> pd.DataFrame:
    """Valida la entrada y produce las variables usadas por el modelo."""
    require_columns(data, [*NUMERIC_INPUT_COLUMNS, "entidad"])

    transformed = data.copy()
    for column in NUMERIC_INPUT_COLUMNS:
        try:
            transformed[column] = pd.to_numeric(transformed[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"La columna {column} debe ser numérica") from exc

    required = [*NUMERIC_INPUT_COLUMNS, "entidad"]
    if transformed[required].isnull().any().any():
        null_columns = transformed[required].columns[
            transformed[required].isnull().any()
        ].tolist()
        raise ValueError(
            f"No se permiten valores nulos en: {', '.join(null_columns)}"
        )

    if (transformed[MORA_COLUMNS] < 0).any().any():
        raise ValueError("Los valores de mora no pueden ser negativos")
    if (transformed["ingreso_mensual"] <= 0).any():
        raise ValueError("El ingreso mensual debe ser mayor que cero")
    if (transformed["saldo_credito"] < 0).any():
        raise ValueError("El saldo de crédito no puede ser negativo")
    if (transformed["antiguedad_meses"] < 0).any():
        raise ValueError("La antigüedad no puede ser negativa")
    if (transformed["num_productos"] < 1).any():
        raise ValueError("El número de productos debe ser al menos uno")
    if transformed["entidad"].astype(str).str.strip().eq("").any():
        raise ValueError("La entidad no puede estar vacía")

    transformed["promedio_mora_6m"] = transformed[MORA_COLUMNS].mean(axis=1)
    return transformed[MODEL_INPUT_COLUMNS]
