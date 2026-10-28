"""SQLite con sqlite3 de la librería estándar. Migraciones en SQL por módulo."""

import sqlite3
from pathlib import Path

from starlette.requests import Request

MODULOS = Path(__file__).resolve().parents[1] / "modules"


def carpetas_migraciones() -> list[Path]:
    """Una carpeta `migrations` por módulo, en orden alfabético del módulo; cada una numera desde 001."""
    return sorted(p for p in MODULOS.glob("*/migrations") if p.is_dir())


def conectar(ruta: Path | str) -> sqlite3.Connection:
    if str(ruta) != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def migrar(con: sqlite3.Connection) -> list[str]:
    con.execute(
        "CREATE TABLE IF NOT EXISTS _migraciones ("
        " nombre TEXT PRIMARY KEY, aplicada TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    hechas = {r[0] for r in con.execute("SELECT nombre FROM _migraciones")}
    nuevas = []
    for carpeta in carpetas_migraciones():
        for archivo in sorted(carpeta.glob("*.sql")):
            nombre = f"{carpeta.parent.name}/{archivo.name}"
            if nombre in hechas:
                continue
            with con:
                con.executescript(archivo.read_text(encoding="utf-8"))
                con.execute("INSERT INTO _migraciones (nombre) VALUES (?)", (nombre,))
            nuevas.append(nombre)
    return nuevas


def con_peticion(request: Request):
    """Dependencia de FastAPI: una conexión por petición."""
    con = conectar(request.app.state.config.db_path)
    try:
        yield con
    finally:
        con.close()
