import pytest
from fastapi.testclient import TestClient

from app.core.config import Config
from app.core.db import conectar, migrar
from app.main import crear_app

PIN = "4321"


@pytest.fixture
def config(tmp_path):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db", exports_path=tmp_path / "exports")


@pytest.fixture
def con(config):
    c = conectar(config.db_path)
    migrar(c)
    yield c
    c.close()


@pytest.fixture
def datos(con):
    """Bolsillos iniciales, deudas del spec, cuentas, metas y plantillas 15 y 30."""
    from app.modules.finanzas import consultas as q
    from app.modules.finanzas.logica import Linea

    b = {n: q.crear_bolsillo(con, n, t) for n, t in
         [("Casa", "fijo"), ("Tarjeta Uno", "deuda"), ("Ahorro", "ahorro"), ("Libre", "libre")]}
    d = {
        "tarjeta": q.crear_deuda(con, "Tarjeta USD", "USD", 183700),
        "tarjeta_cop": q.crear_deuda(con, "Tarjeta COP", "COP", 275791),
        "educa": q.crear_deuda(con, "Educa", "COP", 9637784),
    }
    c = {n: q.crear_cuenta(con, n) for n in ["Nu", "Banco Uno", "Fondo Uno"]}
    q.crear_meta(con, "6 meses de básicos", 17_000_000, [c["Nu"]])
    with con:
        p15 = con.execute("INSERT INTO plantillas (nombre) VALUES ('15')").lastrowid
        p30 = con.execute("INSERT INTO plantillas (nombre) VALUES ('30')").lastrowid
    q.guardar_lineas_plantilla(con, p15, [
        Linea("Educa", b["Casa"], 226582, deuda_id=d["educa"]),
        Linea("Mitad del mercado", b["Casa"], 700000),
        Linea("Cositas", b["Casa"], 150000),
        Linea("Mitad de administración", b["Casa"], 130000),
        Linea("Mamá", b["Casa"], 250000),
        Linea("Datos", b["Casa"], 50000),
        Linea("Ahorro", b["Ahorro"], 1000000),
        Linea("Libre", b["Libre"], None, "resto"),
    ])
    q.guardar_lineas_plantilla(con, p30, [
        Linea("Mitad del mercado", b["Casa"], 700000),
        Linea("Factura Tarjeta Uno", b["Tarjeta Uno"], None, "pedir"),
        Linea("Ahorro", b["Ahorro"], 0),
        Linea("Libre", b["Libre"], None, "resto"),
    ])
    return {"b": b, "d": d, "c": c, "p15": p15, "p30": p30}


@pytest.fixture
def app(config):
    return crear_app(config)


@pytest.fixture
def anonimo(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cliente(app, datos):
    with TestClient(app) as c:
        r = c.post("/login", data={"pin": PIN}, follow_redirects=False)
        assert r.status_code == 303
        yield c
