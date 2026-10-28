"""Spec openspec/changes/v1-registro-por-voz. Transcriptor falso (nunca carga Whisper) y Claude falso
(tests/claude_falso.py, nunca llama a Anthropic). Hoy es jueves 2026-10-22 a las 20:00."""

import json
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Config
from app.main import crear_app
from app.modules.rendimiento import actividades as act
from app.modules.rendimiento import nutricion as nu
from app.modules.rendimiento import rutas, vault, voz
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
FALSO = Path(__file__).parent / "claude_falso.py"
HOY = date(2026, 10, 22)
MIXTO = ("almorcé arroz con pollo a la una, llevo seis vasos de agua, y en la noche judo hora y media: técnica veinte "
         "minutos de uchi mata, randori cinco rounds, me entró el uchi mata dos veces")


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    vault.limpiar_cache()
    return destino


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


@pytest.fixture
def config(tmp_path, boveda, home):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "data" / "prueba.db",
                  exports_path=tmp_path / "exports", vault_path=boveda, fotos_path=tmp_path / "fotos",
                  claude_cmd=str(FALSO), tiempo_max_voz_s=20)


@pytest.fixture(autouse=True)
def reloj(monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: HOY)
    monkeypatch.setattr(voz, "_ahora", lambda: datetime(2026, 10, 22, 20, 0))
    monkeypatch.setattr(voz, "EN_HILO", False)


@pytest.fixture
def transcripcion(monkeypatch):
    """Transcriptor falso: devuelve el texto fijado y anota el PCM que recibió."""
    estado = {"texto": "", "llamadas": 0}

    def falso(cfg, pcm, pista):
        estado["llamadas"] += 1
        estado["pcm"] = len(pcm)
        return estado["texto"]
    monkeypatch.setattr(voz, "whisper", falso)
    return estado


@pytest.fixture
def cliente(config):
    app = crear_app(config)
    with TestClient(app) as c:
        assert c.post("/login", data={"pin": PIN}, follow_redirects=False).status_code == 303
        yield c


def responde(home: Path, *respuestas, **extra):
    (home / "modo_claude.json").write_text(json.dumps({"respuestas": list(respuestas), **extra}, ensure_ascii=False))


def llamadas(home: Path) -> list[dict]:
    ruta = home / "llamadas_claude.jsonl"
    return [json.loads(l) for l in ruta.read_text().splitlines()] if ruta.is_file() else []


def agregar_polar(boveda: Path, *filas: str) -> None:
    csv = next((boveda / vault.POLAR).glob("*.csv"))
    csv.write_text(csv.read_text() + "".join(f + "\n" for f in filas))
    vault.limpiar_cache()


def entrada(con, eid):
    return voz.entrada(con, eid)


def items(con, eid):
    return voz.borrador(entrada(con, eid))["items"]


def enviar(cliente, texto):
    r = cliente.post("/rendimiento/voz", data={"texto": texto}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[1].split("?")[0])


def form_de(cliente, eid) -> dict:
    """Los campos del formulario del borrador tal como los muestra la página (valores por defecto)."""
    import re
    from html import unescape
    html = cliente.get(f"/rendimiento/voz/{eid}").text
    datos: dict = {}
    for m in re.finditer(r'<input[^>]*name="(\d+\.[^"]+)"[^>]*>', html):
        tag = m.group(0)
        if 'type="checkbox"' in tag or 'type="radio"' in tag:
            if "checked" in tag:
                datos[m.group(1)] = unescape(re.search(r'value="([^"]*)"', tag).group(1))
            continue
        v = re.search(r'value="([^"]*)"', tag)
        datos[m.group(1)] = unescape(v.group(1)) if v else ""
    for m in re.finditer(r'<select name="(\d+\.[^"]+)">(.*?)</select>', html, re.S):
        sel = re.search(r'<option value="([^"]*)" selected>', m.group(2))
        datos[m.group(1)] = unescape(sel.group(1)) if sel else ""
    for m in re.finditer(r'<textarea name="(\d+\.[^"]+)"[^>]*>(.*?)</textarea>', html, re.S):
        datos[m.group(1)] = unescape(m.group(2))
    return datos


# Respuestas de Claude de los escenarios -------------------------------------

def r_mixto(hora="13:00", intercambios=None):
    return {"items": [
        {"tipo": "comida", "indice": None, "cita": "almorcé arroz con pollo a la una", "fecha": None, "momento": "almuerzo",
         "hora": hora, "franja": None, "texto": "arroz con pollo", "intercambios": intercambios or {}, "segun_plan": False},
        {"tipo": "agua", "indice": None, "cita": "llevo seis vasos de agua", "fecha": None, "vasos": 6, "modo": "total"},
        {"tipo": "combate", "indice": None, "cita": "en la noche judo hora y media", "fecha": None, "hora": None,
         "franja": "noche", "duracion_min": 90, "sensaciones": None, "molestia_hombro": None, "notas": None,
         "disciplina": "judo", "bloques": [
             {"tipo": "tecnica", "duracion_min": 20, "rounds": None, "cita": "técnica veinte minutos de uchi mata",
              "entradas": [{"nombre_dicho": "uchi mata", "catalogo": "Uchi mata", "situacion": None,
                            "resultado": "trabajada", "detalle": None}]},
             {"tipo": "randori", "duracion_min": None, "rounds": 5,
              "cita": "randori cinco rounds, me entró el uchi mata dos veces",
              "entradas": [{"nombre_dicho": "uchi mata", "catalogo": "Uchi mata", "situacion": None,
                            "resultado": "funciono", "detalle": "2 veces"}]}]},
    ], "pregunta": None}


