"""Requirement: Registro de sesión de fuerza."""

import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import consultas as q
from app.modules.rendimiento import logica, rutas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
HOY = date(2026, 10, 17)
FUERZA_GARMIN = "| 2026-10-17 | sáb | 11:05 | Fuerza | 62,4 | 21,0 | - | 112 | 161 | 210 |\n"


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
    r = cliente.post("/rendimiento/sesiones", data={"tipo": "fuerza"}, follow_redirects=False)
    assert r.status_code == 303
    return int(re.search(r"/sesiones/(\d+)", r.headers["location"]).group(1))


def _ej(con, nombre) -> int:
    return q.ejercicio_por_nombre(con, nombre)["id"]


HX = {"HX-Request": "true"}


def test_sesion_rapida_4x6_100kg(cliente, con):
    sid = _nueva(cliente)
    sentadilla = _ej(con, "Sentadilla trasera")
    r = cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": sentadilla}, headers=HX)
    assert r.status_code == 200 and "Sentadilla trasera" in r.text
    primera = con.execute("SELECT id FROM series WHERE sesion_id = ?", (sid,)).fetchone()[0]
    r = cliente.post(f"/rendimiento/series/{primera}", data={"reps": "6", "carga": "100", "rpe": "8"}, headers=HX)
    assert r.status_code == 200
    for _ in range(3):  # cada serie nueva copia la anterior
        cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios/{sentadilla}/serie", headers=HX)
    series = con.execute("SELECT reps, carga_g, rpe_x10 FROM series WHERE sesion_id = ? ORDER BY orden", (sid,)).fetchall()
    assert [tuple(s) for s in series] == [(6, 100_000, 80)] * 4
    assert q.carga_total_sesion(con, sid) == 2_400_000
    pagina = cliente.get(f"/rendimiento/sesiones/{sid}").text
    assert "2.400 kg" in pagina and 'id="total-sesion"' in pagina


def test_respuesta_htmx_actualiza_el_total_fuera_de_banda(cliente, con):
    sid = _nueva(cliente)
    r = cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": _ej(con, "Prensa")}, headers=HX)
    assert 'id="total-sesion" class="total-sesion" hx-swap-oob="true"' in r.text


def test_aviso_de_hombro_y_puede_continuar(cliente, con):
    sid = _nueva(cliente)
    press = _ej(con, "Press militar")
    r = cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": press}, headers=HX)
    assert "Ejercicio que carga el hombro: revisa las indicaciones de tu ortopedista y fisio" in r.text
    r = cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios/{press}/serie", headers=HX)
    assert r.status_code == 200
    assert con.execute("SELECT COUNT(*) FROM series WHERE sesion_id = ?", (sid,)).fetchone()[0] == 2
    sentadilla = cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": _ej(con, "Sentadilla trasera")}, headers=HX)
    assert "carga el hombro" not in sentadilla.text


def test_vinculo_con_garmin_del_mismo_dia(cliente, con, boveda):
    archivo = next((boveda / vault.GARMIN).glob("*actividades*.md"))
    texto = archivo.read_text()
    archivo.write_text(texto.replace("\n## Totales", FUERZA_GARMIN + "\n## Totales"))
    sid = _nueva(cliente)
    cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": _ej(con, "Peso muerto")})
    pagina = cliente.get(f"/rendimiento/sesiones/{sid}").text
    assert "Vincular con Fuerza de Garmin a las 11:05" in pagina
    r = cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={"vincular": "garmin|2026-10-17|11:05:00"},
                     follow_redirects=False)
    assert r.status_code == 303
    s = q.sesion(con, sid)
    assert s["clave_importada"] == "garmin|2026-10-17|11:05:00" and s["guardada"] == 1
    assert s["duracion_s"] == 3744  # 62,4 min de Garmin
    hecho = cliente.get(r.headers["location"]).text
    assert "Vinculada con Fuerza de Garmin" in hecho and "FC media 112" in hecho and "1 h 2 min" in hecho
    otra = _nueva(cliente)
    assert "Vincular con" not in cliente.get(f"/rendimiento/sesiones/{otra}").text  # ya está tomada


def test_no_vincular(cliente, con, boveda):
    archivo = next((boveda / vault.GARMIN).glob("*actividades*.md"))
    archivo.write_text(archivo.read_text().replace("\n## Totales", FUERZA_GARMIN + "\n## Totales"))
    sid = _nueva(cliente)
    cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={"vincular": "", "duracion_min": "55", "molestia": "3"})
    s = q.sesion(con, sid)
    assert s["clave_importada"] is None and s["duracion_s"] == 3300 and s["molestia_hombro"] == 3


