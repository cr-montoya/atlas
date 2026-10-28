"""Requirement: Registro de combate (escenario Patrones) y catálogo editable."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import combate, consultas as q, rutas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
HOY = date(2026, 10, 17)


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    vault.limpiar_cache()
    return destino


@pytest.fixture
def config(tmp_path, boveda):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db",
                  exports_path=tmp_path / "exports", vault_path=boveda, fotos_path=tmp_path / "fotos")


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: HOY)


def _t(con, nombre):
    return con.execute("SELECT id FROM tecnicas WHERE disciplina = 'judo' AND nombre = ?", (nombre,)).fetchone()[0]


def _seis_sesiones(con):
    fechas = ["2026-09-22", "2026-09-26", "2026-10-01", "2026-10-06", "2026-10-10", "2026-10-15"]
    for i, f in enumerate(fechas):
        sid = q.crear_sesion(con, f, "combate", "judo")
        tec = q.crear_bloque(con, sid, "tecnica", 1800)
        q.agregar_entrada(con, tec, tecnica_id=_t(con, "Uchi mata"))
        if i % 2 == 0:
            q.agregar_entrada(con, tec, tecnica_id=_t(con, "Seoi nage"))
        ran = q.crear_bloque(con, sid, "randori", 1500, 5)
        q.actualizar_bloque(con, ran, duracion_s=1500, rounds=5, rivales=["más pesado"] if i < 3 else ["zurdo"])
        q.agregar_entrada(con, ran, tecnica_id=_t(con, "O uchi gari"), resultado="funciono" if i < 4 else "no_funciono")
        q.agregar_entrada(con, ran, situacion="agarre", resultado="no_funciono", detalle="salidas de agarre contra zurdo")
        q.guardar_sesion(con, sid, duracion_s=3300, molestia=None, sensaciones=None, notas="", clave_importada=None)


def test_patrones(cliente, con):
    _seis_sesiones(con)
    p = combate.patrones(con, "2026-09-19", "2026-10-17")
    assert p["sesiones"] == 6
    ranking = [(t.nombre, t.veces) for t in p["tecnicas"]]
    assert ranking[:3] == [("O uchi gari", 6), ("Uchi mata", 6), ("Seoi nage", 3)]
    ouchi = next(t for t in p["con_resultado"] if t.nombre == "O uchi gari")
    assert (ouchi.funciono, ouchi.no_funciono, ouchi.pct_funciono) == (4, 2, 67)
    assert p["situaciones"] == [("Agarre y kumikata", 6)]
    assert dict(p["rivales"]) == {"más pesado": 3, "zurdo": 3}
    pagina = cliente.get("/rendimiento/combate").text
    assert "Técnicas más trabajadas" in pagina and "67 % funcionó" in pagina and "Agarre y kumikata" in pagina


def test_periodo_y_disciplina(cliente, con):
    _seis_sesiones(con)
    assert combate.patrones(con, "2026-10-03", "2026-10-17")["sesiones"] == 3
    assert combate.patrones(con, "2026-09-19", "2026-10-17", "bjj")["sesiones"] == 0
    assert "Sin sesiones de combate en este período" in cliente.get("/rendimiento/combate?disciplina=bjj").text


def test_analisis_lleva_a_mi_combate_y_mas_a_catalogos(cliente):
    assert 'href="/rendimiento/combate"' in cliente.get("/rendimiento/analisis").text
    pagina = cliente.get("/rendimiento/mas").text
    for ruta in ("/rendimiento/actividades", "/rendimiento/catalogo/ejercicios", "/rendimiento/catalogo/tecnicas"):
        assert f'href="{ruta}"' in pagina


def test_catalogo_de_ejercicios_editable(cliente, con):
    r = cliente.post("/rendimiento/catalogo/ejercicios", data={"nombre": "Landmine press", "grupo": "empuje",
                                                               "tipo_carga": "barra", "carga_hombro": "1"}, follow_redirects=False)
    assert r.status_code == 303
    e = q.ejercicio_por_nombre(con, "Landmine press")
    assert e["carga_hombro"] == 1
    cliente.post(f"/rendimiento/catalogo/ejercicios/{e['id']}", data={"carga_hombro": "0"})
    cliente.post(f"/rendimiento/catalogo/ejercicios/{e['id']}", data={"activo": "0"})
    e = q.ejercicio(con, e["id"])
    assert (e["carga_hombro"], e["activo"]) == (0, 0)
    assert all(x["id"] != e["id"] for x in q.ejercicios(con))  # oculto ya no aparece para registrar
    r = cliente.post("/rendimiento/catalogo/ejercicios", data={"nombre": "Landmine press", "grupo": "empuje", "tipo_carga": "barra"})
    assert r.status_code == 422 and "Ya existe un ejercicio llamado «Landmine press»." in r.text


def test_catalogo_de_tecnicas_editable(cliente, con):
    cliente.post("/rendimiento/catalogo/tecnicas", data={"disciplina": "judo", "familia": "ashi-waza", "nombre": "Kosoto gake especial"})
    assert q.buscar_tecnicas(con, "judo", "especial")[0]["familia"] == "ashi-waza"
    tid = q.buscar_tecnicas(con, "judo", "especial")[0]["id"]
    cliente.post(f"/rendimiento/catalogo/tecnicas/{tid}", data={"activo": "0"})
    assert q.buscar_tecnicas(con, "judo", "especial") == []