def r_fuerza(cita, ejercicios, duracion=None, hora=None, franja=None, fecha=None):
    return {"items": [{"tipo": "fuerza", "indice": None, "cita": cita, "fecha": fecha, "hora": hora, "franja": franja,
                       "duracion_min": duracion, "sensaciones": None, "molestia_hombro": None, "notas": None,
                       "ejercicios": ejercicios}], "pregunta": None}


def ej(nombre_dicho, catalogo, cita, *series):
    return {"nombre_dicho": nombre_dicho, "catalogo": catalogo, "cita": cita,
            "series": [{"reps": r, "carga_kg": c, "rpe": p} for r, c, p in series]}


# Texto y números ------------------------------------------------------------

@pytest.mark.parametrize("texto,esperado", [
    ("ciento veinte", "120"), ("sesenta y dos y medio", "62.5"), ("ocho y medio", "8.5"),
    ("tres series de ocho con sesenta", "3 series de 8 con 60"), ("una hora y media", "1 hora y media"),
    ("treinta y cinco", "35"), ("veinticinco", "25"), ("con cien, una hora", "con 100 1 hora"),
])
def test_numeros_en_palabras(texto, esperado):
    assert voz.a_digitos(texto) == esperado


def test_minutos_y_horas():
    assert 90 in voz.minutos("judo hora y media")
    assert 90 in voz.minutos("judo una hora y media")
    assert 120 in voz.minutos("dos horas")
    assert 30 in voz.minutos("media hora de técnica")
    assert 75 in voz.minutos("1 hora y 15 minutos")
    assert 1 in voz.horas_dichas("almorcé a la una")
    assert 7 in voz.horas_dichas("a las 7:30 desayuné")
    assert not voz.horas_dichas("en la tarde hice fuerza")
    assert not voz.horas_dichas("hice las 3 series")


def test_intercambio_junto_al_grupo():
    assert not voz.intercambio_dicho("almorcé dos arepas con pollo", "carbohidrato", 2)
    assert voz.intercambio_dicho("dos de carbohidrato y una de carne", "carbohidrato", 2)
    assert voz.intercambio_dicho("dos de carbohidrato y una de carne", "carne", 1)
    assert voz.intercambio_dicho("me comí una fruta", "fruta", 1)


def test_vacia_y_alucinaciones():
    assert voz.es_vacia("")
    assert voz.es_vacia("Subtítulos realizados por la comunidad de Amara.org")
    assert not voz.es_vacia("ocho vasos")


# Grabar o escribir ------------------------------------------------------------

def test_portada_y_botones(cliente):
    r = cliente.get("/rendimiento/voz")
    assert r.status_code == 200 and "Grabar" in r.text and "O escríbelo" in r.text and "/static/voz.js" in r.text
    for url in ("/rendimiento", "/rendimiento/comidas"):
        assert 'href="/rendimiento/voz"' in cliente.get(url).text
    assert "Contar por voz" in cliente.get("/rendimiento/mas").text


def test_texto_en_lugar_de_audio(cliente, config, con_db, home, transcripcion):
    responde(home, {"items": [{"tipo": "comida", "indice": None, "cita": "cené arepa con huevo", "fecha": None,
                               "momento": "cena", "hora": None, "franja": None, "texto": "arepa con huevo",
                               "intercambios": {}, "segun_plan": False}], "pregunta": None})
    eid = enviar(cliente, "cené arepa con huevo")
    e = entrada(con_db, eid)
    assert e["estado"] == "borrador" and json.loads(e["rondas"]) == ["cené arepa con huevo"]
    assert transcripcion["llamadas"] == 0
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "Cena" in pagina and "arepa con huevo" in pagina


@pytest.fixture
def con_db(config, cliente):
    from app.core.db import conectar
    c = conectar(config.db_path)
    yield c
    c.close()


def test_audio_grande_o_de_otro_tipo(cliente, con_db, config):
    grande = b"\x1a\x45\xdf\xa3" + b"0" * (voz.MAX_AUDIO + 10)
    r = cliente.post("/rendimiento/voz/audio", content=grande, headers={"Content-Type": "audio/webm"})
    assert r.status_code == 413 and "pasa de 10 MB" in r.json()["error"]
    r = cliente.post("/rendimiento/voz/audio", content=b"RIFF....WAVEfmt " + b"0" * 100, headers={"Content-Type": "audio/webm"})
    assert r.status_code == 422 and "no lo reconozco" in r.json()["error"]
    assert con_db.execute("SELECT COUNT(*) FROM voz_entradas").fetchone()[0] == 0
    assert not list(voz.carpeta_tmp(config).glob("*"))


