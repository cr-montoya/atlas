"""Requirement: Registro de combate técnico-táctico."""

import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import actividades as act
from app.modules.rendimiento import consultas as q
from app.modules.rendimiento import rutas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
HOY = date(2026, 10, 17)
HX = {"HX-Request": "true"}


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


def _nueva(cliente) -> int:
    r = cliente.post("/rendimiento/sesiones", data={"tipo": "combate"}, follow_redirects=False)
    return int(re.search(r"/sesiones/(\d+)", r.headers["location"]).group(1))


def _bloque(cliente, con, sid, tipo) -> int:
    r = cliente.post(f"/rendimiento/sesiones/{sid}/bloques", data={"tipo": tipo}, headers=HX)
    assert r.status_code == 200
    return con.execute("SELECT MAX(id) FROM combate_bloques WHERE sesion_id = ?", (sid,)).fetchone()[0]


def _tecnica(con, disciplina, nombre) -> int:
    return con.execute("SELECT id FROM tecnicas WHERE disciplina = ? AND nombre = ?", (disciplina, nombre)).fetchone()[0]


def test_judo_tecnico(cliente, con):
    sid = _nueva(cliente)
    assert q.sesion(con, sid)["disciplina"] == "judo"
    bid = _bloque(cliente, con, sid, "tecnica")
    cliente.post(f"/rendimiento/bloques/{bid}", data={"duracion_min": "30"}, headers=HX)
    for nombre in ("Uchi mata", "Kumikata: agarre cruzado"):
        r = cliente.post(f"/rendimiento/bloques/{bid}/entradas", data={"tecnica_id": _tecnica(con, "judo", nombre)}, headers=HX)
        assert nombre in r.text
    (b,) = q.bloques_combate(con, sid)
    assert b.bloque["tipo"] == "tecnica" and b.bloque["duracion_s"] == 1800
    assert [(e["tecnica"], e["familia"], e["resultado"]) for e in b.entradas] == [
        ("Uchi mata", "ashi-waza", "trabajada"), ("Kumikata: agarre cruzado", "kumikata", "trabajada")]
    cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={})
    assert q.sesion(con, sid)["duracion_s"] == 1800  # sin reloj, la duración es la suma de los bloques


def test_randori_con_resultados(cliente, con):
    sid = _nueva(cliente)
    bid = _bloque(cliente, con, sid, "randori")
    assert q.bloque_combate(con, bid)["rounds"] == 5
    cliente.post(f"/rendimiento/bloques/{bid}", data={"rounds": "5", "duracion_min": "25", "rival": ["más pesado"]}, headers=HX)
    cliente.post(f"/rendimiento/bloques/{bid}/entradas", headers=HX, data={
        "tecnica_id": _tecnica(con, "judo", "O uchi gari"), "resultado": "funciono", "detalle": "o-uchi-gari a o-soto-gari"})
    cliente.post(f"/rendimiento/bloques/{bid}/entradas", headers=HX, data={"situacion": "agarre"})
    agarre = con.execute("SELECT id FROM combate_tecnicas WHERE situacion = 'agarre'").fetchone()[0]
    r = cliente.post(f"/rendimiento/entradas/{agarre}", headers=HX,
                     data={"resultado": "no_funciono", "detalle": "salidas de agarre contra zurdo"})
    assert r.status_code == 200
    (b,) = q.bloques_combate(con, sid)
    assert b.rivales == ["más pesado"] and b.bloque["rounds"] == 5
    filas = {(e["tecnica"], e["situacion"], e["resultado"], e["detalle"]) for e in b.entradas}
    assert filas == {("O uchi gari", None, "funciono", "o-uchi-gari a o-soto-gari"),
                     (None, "agarre", "no_funciono", "salidas de agarre contra zurdo")}
    pagina = cliente.get(f"/rendimiento/sesiones/{sid}").text
    assert "salidas de agarre contra zurdo" in pagina and "Más pesado" in pagina
    # Auditoría 7.2: los títulos no saltan de h1 a h3
    assert pagina.index('<h2 class="oculto">Bloques</h2>') < pagina.index("<h3>")