def test_tipo_de_carga_dominadas_con_lastre(cliente, con):
    """Peso corporal más reciente del vault (83,25 kg) + 10 kg de lastre, 3 x 5."""
    sid = _nueva(cliente)
    dominadas = _ej(con, "Dominadas")
    cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": dominadas}, headers=HX)
    primera = con.execute("SELECT id, peso_corporal_g FROM series WHERE sesion_id = ?", (sid,)).fetchone()
    assert primera["peso_corporal_g"] == 83_250
    cliente.post(f"/rendimiento/series/{primera['id']}", data={"reps": "5", "carga": "10"}, headers=HX)
    for _ in range(2):
        cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios/{dominadas}/serie", headers=HX)
    assert q.carga_total_sesion(con, sid) == 1_398_750
    assert logica.fmt_kg(1_398_750) == "1.398,75 kg"


@pytest.mark.parametrize("tipo,esperado", [
    ("barra", 600_000), ("maquina", 600_000), ("mancuerna_una", 600_000),
    ("mancuerna_par", 1_200_000), ("unilateral", 1_200_000),
    ("peso_corporal", 499_500), ("peso_corporal_lastre", 1_099_500),
])
def test_carga_por_tipo(tipo, esperado):
    assert logica.carga_serie_g(tipo, 6, 100_000, 83_250) == esperado


def test_peso_corporal_sin_dato_no_inventa_carga():
    assert logica.carga_serie_g("peso_corporal", 10, 0, None) is None


def test_repetir_la_sesion_anterior(cliente, con):
    sid = _nueva(cliente)
    cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": _ej(con, "Sentadilla trasera")})
    cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": _ej(con, "Press banca")})
    cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={})
    nueva = _nueva(cliente)
    assert nueva != sid
    assert "Repetir la sesión anterior" in cliente.get(f"/rendimiento/sesiones/{nueva}").text
    cliente.post(f"/rendimiento/sesiones/{nueva}/repetir")
    nombres = [b.ejercicio["nombre"] for b in q.bloques(con, nueva)]
    assert nombres == ["Sentadilla trasera", "Press banca"]
    assert "Repetir la sesión anterior" not in cliente.get(f"/rendimiento/sesiones/{nueva}").text


def test_borrador_de_hoy_se_continua(cliente):
    assert _nueva(cliente) == _nueva(cliente)
    assert "Continuar la de hoy" in cliente.get("/rendimiento/registrar").text


def test_controles_de_mas_y_menos(cliente, con):
    sid = _nueva(cliente)
    cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": _ej(con, "Hip thrust")})
    serie_id = con.execute("SELECT id FROM series WHERE sesion_id = ?", (sid,)).fetchone()[0]
    cliente.post(f"/rendimiento/series/{serie_id}/ajustar?campo=carga&paso=1", headers=HX)
    cliente.post(f"/rendimiento/series/{serie_id}/ajustar?campo=carga&paso=1", headers=HX)
    cliente.post(f"/rendimiento/series/{serie_id}/ajustar?campo=reps&paso=-1", headers=HX)
    s = q.serie(con, serie_id)
    assert (s["reps"], s["carga_g"]) == (q.REPS_DEFECTO - 1, 5_000)
    for _ in range(3):
        cliente.post(f"/rendimiento/series/{serie_id}/ajustar?campo=carga&paso=-1", headers=HX)
    assert q.serie(con, serie_id)["carga_g"] == 0


def test_carga_invalida_explica_como_arreglarla(cliente, con):
    sid = _nueva(cliente)
    cliente.post(f"/rendimiento/sesiones/{sid}/ejercicios", data={"ejercicio_id": _ej(con, "Prensa")})
    serie_id = con.execute("SELECT id FROM series WHERE sesion_id = ?", (sid,)).fetchone()[0]
    r = cliente.post(f"/rendimiento/series/{serie_id}", data={"reps": "8", "carga": "cien"}, headers=HX)
    assert r.status_code == 422 and "Escribe la carga en kg, por ejemplo 100 o 22,5." in r.text


def test_molestia_fuera_de_rango(cliente):
    sid = _nueva(cliente)
    r = cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={"molestia": "11"})
    assert r.status_code == 422 and "La molestia del hombro va de 0 a 10." in r.text


@pytest.mark.parametrize("texto,g", [("100", 100_000), ("22,5", 22_500), ("22.5", 22_500), ("", 0), ("1.000", 1_000_000)])
def test_parse_kg(texto, g):
    assert logica.parse_kg(texto) == g


@pytest.mark.parametrize("s,texto", [(2478, "41,3 min"), (3744, "1 h 2 min"), (3600, "1 h"), (None, "sin dato")])
def test_fmt_duracion(s, texto):
    assert logica.fmt_duracion(s) == texto