def _webm(tmp_path: Path, segundos: float = 1.5) -> bytes:
    if not shutil.which("ffmpeg"):
        pytest.skip("sin ffmpeg")
    ruta = tmp_path / "a.webm"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=300:duration={segundos}",
                    "-c:a", "libopus", str(ruta)], check=True)
    return ruta.read_bytes()


def test_audio_se_transcribe_y_no_queda(cliente, con_db, config, home, transcripcion, tmp_path):
    transcripcion["texto"] = "cené arepa con huevo"
    responde(home, {"items": [], "pregunta": None})
    r = cliente.post("/rendimiento/voz/audio", content=_webm(tmp_path), headers={"Content-Type": "audio/webm;codecs=opus"})
    assert r.status_code == 200, r.text
    eid = int(r.json()["url"].rsplit("/", 1)[1])
    e = entrada(con_db, eid)
    assert e["estado"] == "borrador" and json.loads(e["rondas"]) == ["cené arepa con huevo"]
    assert transcripcion["pcm"] > 16000   # PCM s16le de 16 kHz de 1,5 s
    assert not list(voz.carpeta_tmp(config).glob("*"))
    assert all(str(voz.carpeta_tmp(config)) not in json.dumps(ll) for ll in llamadas(home))


def test_transcripcion_vacia_o_alucinada(cliente, con_db, home, transcripcion, tmp_path):
    transcripcion["texto"] = "Subtítulos realizados por la comunidad de Amara.org"
    r = cliente.post("/rendimiento/voz/audio", content=_webm(tmp_path), headers={"Content-Type": "audio/webm"})
    e = entrada(con_db, int(r.json()["url"].rsplit("/", 1)[1]))
    assert e["estado"] == "fallida" and "No entendí el audio" in e["error"]
    assert llamadas(home) == []


def test_audio_de_mas_de_tres_minutos(cliente, con_db, home, transcripcion, tmp_path, monkeypatch):
    monkeypatch.setattr(voz, "MAX_SEGUNDOS", 2)
    r = cliente.post("/rendimiento/voz/audio", content=_webm(tmp_path, 4), headers={"Content-Type": "audio/webm"})
    e = entrada(con_db, int(r.json()["url"].rsplit("/", 1)[1]))
    assert e["estado"] == "fallida" and "pasa de 3 minutos" in e["error"]


def test_falla_ffmpeg(cliente, con_db, config, home, transcripcion):
    r = cliente.post("/rendimiento/voz/audio", content=b"\x1a\x45\xdf\xa3basura" * 20, headers={"Content-Type": "audio/webm"})
    e = entrada(con_db, int(r.json()["url"].rsplit("/", 1)[1]))
    assert e["estado"] == "fallida" and e["error"] == "No pude leer el audio" and not e["reintentable"]
    assert not list(voz.carpeta_tmp(config).glob("*"))


# Interpretación aislada -------------------------------------------------------

