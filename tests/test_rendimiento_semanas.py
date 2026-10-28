"""Requirement: Comparar semanas."""

import shutil
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import consultas as q
from app.modules.rendimiento import logica, rutas, semanas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
SALUD = ("day,steps,resting_hr,stress_avg,body_battery_high,sleep_h,deep_min,light_min,rem_min,awake_min,sleep_score,"
         "hrv_ms,hrv_status,intensity_min,vigorous_min\n")


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
    monkeypatch.setattr(rutas, "hoy", lambda: date(2026, 10, 17))


def _fuerza(con, fecha: str, kg: int, series: int = 10, reps: int = 10) -> int:
    sid = q.crear_sesion(con, fecha, "fuerza", "fuerza")
    ej = q.ejercicio_por_nombre(con, "Sentadilla trasera")["id"]
    for _ in range(series):
        q.agregar_serie(con, sid, ej, reps=reps, carga_g=kg * 1000)
    q.guardar_sesion(con, sid, duracion_s=3600, molestia=None, sensaciones=None, notas="", clave_importada=None)
    return sid


def _semanas_del_spec(con):
    # W41 (5 al 11 oct): 5 sesiones de 6.000 kg = 30.000 kg. W42 (12 al 18 oct): 4 de 6.500 kg = 26.000 kg.
    for d in ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"):
        _fuerza(con, d, 60)
    for d in ("2026-10-12", "2026-10-13", "2026-10-14", "2026-10-15"):
        _fuerza(con, d, 65)


def test_semana_contra_la_anterior(cliente, con, boveda):
    _semanas_del_spec(con)
    w41 = semanas.resumen(con, boveda, "2026-W41")
    w42 = semanas.resumen(con, boveda, "2026-W42")
    assert (w41.sesiones, w41.carga_g, w42.sesiones, w42.carga_g) == (5, 30_000_000, 4, 26_000_000)
    m = {x.nombre: x for x in semanas.comparar(w41, w42)}
    assert m["Sesiones"].delta.valor == -1 and m["Sesiones"].delta.clase == "neutro"
    d = m["Carga total"].delta
    assert (d.valor, logica.fmt_pct(d.pct_mil), d.clase) == (-4_000_000, "13,3 %", "neutro")
    pagina = cliente.get("/rendimiento/comparar", params={"a": "2026-W41", "b": "2026-W42"}).text
    assert "-1 sesión" in pagina and "-4.000 kg" in pagina and "-13,3 %" in pagina
    assert 'class="delta neutro"' in pagina


def test_por_defecto_semana_actual_contra_la_anterior(cliente):
    pagina = cliente.get("/rendimiento/comparar").text
    assert 'value="2026-W41" selected' in pagina and 'value="2026-W42" selected' in pagina


def test_color_por_direccion(con, boveda):
    csv = next((boveda / vault.GARMIN).glob("*salud*.csv"))
    filas = [f"2026-10-0{d},8000,56,30,80,7.0,60,300,80,20,75,70,BALANCED,10,0" for d in range(5, 10)]
    filas += [f"2026-10-1{d},8000,53,30,80,7.5,60,300,80,20,75,74,BALANCED,10,0" for d in range(2, 7)]
    csv.write_text(SALUD + "\n".join(filas) + "\n")
    m = {x.nombre: x for x in semanas.comparar(semanas.resumen(con, boveda, "2026-W41"), semanas.resumen(con, boveda, "2026-W42"))}
    assert m["FC en reposo promedio"].delta.valor == -3 and m["FC en reposo promedio"].delta.clase == "pos"
    assert m["Sueño promedio"].delta.clase == "pos" and m["HRV promedio"].delta.clase == "pos"


def test_sin_datos_de_sueno_es_sin_dato(cliente, con, boveda):
    w = semanas.resumen(con, boveda, "2026-W42")
    assert w.sueno_s is None and w.hrv_ms is None and w.pasos is None
    m = {x.nombre: x for x in semanas.comparar(semanas.resumen(con, boveda, "2026-W41"), w)}
    assert m["Sueño promedio"].delta is None
    pagina = cliente.get("/rendimiento/comparar", params={"a": "2026-W41", "b": "2026-W42"}).text
    assert "sin dato" in pagina and "0 h" not in pagina


def test_noche_cuenta_para_el_dia_en_que_termina(con, boveda):
    """El CSV de Garmin trae la noche en el día en que se despierta: el 2026-02-02 pertenece a la W06."""
    w = semanas.resumen(con, boveda, "2026-W06")
    assert w.sueno_s == round((7.25 * 3600 + 6.5 * 3600) / 2)


def test_sesion_vinculada_cuenta_una_vez_con_datos_del_reloj(con, boveda):
    sid = _fuerza(con, "2026-02-03", 50, series=2)
    with con:
        con.execute("UPDATE sesiones SET clave_importada = 'garmin|2026-02-03|12:17:00' WHERE id = ?", (sid,))
    w = semanas.resumen(con, boveda, "2026-W06")
    del_dia = [e for e in w.entrenos if e.fecha == "2026-02-03"]
    assert len(del_dia) == 2  # la fuerza vinculada (una vez) y la caminadora de Garmin
    fuerza = next(e for e in del_dia if e.disciplina == "fuerza")
    assert fuerza.sesion_id == sid and fuerza.duracion_s == 2478 and fuerza.fc_media == 104


def test_fc_dudosa_no_entra_a_zonas_y_las_zonas_son_estimadas(con, boveda):
    w = semanas.resumen(con, boveda, "2026-W02")  # 5 al 11 ene: judo con FC 92 el martes 6
    dudosa = next(e for e in w.entrenos if e.fecha == "2026-01-06")
    assert dudosa.fc_dudosa
    total_zonas = sum(w.zonas_s or [0])
    assert total_zonas == sum(e.duracion_s for e in w.entrenos if not e.fc_dudosa and e.fc_media and e.fc_media >= 97)
    assert w.zonas_s is None or w.zonas_estimadas


def test_no_entrenamiento_no_cuenta(con, boveda):
    w = semanas.resumen(con, boveda, "2026-W03")  # 12 al 18 ene: perfil genérico de Polar el sábado 17
    assert not any(e.fecha == "2026-01-17" and e.disciplina == "otro" for e in w.entrenos)


def test_molestia_promedio_y_series_por_grupo(con, boveda):
    sid = _fuerza(con, "2026-10-12", 60, series=3)
    with con:
        con.execute("UPDATE sesiones SET molestia_hombro = 4 WHERE id = ?", (sid,))
    sid2 = _fuerza(con, "2026-10-13", 60, series=2)
    with con:
        con.execute("UPDATE sesiones SET molestia_hombro = 2 WHERE id = ?", (sid2,))
    w = semanas.resumen(con, boveda, "2026-W42")
    assert w.molestia_mil == 3000 and w.series_grupo["piernas"] == 5
