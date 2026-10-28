"""Tablero Hoy y Requirement: Molestia del hombro."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import consultas as q
from app.modules.rendimiento import logica, rutas, tablero, vault
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


def _sesion(con, fecha, molestia, tipo="fuerza", disciplina="fuerza"):
    sid = q.crear_sesion(con, fecha, tipo, disciplina)
    q.guardar_sesion(con, sid, duracion_s=3600, molestia=molestia, sensaciones=None, notas="", clave_importada=None)
    return sid


@pytest.mark.parametrize("valores,alza", [
    ([2, 3, 5], True), ([5, 3, 2], False), ([2, 2, 3], False), ([1, 1, 1, 3, 4, 3], True), ([3, 2], False)])
def test_regla_de_tendencia(valores, alza):
    assert logica.molestia_al_alza(valores) is alza


def test_tendencia_al_alza_en_el_tablero(cliente, con):
    for fecha, m in (("2026-10-13", 2), ("2026-10-14", 3), ("2026-10-16", 5)):
        _sesion(con, fecha, m)
    pagina = cliente.get("/rendimiento").text
    assert "Si la molestia persiste, consúltalo con tu fisio u ortopedista" in pagina
    assert 'id="g-hombro"' in pagina  # se grafica en el tiempo


def test_sin_tendencia_no_muestra_el_aviso(cliente, con):
    for fecha, m in (("2026-10-13", 5), ("2026-10-14", 3), ("2026-10-16", 2)):
        _sesion(con, fecha, m)
    assert "Si la molestia persiste" not in cliente.get("/rendimiento").text


def test_tablero_semana_actual_frente_a_la_anterior(con, boveda):
    _sesion(con, "2026-10-06", None)
    _sesion(con, "2026-10-13", None)
    _sesion(con, "2026-10-14", None, "combate", "bjj")
    t = tablero.construir(con, boveda, HOY)
    assert (t["sa"].semana, t["sp"].semana) == ("2026-W42", "2026-W41")
    assert t["minutos"].cifra == "120" and t["minutos"].unidad == "de 60"
    assert t["combate"].cifra == "1" and t["por_disc_combate"] == {"BJJ": 1}
    dias = {c["n"]: c for c in t["cal"]["celdas"] if not c["fuera"]}
    assert dias[14]["sesiones"] == ["bjj"] and dias[17]["hoy"] and dias[18]["futuro"]
    assert t["cal"]["celdas"][0]["fuera"]  # octubre de 2026 empieza en jueves


def test_hitos(con, boveda):
    hitos = {h["nombre"]: h for h in tablero.construir(con, boveda, HOY)["hitos"]}
    assert hitos["Viaje a la costa"]["texto"] == "faltan 50 días" and hitos["Viaje a la costa"]["detalle"] == "6 al 16 de diciembre"
    assert hitos["Cirugía"]["texto"] == "en unos 76 días"
    assert hitos["Cirugía"]["detalle"] == "primer trimestre de 2027"


def test_estados_vacios(cliente):
    pagina = cliente.get("/rendimiento").text
    assert "Sin fuerza registrada esta semana." in pagina
    assert "Sin datos de Garmin en los últimos 60 días. Sincroniza para traerlos." in pagina
    assert "sin dato" in pagina and "Nunca se ha sincronizado" in pagina


def test_anio_de_calor(con, boveda):
    _sesion(con, "2026-10-13", None)
    anio = tablero.construir(con, boveda, HOY)["anio"]
    celda = next(c for c in anio["celdas"] if c["fecha"] == "2026-10-13")
    assert celda["min"] == 60 and celda["nivel"] == 3
    assert next(c for c in anio["celdas"] if c["fecha"] == "2026-10-20")["fuera"]


def test_calendario_navega_desde_el_primer_mes_con_datos(cliente, con, boveda):
    actual = tablero.calendario(con, boveda, HOY, date(2026, 10, 1))
    assert actual["titulo"] == "Octubre 2026" and actual["siguiente"] is None and actual["anterior"] == "2026-09"
    primero = tablero.calendario(con, boveda, HOY, date(2025, 3, 1))  # antes de los sensores: se ajusta al primer mes
    assert primero["titulo"] == "Enero 2026" and primero["anterior"] is None and primero["siguiente"] == "2026-02"
    assert primero["sesiones"] > 0
    futuro = tablero.calendario(con, boveda, HOY, date(2027, 5, 1))
    assert futuro["titulo"] == "Octubre 2026"
    r = cliente.get("/rendimiento/calendario?mes=2026-02")
    assert r.status_code == 200 and "Febrero 2026" in r.text and 'id="calendario"' in r.text
    assert 'hx-get="/rendimiento/calendario?mes=2026-01"' in r.text and 'hx-get="/rendimiento/calendario?mes=2026-03"' in r.text
    assert "Febrero 2026" in cliente.get("/rendimiento?mes=2026-02").text  # sin JavaScript, por enlace


def test_esenciales_de_los_ultimos_siete_dias(con, boveda):
    csv = next((boveda / vault.GARMIN).glob("*salud*.csv"))
    csv.write_text(csv.read_text() + "".join(f"2026-10-{d},8000,50,30,80,7.0,60,300,80,20,75,80,BALANCED,10,0\n" for d in range(10, 17)))
    t = tablero.construir(con, boveda, date(2026, 10, 19))  # lunes: la semana actual aún no tiene datos
    sueno, hrv, fc, pasos = (a for _, _, a in t["esenciales"])
    assert (sueno.cifra, hrv.cifra, fc.cifra, pasos.cifra) == ("7", "80", "50", "8")
    assert t["ventana_salud"] == ("2026-10-10", "2026-10-16")