def test_llamada_aislada(cliente, home, monkeypatch, config):
    monkeypatch.setenv("BRAIN_PIN", "1234")
    monkeypatch.setenv("FINANZAS_SECRETO", "no-debe-salir")
    responde(home, r_mixto())
    enviar(cliente, MIXTO)
    ll = llamadas(home)[0]
    args = ll["args"]
    assert args[args.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in args and "--mcp-config" not in args
    assert args[args.index("--setting-sources") + 1] == ""
    for flag in ("--disable-slash-commands", "--no-session-persistence", "--json-schema", "--system-prompt"):
        assert flag in args
    assert args[args.index("--model") + 1] == "opus"
    assert set(ll["env"]) <= {"PATH", "HOME", "LANG", "USER"} | {"PWD", "SHLVL", "_", "LC_CTYPE"}
    assert not any(k.startswith(("BRAIN_", "FINANZAS_")) for k in ll["env"])
    assert ll["cwd"] != str(config.vault_path) and not ll["cwd"].startswith(str(Path(__file__).parents[1]))
    assert MIXTO in ll["prompt"] and "Press banca" in ll["prompt"] and "Uchi mata" in ll["prompt"]
    assert str(config.vault_path) not in ll["prompt"] and "1234" not in ll["prompt"]


@pytest.mark.parametrize("modo", [{"codigo": 1}, {"is_error": True}, {"sin_structured": True}, {"dormir": 3},
                                  {"respuestas": [{"sin": "items"}]}])
def test_error_o_tiempo_agotado(cliente, con_db, home, config, modo, monkeypatch):
    if "dormir" in modo:
        monkeypatch.setattr(voz, "interpretar", _con_tiempo(voz.interpretar, 1))
    (home / "modo_claude.json").write_text(json.dumps(modo))
    eid = enviar(cliente, "cené arepa")
    e = entrada(con_db, eid)
    assert e["estado"] == "fallida" and "No pude interpretar el relato" in e["error"] and e["reintentable"]
    assert json.loads(e["rondas"]) == ["cené arepa"]
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "Intentar de nuevo" in pagina and "cené arepa" in pagina
    responde(home, {"items": [], "pregunta": None})
    cliente.post(f"/rendimiento/voz/{eid}/reintentar", data={"texto": "cené arepa con queso"})
    e = entrada(con_db, eid)
    assert e["estado"] == "borrador" and json.loads(e["rondas"]) == ["cené arepa con queso"]


def _con_tiempo(real, segundos):
    from dataclasses import replace

    def envoltura(cfg, texto):
        return real(replace(cfg, tiempo_max_voz_s=segundos), texto)
    return envoltura


# Validación contra lo dicho -----------------------------------------------------

def test_borrador_mixto(cliente, con_db, home):
    nu.guardar_dia(con_db, HOY.isoformat(), agua_vasos=4)
    responde(home, r_mixto())
    eid = enviar(cliente, MIXTO)
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "Almuerzo" in pagina and 'value="13:00"' in pagina
    assert "6 vasos</b> en total" in pagina and "(ahora 4)" in pagina
    assert "Sesión de judo" in pagina and "dijiste: noche" in pagina
    assert "No encuentro esto" not in pagina and "Revisa: no lo oí" not in pagina and "Falta" not in pagina


def test_intercambios_no_dichos(cliente, con_db, home):
    responde(home, r_mixto(intercambios={"carbohidrato": 2}))
    eid = enviar(cliente, MIXTO)
    cliente.get(f"/rendimiento/voz/{eid}")
    ctx = voz.Contexto.crear(con_db, Path(cliente.app.state.config.vault_path), "2026-10-22", [MIXTO])
    t = voz.validar(ctx, items(con_db, eid))[0]
    assert t.item["intercambios"] == {}
    texto = "almorcé dos de carbohidrato y una de carne"
    it = voz.limpiar_item({"tipo": "comida", "cita": texto, "momento": "almuerzo", "texto": "arroz y pollo",
                           "intercambios": {"carbohidrato": 2, "carne": 1, "grasa": 1}})
    t = voz.validar(voz.Contexto.crear(con_db, Path(cliente.app.state.config.vault_path), "2026-10-22", [texto]), [it])[0]
    assert t.item["intercambios"] == {"carbohidrato": 2, "carne": 1}


def test_segun_el_plan(cliente, con_db, config):
    texto = "desayuné lo del plan"
    it = voz.limpiar_item({"tipo": "comida", "cita": texto, "momento": "desayuno", "texto": "", "segun_plan": True,
                           "intercambios": {"grasa": 3}})
    t = voz.validar(voz.Contexto.crear(con_db, config.vault_path, "2026-10-22", [texto]), [it])[0]
    assert t.item["intercambios"] == {"carbohidrato": 1, "proteína": 4, "grasa": 1, "verdura": 1}
    assert not t.bloqueada


def test_ejercicio_fuera_del_catalogo(cliente, con_db, home):
    texto = "hice press Arnold tres de diez con 14, una hora"
    responde(home, r_fuerza(texto, [ej("press Arnold", None, "press Arnold tres de diez con 14", (10, 14, None),
                                       (10, 14, None), (10, 14, None))], duracion=60))
    eid = enviar(cliente, texto)
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "No reconocido: «press Arnold»" in pagina
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_de(cliente, eid))
    assert r.status_code == 422
    datos = form_de(cliente, eid)
    datos["0.e0.catalogo"] = "Press militar"
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos, follow_redirects=False)
    assert r.status_code == 303
    assert con_db.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 3
    assert con_db.execute("SELECT COUNT(*) FROM ejercicios WHERE nombre LIKE '%Arnold%'").fetchone()[0] == 0


def test_catalogo_interpretado(cliente, con_db, home):
    texto = "sentadilla tres de cinco con cien, una hora"
    responde(home, r_fuerza(texto, [ej("sentadilla", "Sentadilla trasera", "sentadilla tres de cinco con cien",
                                       (5, 100, None), (5, 100, None), (5, 100, None))], duracion=60))
    eid = enviar(cliente, texto)
    assert "Entendí «sentadilla» como Sentadilla trasera" in cliente.get(f"/rendimiento/voz/{eid}").text
    datos = form_de(cliente, eid)
    assert cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos).status_code == 422
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data={**datos, "0.confirmo": "e0.catalogo"}, follow_redirects=False)
    assert r.status_code == 303


def test_cita_o_numero_no_oidos(cliente, con_db, home):
    texto = "judo hora y media"
    responde(home, {"items": [{"tipo": "combate", "indice": None, "cita": "judo dos horas", "fecha": None, "hora": None,
                               "franja": None, "duracion_min": 120, "sensaciones": None, "molestia_hombro": None,
                               "notas": None, "disciplina": "judo", "bloques": []}], "pregunta": None})
    eid = enviar(cliente, texto)
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "No encuentro esto en lo que dijiste" in pagina and "Revisa: no lo oí" in pagina
    datos = form_de(cliente, eid)
    assert cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos).status_code == 422
    datos["0.duracion_min"] = "90"
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data={**datos, "0.confirmo": "cita"}, follow_redirects=False)
    assert r.status_code == 303
    assert con_db.execute("SELECT duracion_s FROM sesiones").fetchone()[0] == 5400


