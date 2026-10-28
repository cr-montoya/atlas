"""Requirement: Resumen para IA de rendimiento."""

import json
import re
import shutil
import stat
from datetime import date
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import consultas as q
from app.modules.rendimiento import resumen_ia, rutas, vault
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


def _judo(cliente, con) -> int:
    r = cliente.post("/rendimiento/sesiones", data={"tipo": "combate"}, follow_redirects=False)
    sid = int(re.search(r"/sesiones/(\d+)", r.headers["location"]).group(1))
    cliente.post(f"/rendimiento/sesiones/{sid}/bloques", data={"tipo": "tecnica"}, headers=HX)
    bid = con.execute("SELECT MAX(id) FROM combate_bloques").fetchone()[0]
    uchi = con.execute("SELECT id FROM tecnicas WHERE nombre = 'Uchi mata'").fetchone()[0]
    cliente.post(f"/rendimiento/bloques/{bid}/entradas", data={"tecnica_id": uchi}, headers=HX)
    cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={"molestia": "2"})
    return sid


def test_despues_de_guardar_una_sesion_de_judo(cliente, con, config):
    sid = _judo(cliente, con)
    js = config.exports_path / "rendimiento-ia.json"
    md = config.exports_path / "rendimiento-ia.md"
    datos = json.loads(js.read_text())
    assert datos["schema_version"] == "1" and datos["fuente"] == "[app rendimiento 2026-10-17 | alta]"
    s = next(x for x in datos["sesiones"] if x["id"] == sid)
    assert s["disciplina"] == "judo" and s["molestia_hombro"] == 2
    assert s["bloques"][0]["tipo"] == "tecnica" and s["bloques"][0]["entradas"][0]["tecnica"] == "Uchi mata"
    texto = md.read_text()
    assert "- [M] 2026-10-17 Judo" in texto and "[app rendimiento 2026-10-17 | alta]" in texto
    assert "Uchi mata" in texto and "—" not in texto
    assert stat.S_IMODE(js.stat().st_mode) == 0o600


def test_se_regenera_al_guardar_un_test(cliente, config):
    cliente.post("/rendimiento/tests", data={"tipo": "cmj", "fecha": "2026-10-17", "v0": "50,2"})
    datos = json.loads((config.exports_path / "rendimiento-ia.json").read_text())
    (t,) = datos["tests"]
    assert t["tipo"] == "cmj" and t["valores"][0]["valor_mil"] == 50_200 and t["origen"] == "app"


def test_fuerza_con_series_y_carga(cliente, con, config):
    r = cliente.post("/rendimiento/sesiones", data={"tipo": "fuerza"}, follow_redirects=False)
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    ej = q.ejercicio_por_nombre(con, "Sentadilla trasera")["id"]
    for _ in range(4):
        q.agregar_serie(con, sid, ej, reps=6, carga_g=100_000, rpe_x10=80)
    cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={})
    datos = json.loads((config.exports_path / "rendimiento-ia.json").read_text())
    s = next(x for x in datos["sesiones"] if x["id"] == sid)
    assert s["carga_total_g"] == 2_400_000 and len(s["ejercicios"][0]["series"]) == 4
    assert "Sentadilla trasera: 6x100 RPE 8, 6x100 RPE 8" in (config.exports_path / "rendimiento-ia.md").read_text()


def test_sin_imagenes(con, boveda):
    with con:
        con.execute("INSERT INTO fotos_cuerpo (fecha, pose, archivo, ancho, alto) VALUES ('2026-10-17', 'frente', '2026-10-17_frente.jpg', 900, 1200)")
    datos = resumen_ia.construir(con, boveda, HOY)
    assert datos["fotos"] == [{"fecha": "2026-10-17", "pose": "frente"}]
    assert "2026-10-17_frente.jpg" not in json.dumps(datos) and "2026-10-17_frente.jpg" not in resumen_ia.markdown(datos)


def test_avisos(con, boveda):
    for fecha, m in (("2026-10-13", 2), ("2026-10-14", 3), ("2026-10-16", 5)):
        sid = q.crear_sesion(con, fecha, "fuerza", "fuerza")
        q.guardar_sesion(con, sid, duracion_s=3600, molestia=m, sensaciones=None, notas="", clave_importada=None)
    avisos = " ".join(resumen_ia.construir(con, boveda, HOY)["avisos"])
    assert "Molestia del hombro al alza" in avisos and "Datos de Garmin hasta 2026-02-05" in avisos