def test_resultado_solo_en_randori_y_situacional(cliente, con):
    sid = _nueva(cliente)
    tecnica = _bloque(cliente, con, sid, "tecnica")
    r = cliente.post(f"/rendimiento/bloques/{tecnica}/entradas", data={"tecnica_id": _tecnica(con, "judo", "Seoi nage")}, headers=HX)
    assert "Funcionó" not in r.text and "Rival" not in r.text
    situacional = _bloque(cliente, con, sid, "situacional")
    r = cliente.post(f"/rendimiento/bloques/{situacional}/entradas", data={"situacion": "entradas"}, headers=HX)
    assert "Funcionó" in r.text and "Rival" in r.text


def test_buscador_de_tecnicas_y_recientes(cliente, con):
    sid = _nueva(cliente)
    bid = _bloque(cliente, con, sid, "tecnica")
    r = cliente.get(f"/rendimiento/bloques/{bid}/tecnicas", params={"q": "uchi"})
    assert "Uchi mata" in r.text and "O uchi gari" in r.text and "Armbar" not in r.text
    assert "Sin coincidencias" in cliente.get(f"/rendimiento/bloques/{bid}/tecnicas", params={"q": "zzz"}).text
    cliente.post(f"/rendimiento/bloques/{bid}/entradas", data={"tecnica_id": _tecnica(con, "judo", "Tai otoshi")}, headers=HX)
    assert [t["nombre"] for t in q.buscar_tecnicas(con, "judo")] == ["Tai otoshi"]  # recientes primero


def test_catalogo_por_disciplina(cliente, con):
    sid = _nueva(cliente)
    cliente.post(f"/rendimiento/sesiones/{sid}/disciplina", data={"disciplina": "bjj"})
    bid = _bloque(cliente, con, sid, "drill")
    r = cliente.get(f"/rendimiento/bloques/{bid}/tecnicas", params={"q": "guardia"})
    assert "Guardia cerrada" in r.text and "Uchi mata" not in r.text
    r = cliente.post(f"/rendimiento/sesiones/{sid}/disciplina", data={"disciplina": "karate"})
    assert r.status_code == 422 and "Elige judo, BJJ o Muay Thai." in r.text


def test_entrada_vacia_explica(cliente, con):
    sid = _nueva(cliente)
    bid = _bloque(cliente, con, sid, "tecnica")
    r = cliente.post(f"/rendimiento/bloques/{bid}/entradas", data={}, headers=HX)
    assert r.status_code == 422 and "Elige una técnica o una situación" in r.text


def test_borrar_bloque(cliente, con):
    sid = _nueva(cliente)
    bid = _bloque(cliente, con, sid, "drill")
    r = cliente.post(f"/rendimiento/bloques/{bid}/borrar", headers=HX)
    assert r.status_code == 200 and f'id="bl-{bid}" hidden' in r.text
    assert q.bloques_combate(con, sid) == []


def test_vincular_con_polar_confirma_judo_o_bjj(cliente, con, boveda):
    csv = next((boveda / vault.POLAR).glob("*.csv"))
    csv.write_text(csv.read_text() + "2026-10-17,10:00:00,Judo,5400,,141,182,900,,\n")
    sid = _nueva(cliente)
    cliente.post(f"/rendimiento/sesiones/{sid}/disciplina", data={"disciplina": "bjj"})
    pagina = cliente.get(f"/rendimiento/sesiones/{sid}").text
    assert "Vincular con Judo de Polar a las 10:00" in pagina
    cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={"vincular": "polar|2026-10-17|10:00:00"})
    a = act.por_clave(con, boveda, "polar|2026-10-17|10:00:00")
    assert a.disciplina == "bjj" and a.sugerencia is None and vault.AVISO_JUDO_BJJ not in a.avisos
    assert q.sesion(con, sid)["duracion_s"] == 5400