def test_hora_no_dicha(cliente, con_db, home):
    texto = "en la tarde hice fuerza: press banca tres de ocho con sesenta, una hora"
    responde(home, r_fuerza(texto, [ej("press banca", "Press banca", "press banca tres de ocho con sesenta",
                                       (8, 60, None), (8, 60, None), (8, 60, None))], duracion=60, hora="17:00", franja="tarde"))
    eid = enviar(cliente, texto)
    datos = form_de(cliente, eid)
    assert datos["0.hora"] == ""
    cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos)
    assert con_db.execute("SELECT hora FROM sesiones").fetchone()[0] is None


def test_series_sin_rpe_heredado(cliente, con_db, home):
    texto = "press banca dos series de ocho con sesenta, la primera a RPE ocho, en cuarenta minutos"
    responde(home, r_fuerza(texto, [ej("press banca", "Press banca", texto, (8, 60, 8), (8, 60, None))], duracion=40))
    eid = enviar(cliente, texto)
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_de(cliente, eid), follow_redirects=False)
    assert r.status_code == 303, r.text
    filas = con_db.execute("SELECT reps, carga_g, rpe_x10 FROM series ORDER BY orden").fetchall()
    assert [tuple(f) for f in filas] == [(8, 60000, 80), (8, 60000, None)]


def test_fecha_fuera_de_rango(cliente, con_db, home):
    responde(home, {"items": [{"tipo": "comida", "indice": None, "cita": "cené arepa", "fecha": "2026-10-01",
                               "momento": "cena", "hora": None, "franja": None, "texto": "arepa", "intercambios": {},
                               "segun_plan": False}], "pregunta": None})
    eid = enviar(cliente, "cené arepa")
    assert "Fecha fuera de rango (del 15 al 22 de octubre)" in cliente.get(f"/rendimiento/voz/{eid}").text
    datos = form_de(cliente, eid)
    assert cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos).status_code == 422
    datos["0.fecha"] = "2026-10-21"
    assert cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos, follow_redirects=False).status_code == 303


def test_agua_sin_modo_pregunta(cliente, con_db, home):
    responde(home, {"items": [{"tipo": "agua", "indice": None, "cita": "me tomé seis vasos", "fecha": None, "vasos": 6,
                               "modo": None}], "pregunta": None})
    eid = enviar(cliente, "me tomé seis vasos")
    b = voz.borrador(entrada(con_db, eid))
    assert "total de hoy o se suman" in b["pregunta"] and b["preguntados"] == ["0.modo"]


# Repreguntas --------------------------------------------------------------------

def test_pregunta_por_la_duracion(cliente, con_db, home):
    texto = "hice sentadilla trasera tres de cinco con cien"
    sin = r_fuerza(texto, [ej("sentadilla trasera", "Sentadilla trasera", texto, (5, 100, None), (5, 100, None), (5, 100, None))])
    con_dur = json.loads(json.dumps(sin))
    con_dur["items"][0].update(indice=0, duracion_min=60, cita="una hora")
    responde(home, sin, con_dur)
    eid = enviar(cliente, texto)
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "¿Cuánto duró la sesión de fuerza?" in pagina
    r = cliente.post(f"/rendimiento/voz/{eid}/responder", data={**form_de(cliente, eid), "respuesta": "una hora"},
                     follow_redirects=False)
    assert r.status_code == 303
    e = entrada(con_db, eid)
    assert json.loads(e["rondas"]) == [texto, "una hora"]
    b = voz.borrador(e)
    assert b["items"][0]["duracion_min"] == 60 and b["pregunta"] is None
    assert "Revisa: no lo oí" not in cliente.get(f"/rendimiento/voz/{eid}").text
    assert "La app le preguntó por" in llamadas(home)[1]["prompt"]


def test_ediciones_a_mano_no_se_pierden(cliente, con_db, home):
    texto = "almorcé arroz a la una y fuerza: press banca tres de ocho con sesenta"
    primero = r_fuerza(texto, [ej("press banca", "Press banca", "press banca tres de ocho con sesenta",
                                  (8, 60, None), (8, 60, None), (8, 60, None))])
    primero["items"].insert(0, {"tipo": "comida", "indice": None, "cita": "almorcé arroz a la una", "fecha": None,
                                "momento": "almuerzo", "hora": "13:00", "franja": None, "texto": "arroz",
                                "intercambios": {}, "segun_plan": False})
    segundo = json.loads(json.dumps(primero))
    segundo["items"][0]["indice"] = 0
    segundo["items"][1].update(indice=1, duracion_min=45, cita="cuarenta y cinco minutos")
    responde(home, primero, segundo)
    eid = enviar(cliente, texto)
    datos = form_de(cliente, eid)
    datos["0.hora"] = "13:30"
    cliente.post(f"/rendimiento/voz/{eid}/responder", data={**datos, "respuesta": "cuarenta y cinco minutos"})
    b = items(con_db, eid)
    assert b[0]["hora"] == "13:30" and b[1]["duracion_min"] == 45
    assert '"hora": "13:30"' in llamadas(home)[1]["prompt"]


