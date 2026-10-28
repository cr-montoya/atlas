"""Requirement: Fotos antes y después."""

import io
import json
import shutil
import stat
import subprocess
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import Config
from app.modules.rendimiento import fotos as fx
from app.modules.rendimiento import rutas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
RAIZ = Path(__file__).resolve().parents[1]


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


def jpeg_con_gps(ancho=300, alto=400, orientacion=1) -> bytes:
    img = Image.new("RGB", (ancho, alto), (120, 90, 60))
    exif = Image.Exif()
    exif[0x0112] = orientacion                      # Orientation
    exif[0x010F] = "CamaraFicticia"                 # Make
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (6.0, 15.0, 0.0), "W", (75.0, 34.0, 0.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _subir(cliente, fecha="2026-10-17", pose="frente", datos=None, **extra):
    return cliente.post("/rendimiento/fotos", data={"fecha": fecha, "pose": pose, **extra},
                        files={"foto": ("foto.jpg", datos or jpeg_con_gps(), "image/jpeg")}, follow_redirects=False)


def test_subida_sin_gps_con_permisos_y_miniatura(cliente, con, config):
    assert Image.open(io.BytesIO(jpeg_con_gps())).getexif().get_ifd(0x8825)  # la original sí trae GPS
    r = _subir(cliente)
    assert r.status_code == 303
    archivo = config.fotos_path / "2026-10-17_frente.jpg"
    mini = config.fotos_path / "miniaturas" / "2026-10-17_frente.jpg"
    assert archivo.is_file() and mini.is_file()
    for p in (archivo, mini):
        assert stat.S_IMODE(p.stat().st_mode) == 0o600
        exif = Image.open(p).getexif()
        assert not exif.get_ifd(0x8825) and 0x010F not in exif and len(exif) == 0
    assert stat.S_IMODE(config.fotos_path.stat().st_mode) == 0o700
    assert max(Image.open(mini).size) <= fx.LADO_MINI
    f = fx.foto_por(con, "2026-10-17", "frente")
    assert f.archivo == "2026-10-17_frente.jpg"


def test_orientacion_aplicada_antes_de_quitar_el_exif(cliente, config):
    _subir(cliente, datos=jpeg_con_gps(300, 400, orientacion=6))  # 6 = rotada 90 grados
    assert Image.open(config.fotos_path / "2026-10-17_frente.jpg").size == (400, 300)


def test_misma_fecha_y_pose_reemplaza(cliente, con):
    _subir(cliente)
    _subir(cliente, datos=jpeg_con_gps(200, 200))
    assert len(fx.de_pose(con, "frente")) == 1 and fx.de_pose(con, "frente")[0].ancho == 200


def test_archivo_invalido_explica(cliente):
    r = _subir(cliente, datos=b"esto no es una foto")
    assert r.status_code == 422 and "No pude leer la foto" in r.text
    r = cliente.post("/rendimiento/fotos", data={"fecha": "2026-10-17", "pose": "lado"},
                     files={"foto": ("f.jpg", jpeg_con_gps(), "image/jpeg")})
    assert r.status_code == 422 and "Elige la pose" in r.text


def test_respuesta_json_para_la_camara(cliente):
    r = cliente.post("/rendimiento/fotos", data={"fecha": "2026-10-17", "pose": "espalda"},
                     files={"foto": ("f.jpg", jpeg_con_gps(), "image/jpeg")}, headers={"Accept": "application/json"})
    assert r.json()["ok"] is True and "pose=espalda" in r.json()["url"]


def test_guia_de_pose_con_la_foto_anterior(cliente, con):
    sin_anterior = cliente.get("/rendimiento/fotos/nueva?pose=frente").text
    assert 'class="guia"' not in sin_anterior and "Es tu primera foto de frente" in sin_anterior
    _subir(cliente, fecha="2026-09-01")
    f = fx.ultima(con, "frente")
    pagina = cliente.get("/rendimiento/fotos/nueva?pose=frente").text
    assert f'<img class="guia" src="/rendimiento/fotos/{f.id}/imagen"' in pagina  # silueta semitransparente
    assert "data-camara" in pagina and "data-opacidad" in pagina
    # Sin HTTPS: subida normal con la anterior al lado
    assert 'type="file"' in pagina and "Anterior: 1 sep 2026" in pagina and "necesita HTTPS" in pagina


def test_deslizador_con_medidas_cercanas(cliente, con):
    _subir(cliente, fecha="2026-08-20")  # cerca de la antropometría del 2026-08-18 del vault
    _subir(cliente, fecha="2026-10-17")
    fa, fb = fx.de_pose(con, "frente")
    pagina = cliente.get("/rendimiento/fotos?pose=frente").text
    assert "data-ad" in pagina and 'id="ad-rango"' in pagina
    assert f"/rendimiento/fotos/{fa.id}/imagen" in pagina and f"/rendimiento/fotos/{fb.id}/imagen" in pagina
    assert "83,25 kg" in pagina and "Antropometría, Yuhasz (Centro Uno)" in pagina  # peso más cercano a la primera
    assert "Sin medidas a 45 días de esta foto." in pagina                    # nada cerca de la segunda
    assert "data-linea" in pagina and "data-revelar" in pagina                # línea de tiempo y miniaturas borrosas


def test_imagen_detras_del_pin(app, cliente, con):
    _subir(cliente)
    f = fx.ultima(con, "frente")
    r = cliente.get(f"/rendimiento/fotos/{f.id}/imagen?mini=1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and "private" in r.headers["cache-control"]
    from fastapi.testclient import TestClient
    with TestClient(app) as anonimo:
        assert anonimo.get(f"/rendimiento/fotos/{f.id}/imagen", follow_redirects=False).status_code == 303


def test_borrar_quita_archivos(cliente, con, config):
    _subir(cliente)
    f = fx.ultima(con, "frente")
    cliente.post(f"/rendimiento/fotos/{f.id}/borrar")
    assert fx.ultima(con, "frente") is None
    assert not (config.fotos_path / f.archivo).exists() and not (config.fotos_path / "miniaturas" / f.archivo).exists()


def test_resumen_solo_fecha_y_pose(cliente, config):
    _subir(cliente)
    datos = json.loads((config.exports_path / "rendimiento-ia.json").read_text())
    assert datos["fotos"] == [{"fecha": "2026-10-17", "pose": "frente"}]
    assert "2026-10-17_frente.jpg" not in (config.exports_path / "rendimiento-ia.md").read_text()


def test_fotos_fuera_de_git():
    r = subprocess.run(["git", "-C", str(RAIZ), "check-ignore", "-q", "data/fotos/2026-10-17_frente.jpg"])
    assert r.returncode == 0
    r = subprocess.run(["git", "-C", str(RAIZ), "check-ignore", "-q", "data/fotos/miniaturas/2026-10-17_frente.jpg"])
    assert r.returncode == 0


# Galería y archivos: varias fotos, fecha en que se tomó cada una ---------

def jpeg_con_fecha(fecha_exif: str | None, ancho=300, alto=400) -> bytes:
    img = Image.new("RGB", (ancho, alto), (90, 120, 60))
    exif = Image.Exif()
    if fecha_exif:
        exif.get_ifd(0x8769)[0x9003] = fecha_exif      # DateTimeOriginal
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (6.0, 15.0, 0.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _lote(cliente, archivos, **extra):
    return cliente.post("/rendimiento/fotos", data={"pose": "frente", "fecha": "2026-10-17", **extra},
                        files=[("foto", (n, d, "image/jpeg")) for n, d in archivos], follow_redirects=False)


def test_fecha_tomada_del_exif():
    assert fx.fecha_tomada(jpeg_con_fecha("2025:03:02 08:15:00")) == "2025-03-02"
    assert fx.fecha_tomada(jpeg_con_fecha(None)) is None
    assert fx.fecha_tomada(jpeg_con_fecha("2099:01:01 00:00:00"), date(2026, 10, 17)) is None  # futuro: no creíble
    assert fx.fecha_tomada(jpeg_con_fecha("0000:00:00 00:00:00")) is None
    assert fx.fecha_tomada(b"no es imagen") is None


def test_varias_fotos_viejas_con_su_fecha(cliente, con, config):
    r = _lote(cliente, [("a.jpg", jpeg_con_fecha("2025:03:02 08:15:00")), ("b.jpg", jpeg_con_fecha("2025:06:01 09:00:00")),
                        ("c.jpg", jpeg_con_fecha(None))], fecha_de_la_foto="1")
    assert r.status_code == 303 and "ok=3" in r.headers["location"]
    assert [f.fecha for f in fx.de_pose(con, "frente")] == ["2025-03-02", "2025-06-01", "2026-10-17"]
    guardada = Image.open(config.fotos_path / "2025-03-02_frente.jpg")
    assert not guardada.getexif()  # la fecha se leyó antes; el archivo guardado no trae EXIF ni GPS
    pagina = cliente.get(r.headers["location"]).text
    assert "3 fotos guardadas: 2 mar 2025, 1 jun 2025 y 17 oct 2026" in pagina
    assert "2 con la fecha en que se tomó; 1 sin esa fecha, con la que elegiste" in pagina


def test_sin_usar_la_fecha_de_la_foto(cliente, con):
    _lote(cliente, [("a.jpg", jpeg_con_fecha("2025:03:02 08:15:00"))])
    assert [f.fecha for f in fx.de_pose(con, "frente")] == ["2026-10-17"]


def test_un_archivo_malo_no_tumba_el_lote(cliente, con):
    r = _lote(cliente, [("bien.jpg", jpeg_con_fecha("2025:03:02 08:15:00")), ("mal.heic", b"no es una foto")],
              fecha_de_la_foto="1")
    assert r.status_code == 303 and len(fx.de_pose(con, "frente")) == 1
    pagina = cliente.get(r.headers["location"]).text
    assert "No pude leer: mal.heic (No pude leer la foto." in pagina


def test_reemplazo_avisado_y_limite(cliente, con):
    _lote(cliente, [("a.jpg", jpeg_con_fecha("2025:03:02 08:15:00"))], fecha_de_la_foto="1")
    r = _lote(cliente, [("a2.jpg", jpeg_con_fecha("2025:03:02 18:00:00"))], fecha_de_la_foto="1")
    assert "Reemplacé 1 que ya existía con la misma fecha y pose" in cliente.get(r.headers["location"]).text
    r = _lote(cliente, [(f"{i}.jpg", jpeg_con_fecha(None)) for i in range(21)])
    assert r.status_code == 422 and "Sube hasta 20 fotos a la vez" in r.text


def test_galeria_sin_forzar_la_camara(cliente):
    pagina = cliente.get("/rendimiento/fotos/nueva?pose=frente").text
    assert "Desde la galería o tus archivos" in pagina and "o arrástralas aquí" in pagina
    entrada = pagina[pagina.index('name="foto"'):].split(">")[0]
    assert "multiple" in entrada and "capture" not in entrada
    assert 'name="fecha_de_la_foto" value="1" checked' in pagina
