"""Carga resultados de tests desde un archivo TOML local (fuera de git) a SQLite.

Uso: uv run python -m app.modules.rendimiento.carga_tests [ruta]  (por defecto data/tests.local.toml)
Es idempotente: una evaluación ya cargada (mismo tipo, fecha y origen) se reemplaza, no se duplica.
"""

import sqlite3
import sys
import tomllib
from pathlib import Path

from .logica import parse_decimal_mil

RAIZ = Path(__file__).resolve().parents[3]
LOCAL = RAIZ / "data" / "tests.local.toml"

# campo del archivo -> (tipo de test, medida, unidad, dirección)
CAMPOS = {
    "cmj_cm": ("cmj", "CMJ", "cm", "mas"),
    "dinamometria_dom_kg": ("dinamometria", "Mano dominante", "kg", "mas"),
    "dinamometria_nodom_kg": ("dinamometria", "Mano no dominante", "kg", "mas"),
    "caminata_6min_km": ("caminata_6min", "Distancia", "km", "mas"),
    "peso_kg": ("antropometria", "Peso", "kg", "neutra"),
    "imc": ("antropometria", "IMC", "kg/m²", "neutra"),
    "cintura_cm": ("antropometria", "Perímetro cintura", "cm", "neutra"),  # depende de la meta
    "cadera_cm": ("antropometria", "Perímetro cadera", "cm", "neutra"),
    "icc": ("antropometria", "Índice cintura cadera", "", "menos"),
}


def _valores(ev: dict) -> dict[str, list[tuple[str, int, str, str]]]:
    por_tipo: dict[str, list[tuple[str, int, str, str]]] = {}
    for campo, (tipo, medida, unidad, direccion) in CAMPOS.items():
        if campo in ev and str(ev[campo]).strip():
            por_tipo.setdefault(tipo, []).append((medida, parse_decimal_mil(str(ev[campo])), unidad, direccion))
    for carga, vel in sorted((ev.get("vmp_ms") or {}).items(), key=lambda kv: int(kv[0])):
        por_tipo.setdefault("carga_velocidad", []).append((f"VMP {carga} kg", parse_decimal_mil(str(vel)), "m/s", "mas"))
    return por_tipo


def cargar(con: sqlite3.Connection, datos: dict, origen: str) -> list[str]:
    fuente = datos.get("fuente", {})
    evaluador = fuente.get("evaluador")
    metodo_antro = fuente.get("metodo_antropometria")
    hechos = []
    with con:
        for ev in datos.get("evaluacion", []):
            fecha = str(ev["fecha"])
            quien = ev.get("evaluador") or evaluador
            por_tipo = _valores(ev)
            if ev.get("overhead_squat"):
                por_tipo.setdefault("movilidad", [])
            for tipo, valores in por_tipo.items():
                con.execute("DELETE FROM tests WHERE tipo = ? AND fecha = ? AND origen = ?", (tipo, fecha, origen))
                notas = f"Overhead squat: {ev['overhead_squat']}" if tipo == "movilidad" else (ev.get("notas", {}).get(tipo))
                metodo = metodo_antro if tipo == "antropometria" else ("Sentadilla" if tipo == "carga_velocidad" else None)
                tid = con.execute(
                    "INSERT INTO tests (tipo, fecha, metodo, evaluador, protocolo, notas, origen) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tipo, fecha, metodo, quien, "Overhead squat" if tipo == "movilidad" else None, notas, origen)).lastrowid
                for medida, valor, unidad, direccion in valores:
                    con.execute("INSERT INTO test_valores (test_id, medida, valor_mil, unidad, direccion) VALUES (?, ?, ?, ?, ?)",
                                (tid, medida, valor, unidad, direccion))
                hechos.append(f"{fecha} {tipo}")
    return hechos


def main(argv: list[str]) -> int:
    from app.core.config import leer_config
    from app.core.db import conectar, migrar
    ruta = Path(argv[0]) if argv else LOCAL
    if not ruta.exists():
        print(f"No encontré {ruta}. Copia tus resultados ahí (ver tests/datos/tests.example.toml).")
        return 1
    cfg = leer_config()
    con = conectar(cfg.db_path)
    migrar(con)
    with ruta.open("rb") as fh:
        hechos = cargar(con, tomllib.load(fh), ruta.name)
    print(f"Cargados {len(hechos)} tests desde {ruta.name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