def test_limite_de_rondas(cliente, con_db, home):
    texto = "hice sentadilla trasera tres de cinco con cien"
    responde(home, r_fuerza(texto, [ej("sentadilla trasera", "Sentadilla trasera", texto, (5, 100, None))]))
    eid = enviar(cliente, texto)
    for respuesta in ("no sé", "no me acuerdo"):
        r = cliente.post(f"/rendimiento/voz/{eid}/responder", data={**form_de(cliente, eid), "respuesta": respuesta},
                         follow_redirects=False)
        assert r.status_code == 303
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "Ya no pregunto más" in pagina and "Responder con voz" not in pagina and "Falta" in pagina
    r = cliente.post(f"/rendimiento/voz/{eid}/responder", data={**form_de(cliente, eid), "respuesta": "otra"})
    assert r.status_code == 409


def test_respuesta_fallida_conserva_el_borrador(cliente, con_db, home):
    texto = "hice sentadilla trasera tres de cinco con cien"
    responde(home, r_fuerza(texto, [ej("sentadilla trasera", "Sentadilla trasera", texto, (5, 100, None))]))
    eid = enviar(cliente, texto)
    (home / "modo_claude.json").write_text(json.dumps({"codigo": 1}))
    cliente.post(f"/rendimiento/voz/{eid}/responder", data={**form_de(cliente, eid), "respuesta": "una hora"})
    e = entrada(con_db, eid)
    assert e["estado"] == "borrador" and "tu borrador sigue igual" in e["error"]
    assert json.loads(e["rondas"]) == [texto]


# Guardar todo ---------------------------------------------------------------------

def test_sesion_registrada(cliente, con_db, home):
    nu.guardar_dia(con_db, HOY.isoformat(), agua_vasos=4)
    responde(home, r_mixto())
    eid = enviar(cliente, MIXTO)
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_de(cliente, eid), follow_redirects=False)
    assert r.status_code == 303, r.text
    s = con_db.execute("SELECT * FROM sesiones").fetchone()
    assert (s["tipo"], s["disciplina"], s["duracion_s"], s["guardada"], s["hora"]) == ("combate", "judo", 5400, 1, None)
    bloques = con_db.execute("SELECT * FROM combate_bloques WHERE sesion_id = ? ORDER BY orden", (s["id"],)).fetchall()
    assert [(b["tipo"], b["duracion_s"], b["rounds"]) for b in bloques] == [("tecnica", 1200, None), ("randori", None, 5)]
    entradas = con_db.execute("SELECT resultado, detalle FROM combate_tecnicas ORDER BY id").fetchall()
    assert [tuple(x) for x in entradas] == [("trabajada", None), ("funciono", "2 veces")]
    assert nu.dia(con_db, HOY.isoformat()).agua_vasos == 6
    assert nu.dia(con_db, HOY.isoformat()).comidas["almuerzo"].texto == "arroz con pollo"
    pagina = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "Guardado" in pagina and f"/rendimiento/sesiones/{s['id']}" in pagina
    assert cliente.post(f"/rendimiento/voz/{eid}/guardar", data={}).status_code == 409
    assert con_db.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0] == 1


def test_atomicidad(cliente, con_db, home, monkeypatch):
    texto = "almorcé arroz a la una y press banca dos de ocho con sesenta en cuarenta minutos"
    resp = r_fuerza(texto, [ej("press banca", "Press banca", texto, (8, 60, None), (8, 60, None))], duracion=40)
    resp["items"].insert(0, {"tipo": "comida", "indice": None, "cita": "almorcé arroz a la una", "fecha": None,
                             "momento": "almuerzo", "hora": "13:00", "franja": None, "texto": "arroz",
                             "intercambios": {}, "segun_plan": False})
    responde(home, resp)
    eid = enviar(cliente, texto)
    real = voz.q._insertar_serie
    cuenta = {"n": 0}

    def falla(*a, **k):
        cuenta["n"] += 1
        if cuenta["n"] == 2:
            raise __import__("sqlite3").OperationalError("disco lleno (simulado)")
        return real(*a, **k)
    monkeypatch.setattr(voz.q, "_insertar_serie", falla)
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_de(cliente, eid))
    assert r.status_code == 500 and "no se guardó nada" in r.text
    assert con_db.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0] == 0
    assert con_db.execute("SELECT COUNT(*) FROM comidas_registro").fetchone()[0] == 0
    assert entrada(con_db, eid)["estado"] == "borrador"


def test_reemplazo_de_comida(cliente, con_db, home):
    for modo, esperado in (("reemplazar", "arroz con pollo"), ("agregar", "sopa; arroz con pollo")):
        with con_db:
            con_db.execute("DELETE FROM comidas_registro")
        nu.guardar_comida(con_db, HOY.isoformat(), "almuerzo", None, "sopa", {})
        responde(home, {"items": [r_mixto()["items"][0]], "pregunta": None})
        eid = enviar(cliente, MIXTO)
        assert "Ya registraste: «sopa»" in cliente.get(f"/rendimiento/voz/{eid}").text
        datos = {**form_de(cliente, eid), "0.modo_texto": modo}
        assert cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos, follow_redirects=False).status_code == 303
        filas = con_db.execute("SELECT texto FROM comidas_registro WHERE momento = 'almuerzo'").fetchall()
        assert [f[0] for f in filas] == [esperado]


