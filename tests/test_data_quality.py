from pathlib import Path

import pandas as pd

from src.features import MORA_COLUMNS, NUMERIC_INPUT_COLUMNS, require_columns

DATA_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "sample_clientes_nomina.csv"
)
REQUIRED_COLUMNS = [
    "cliente_id",
    "entidad",
    *NUMERIC_INPUT_COLUMNS,
    "churn",
]


def load_data() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH)


def test_columnas_requeridas() -> None:
    require_columns(load_data(), REQUIRED_COLUMNS)


def test_datos_sin_nulos() -> None:
    assert not load_data()[REQUIRED_COLUMNS].isnull().any().any()


def test_rangos_y_tipos_validos() -> None:
    data = load_data()

    assert data["cliente_id"].is_unique
    assert (data[MORA_COLUMNS] >= 0).all().all()
    assert (data["ingreso_mensual"] > 0).all()
    assert (data["saldo_credito"] >= 0).all()
    assert (data["antiguedad_meses"] >= 0).all()
    assert (data["num_productos"] >= 1).all()
    assert set(data["churn"].unique()) == {0, 1}


def test_entidades_son_sinteticas_y_conocidas() -> None:
    assert set(load_data()["entidad"].unique()) == {
        "Banco Demo A",
        "Banco Demo B",
        "Banco Demo C",
    }
