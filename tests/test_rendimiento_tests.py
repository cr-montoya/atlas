"""Requirement: Tests del gimnasio."""

import shutil
import tomllib
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import carga_tests, evaluaciones as ev, logica, rutas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos"


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS / "vault", destino)
    vault.limpiar_cache()
    return destino


@pytest.fixture
def config(tmp_path, boveda):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db",
                  exports_path=tmp_path / "exports", vault_path=boveda, fotos_path=tmp_path / "fotos")


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: date(2026, 10, 20))


def _ejemplo():
    with (DATOS / "tests.example.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_cmj_historico_del_vault(con, boveda):
    cmj = ev.serie(ev.todas(con, boveda), "cmj", "CMJ")
    assert [v.valor_mil for _, v in cmj] == [45_100, 51_950]
    c = ev.comparar(cmj[0][0], cmj[1][0])
    d = c.filas[0].delta
    assert (logica.fmt_decimal(d.valor), d.signo, logica.fmt_pct(d.pct_mil), d.clase) == ("6,85", "+", "15,2 %", "pos")


def test_pagina_de_tests_con_historico(cliente):
    r = cliente.get("/rendimiento/tests")
    assert r.status_code == 200
    assert "51,95" in r.text and "~ene 2025" in r.text and "+6,85 cm" in r.text and "+15,2 %" in r.text


def test_test_nuevo_frente_al_mejor(cliente, con, boveda):
    r = cliente.post("/rendimiento/tests", data={"tipo": "cmj", "fecha": "2026-10-20", "v0": "50,2"}, follow_redirects=False)
    assert r.status_code == 303
    cmj = ev.serie(ev.todas(con, boveda), "cmj", "CMJ")
    assert [v.valor_mil for _, v in cmj] == [45_100, 51_950, 50_200]
    pagina = cliente.get("/rendimiento/tests").text
    assert "-1,75 cm frente al mejor" in pagina and "Mejor: 51,95 cm" in pagina
    assert '"v": 45100' in pagina and '"v": 51950' in pagina and '"v": 50200' in pagina  # la serie de los tres


def test_fecha_invalida_explica(cliente):
    r = cliente.post("/rendimiento/tests", data={"tipo": "cmj", "fecha": "ayer", "v0": "50"})
    assert r.status_code == 422 and "La fecha va como 2026-10-20" in r.text


def test_antropometria_mismo_metodo_y_metodo_distinto(cliente, con, boveda):
    metodo = "Antropometría, Yuhasz (Centro Uno)"
    cliente.post("/rendimiento/tests", data={"tipo": "antropometria", "fecha": "2026-10-20", "metodo": metodo,
                                             "v0": "82,5", "v1": "13,68", "v3": "87"})
    meds = ev.todas(con, boveda)
    antro = [m for m in meds if m.tipo == "antropometria"]
    base = next(m for m in antro if m.fecha == "2026-08-18")
    nueva = next(m for m in antro if m.fecha == "2026-10-20")
    c = ev.comparar(base, nueva)
    filas = {f.medida: f for f in c.filas}
    assert not c.metodo_distinto
    assert filas["Peso"].delta.valor == -750 and filas["% graso"].delta.valor == -620
    assert filas["Suma 6 pliegues"].delta.valor == -5_000 and filas["Suma 6 pliegues"].delta.clase == "pos"
    d04 = next(m for m in antro if m.metodo == "Documento nutricional D04")
    distinta = ev.comparar(d04, nueva)
    assert distinta.metodo_distinto and all(f.delta is None for f in distinta.filas)
    serie = ev.serie(meds, "antropometria", "% graso", metodo)
    assert [m.fecha for m, _ in serie] == ["2026-08-18", "2026-10-20"]  # el D04 no entra en la serie
    r = cliente.get("/rendimiento/tests/comparar", params={"tipo": "antropometria", "a": f"antropometria|2025-08-20|vault|",
                                                            "b": f"antropometria|2026-10-20|app|{nueva.test_id}"})
    assert "Método distinto" in r.text and "método distinto" in r.text


def test_radar_con_tres_tests_de_dos_fechas(cliente, con, boveda):
    carga_tests.cargar(con, _ejemplo(), "ejemplo")
    dims = {d.nombre: d for d in ev.radar(ev.todas(con, boveda))}
    assert set(dims) == {"CMJ", "Dina.", "6 min"}  # la VMP a 45 kg no tiene dos fechas en el ejemplo
    cmj = dims["CMJ"]
    assert cmj.ultima == ("2025-09-01", 52_000) and cmj.pct_ultima == 100
    assert cmj.pct_anterior == round(100 * 50_500 / 52_000)
    assert len(dims) >= 3
    pagina = cliente.get("/rendimiento/tests").text
    assert 'id="g-radar"' in pagina and "100 = tu mejor marca" in pagina


def test_radar_normaliza_segun_direccion():
    m1 = ev.Medicion("sprint", "2026-01-01", valores={"Tiempo": ev.Valor("Tiempo", 4_200, "s", "menos")})
    m2 = ev.Medicion("sprint", "2026-03-01", valores={"Tiempo": ev.Valor("Tiempo", 4_000, "s", "menos")})
    (d,) = ev.radar([m1, m2])
    assert (d.pct_anterior, d.pct_ultima) == (round(100 * 4_000 / 4_200), 100)  # en un sprint, el menor tiempo es el 100 %


def test_carga_desde_archivo_es_idempotente_y_oculta_el_vault_del_mismo_mes(con, boveda):
    datos = {"fuente": {"evaluador": "X"}, "evaluacion": [{"fecha": "2025-01-30", "cmj_cm": "45,13"},
                                                         {"fecha": "2025-03-28", "cmj_cm": "51,95"}]}
    carga_tests.cargar(con, datos, "local")
    carga_tests.cargar(con, datos, "local")
    assert con.execute("SELECT COUNT(*) FROM tests").fetchone()[0] == 2
    cmj = ev.serie(ev.todas(con, boveda), "cmj", "CMJ")
    assert [(m.fecha, m.origen, v.valor_mil) for m, v in cmj] == [("2025-01-30", "local", 45_130), ("2025-03-28", "local", 51_950)]


def test_carga_del_ejemplo(con):
    hechos = carga_tests.cargar(con, _ejemplo(), "ejemplo")
    assert "2025-05-01 carga_velocidad" in hechos and "2025-02-01 movilidad" in hechos
    curvas = ev.curvas_carga_velocidad(ev._de_bd(con))
    assert curvas[0] == {"fecha": "2025-05-01", "puntos": [(15, 1_900), (25, 1_600), (35, 1_500)]}