def test_quitar_un_item(cliente, con_db, home):
    responde(home, r_mixto())
    eid = enviar(cliente, MIXTO)
    cliente.post(f"/rendimiento/voz/{eid}/editar", data={**form_de(cliente, eid), "quitar": "1"})
    assert [i["tipo"] for i in items(con_db, eid)] == ["comida", "combate"]
    cliente.post(f"/rendimiento/voz/{eid}/editar", data={**form_de(cliente, eid), "quitar": "1.b1"})
    assert len(items(con_db, eid)[1]["bloques"]) == 1


# Cruce con los sensores ---------------------------------------------------------------

def test_una_candidata_del_mismo_dia(cliente, con_db, home, boveda):
    agregar_polar(boveda, "2026-10-21,19:10:00,Judo,5280,,140,170,600,,")
    texto = "anoche judo, hora y media"
    responde(home, {"items": [{"tipo": "combate", "indice": None, "cita": texto, "fecha": "2026-10-21", "hora": None,
                               "franja": "noche", "duracion_min": 90, "sensaciones": None, "molestia_hombro": None,
                               "notas": None, "disciplina": "judo", "bloques": []}], "pregunta": None})
    eid = enviar(cliente, texto)
    datos = form_de(cliente, eid)
    assert datos["0.vincular"] == "polar|2026-10-21|19:10:00"
    cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos)
    s = con_db.execute("SELECT * FROM sesiones").fetchone()
    assert (s["clave_importada"], s["duracion_s"]) == ("polar|2026-10-21|19:10:00", 5400)
    nota = con_db.execute("SELECT disciplina FROM anotaciones_importadas WHERE clave = ?", (s["clave_importada"],)).fetchone()
    assert nota["disciplina"] == "judo"


def test_sin_duracion_dicha_usa_el_reloj(cliente, con_db, home, boveda):
    agregar_polar(boveda, "2026-10-22,07:05:00,Strength training,3120,,120,150,300,,")
    texto = "hoy en la mañana fuerza: sentadilla trasera tres de cinco con cien"
    responde(home, r_fuerza(texto, [ej("sentadilla trasera", "Sentadilla trasera", texto, (5, 100, None), (5, 100, None),
                                       (5, 100, None))], franja="mañana"))
    eid = enviar(cliente, texto)
    assert voz.borrador(entrada(con_db, eid))["pregunta"] is None
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_de(cliente, eid), follow_redirects=False)
    assert r.status_code == 303, r.text
    s = con_db.execute("SELECT * FROM sesiones").fetchone()
    assert (s["duracion_s"], s["clave_importada"]) == (3120, "polar|2026-10-22|07:05:00")


def test_dos_candidatas(con_db, config, boveda):
    agregar_polar(boveda, "2026-10-22,07:00:00,Strength training,3000,,120,150,300,,",
                  "2026-10-22,18:00:00,Strength training,3000,,120,150,300,,")
    cands = [a for a in act.todas(con_db, boveda) if a.fecha == "2026-10-22"]
    assert voz.preseleccion(cands, "fuerza", None, None, "tarde").hora == "18:00:00"
    assert voz.preseleccion(cands, "fuerza", None, None, None) is None


def test_otra_disciplina_no_se_preselecciona(con_db, boveda):
    agregar_polar(boveda, "2026-10-22,18:00:00,Kickboxing,3000,,120,150,300,,")
    cands = [a for a in act.todas(con_db, boveda) if a.fecha == "2026-10-22"]
    assert voz.preseleccion(cands, "combate", "judo", None, None) is None
    assert voz.preseleccion(cands, "combate", "muaythai", None, None).hora == "18:00:00"


def test_no_vincular_no_insiste(cliente, con_db, home, boveda):
    agregar_polar(boveda, "2026-10-22,18:00:00,Strength training,3000,,120,150,300,,")
    texto = "fuerza: press banca tres de ocho con sesenta, cincuenta minutos"
    responde(home, r_fuerza(texto, [ej("press banca", "Press banca", texto, (8, 60, None), (8, 60, None), (8, 60, None))],
                            duracion=50))
    eid = enviar(cliente, texto)
    cliente.post(f"/rendimiento/voz/{eid}/guardar", data={**form_de(cliente, eid), "0.vincular": ""})
    assert "Tu reloj registró" not in cliente.get("/rendimiento").text


def test_pendiente_hasta_la_sincronizacion(cliente, con_db, home, boveda):
    texto = "judo hora y media"
    responde(home, {"items": [{"tipo": "combate", "indice": None, "cita": texto, "fecha": None, "hora": None,
                               "franja": None, "duracion_min": 90, "sensaciones": None, "molestia_hombro": None,
                               "notas": None, "disciplina": "judo", "bloques": []}], "pregunta": None})
    eid = enviar(cliente, texto)
    assert "Sin datos del reloj todavía" in cliente.get(f"/rendimiento/voz/{eid}").text
    cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_de(cliente, eid))
    sid = con_db.execute("SELECT id FROM sesiones").fetchone()[0]
    assert "Tu reloj registró" not in cliente.get("/rendimiento").text
    agregar_polar(boveda, "2026-10-22,19:00:00,Judo,5000,,140,170,600,,")
    pagina = cliente.get("/rendimiento").text
    assert "Tu reloj registró una sesión que puede ser la de Judo de hoy" in pagina
    cliente.post(f"/rendimiento/sesiones/{sid}/vincular", data={"clave": "polar|2026-10-22|19:00:00"})
    s = con_db.execute("SELECT * FROM sesiones").fetchone()
    assert s["clave_importada"] == "polar|2026-10-22|19:00:00" and s["duracion_s"] == 5400
    assert "Tu reloj registró" not in cliente.get("/rendimiento").text


def test_no_es_la_misma(cliente, con_db, boveda):
    from app.modules.rendimiento import consultas as q
    sid = q.crear_sesion(con_db, "2026-10-21", "fuerza", "fuerza")
    q.guardar_sesion(con_db, sid, duracion_s=3000, molestia=None, sensaciones=None, notas="", clave_importada=None)
    agregar_polar(boveda, "2026-10-21,18:00:00,Strength training,3000,,120,150,300,,")
    assert "la de fuerza de ayer" in cliente.get("/rendimiento").text
    cliente.post(f"/rendimiento/sesiones/{sid}/descartar-vinculo", data={"clave": "polar|2026-10-21|18:00:00"})
    assert "Tu reloj registró" not in cliente.get("/rendimiento").text


def test_no_vincular_en_el_cierre_manual(cliente, con_db, boveda):
    from app.modules.rendimiento import consultas as q
    agregar_polar(boveda, "2026-10-22,18:00:00,Strength training,3000,,120,150,300,,")
    sid = q.crear_sesion(con_db, "2026-10-22", "fuerza", "fuerza")
    cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={"vincular": "", "duracion_min": "50"})
    assert "Tu reloj registró" not in cliente.get("/rendimiento").text


# Un relato a la vez, retención y recuperación -------------------------------------------

def test_no_bloquea_ni_es_bloqueado(cliente, con_db, home):
    with con_db:
        con_db.execute("INSERT INTO trabajos_ia (tipo, estado) VALUES ('sincronizar', 'corriendo')")
    responde(home, {"items": [], "pregunta": None})
    eid = enviar(cliente, "cené arepa")
    assert entrada(con_db, eid)["estado"] == "borrador"
    assert con_db.execute("SELECT estado FROM trabajos_ia").fetchone()[0] == "corriendo"


def test_dos_envios_a_la_vez(cliente, con_db):
    eid = voz.crear(con_db, "2026-10-22", "primero")
    r = cliente.post("/rendimiento/voz", data={"texto": "segundo"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/rendimiento/voz/{eid}?ocupado=1"
    assert con_db.execute("SELECT COUNT(*) FROM voz_entradas").fetchone()[0] == 1
    assert cliente.post(f"/rendimiento/voz/{eid}/descartar").status_code == 409


def test_recuperar_al_arrancar(config, con_db):
    a = voz.crear(con_db, "2026-10-22", "texto")
    with con_db:
        b = con_db.execute("INSERT INTO voz_entradas (estado, fecha_base, hora_base) VALUES ('transcribiendo', '2026-10-22', '20:00')").lastrowid
    voz.carpeta_tmp(config).mkdir(parents=True, exist_ok=True)
    (voz.carpeta_tmp(config) / "huerfano.audio").write_bytes(b"x")
    voz.recuperar(config)
    ea, eb = entrada(con_db, a), entrada(con_db, b)
    assert (ea["estado"], ea["reintentable"]) == ("fallida", 1) and "intentar de nuevo" in ea["error"]
    assert (eb["estado"], eb["reintentable"]) == ("fallida", 0) and "grábalo de nuevo" in eb["error"]
    assert not list(voz.carpeta_tmp(config).glob("*"))


def test_limpieza(cliente, con_db):
    with con_db:
        viejo = con_db.execute("INSERT INTO voz_entradas (estado, fecha_base, hora_base, rondas, creada) VALUES"
                               " ('borrador', '2026-10-14', '20:00', '[\"a\"]', '2026-10-14 20:00:00')").lastrowid
        guardada = con_db.execute("INSERT INTO voz_entradas (estado, fecha_base, hora_base, rondas, borrador, registros, creada)"
                                  " VALUES ('guardada', '2026-09-21', '20:00', '[\"b\"]', '{}', '[{\"url\": \"/x\", \"texto\": \"X\", \"tipo\": \"comida\"}]',"
                                  " '2026-09-21 20:00:00')").lastrowid
    cliente.get("/rendimiento/voz")
    assert entrada(con_db, viejo) is None
    g = entrada(con_db, guardada)
    assert g["rondas"] == "[]" and g["borrador"] is None and json.loads(g["registros"])[0]["url"] == "/x"


def test_descartar_borra(cliente, con_db, home):
    responde(home, {"items": [], "pregunta": None})
    eid = enviar(cliente, "cené arepa")
    assert "No encontré comidas, entrenamientos ni cómo te sentiste" in cliente.get(f"/rendimiento/voz/{eid}").text
    cliente.post(f"/rendimiento/voz/{eid}/descartar")
    assert entrada(con_db, eid) is None


def test_origen_ajeno(cliente):
    r = cliente.post("/rendimiento/voz", data={"texto": "x"}, headers={"Origin": "https://malo.example"})
    assert r.status_code == 403
