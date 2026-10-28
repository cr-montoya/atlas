"""Spec openspec/changes/v1-dia-y-sensaciones. Claude falso (tests/claude_falso.py) y vault ficticio en tmp_path.
Hoy es jueves 2026-10-22."""

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from html import unescape
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Config
from app.core.db import conectar, migrar
from app.main import crear_app
from app.modules.rendimiento import consultas as q
from app.modules.rendimiento import rutas, sensaciones as sen, trabajos, vault, voz
from tests.conftest import PIN
from tests.test_rendimiento_voz import enviar, form_de, items, llamadas, responde

DATOS = Path(__file__).parent / "datos" / "vault"
FALSO = Path(__file__).parent / "claude_falso.py"
HOY = date(2026, 10, 22)
CABECERA_VIEJA = ("day,steps,resting_hr,stress_avg,body_battery_high,sleep_h,deep_min,light_min,rem_min,awake_min,"
                  "sleep_score,hrv_ms,hrv_status,intensity_min,vigorous_min")
CABECERA = ",".join(trabajos.COLUMNAS_SALUD)
RELATO_22 = ("No fui al gimnasio tampoco, porque la verdad me sentía muy malo, indispuesto y he tenido diarrea, siento "
             "como dolor en el cuello y todo el día estuve casi que acostado y trabajé normal.")


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
def cliente(config):
    app = crear_app(config)
    with TestClient(app) as c:
        assert c.post("/login", data={"pin": PIN}, follow_redirects=False).status_code == 303
        yield c


@pytest.fixture
def con(config, cliente):
    c = conectar(config.db_path)
    yield c
    c.close()


def salud(boveda: Path, nombre: str, *filas: str, cabecera: str = CABECERA) -> Path:
    ruta = boveda / vault.GARMIN / nombre
    ruta.write_text(cabecera + "\n" + "".join(f + "\n" for f in filas))
    vault.limpiar_cache()
    return ruta


def fila_salud(dia: str, **v) -> str:
    return ",".join(str(v.get(c, "")) if c != "day" else dia for c in trabajos.COLUMNAS_SALUD)


def r_sens(citas, fecha=None, sintomas=(), **campos) -> dict:
    """Respuesta de Claude con un ítem de sensaciones. Las escalas y textos van como (valor, dicho)."""
    it = {"tipo": "sensaciones", "indice": None, "citas": list(citas), "fecha": fecha,
          **{k: None for k in sen.CLAVES_ESCALA}, "sintomas": [{"clave": c, "dicho": d} for c, d in sintomas],
          "sintomas_otros": None, "dolor": None, "sin_entreno": None}
    for k, (valor, dicho) in campos.items():
        it[k] = {"valor": valor, "dicho": dicho}
    return it


def borrador(cliente, home, texto, *items_claude):
    responde(home, {"items": list(items_claude), "pregunta": None})
    return enviar(cliente, texto)


def tarjetas(con, config, eid):
    e = voz.entrada(con, eid)
    ctx = voz.Contexto.crear(con, config.vault_path, e["fecha_base"], json.loads(e["rondas"]))
    return voz.validar(ctx, voz.borrador(e)["items"])


def marcas(t) -> dict[str, list[str]]:
    return {r: [m.clase for m in ms] for r, ms in t.marcas.items()}


def form_voz(cliente, eid) -> dict:
    """form_de más las casillas de síntomas, que van varias con el mismo nombre."""
    datos = form_de(cliente, eid)
    html = cliente.get(f"/rendimiento/voz/{eid}").text
    for m in re.finditer(r'<input type="checkbox" name="(\d+\.sintomas)" value="([^"]+)"( checked)?>', html):
        datos.setdefault(m.group(1), [])
        if isinstance(datos[m.group(1)], str):
            datos[m.group(1)] = []
        if m.group(3):
            datos[m.group(1)].append(m.group(2))
    return datos


# Datos -------------------------------------------------------------------------

def test_migracion_con_checks(con):
    with pytest.raises(sqlite3.IntegrityError):
        with con:
            con.execute("INSERT INTO sensaciones_dia (fecha, energia) VALUES ('2026-10-22', 7)")
    with pytest.raises(sqlite3.IntegrityError):
        with con:
            con.execute("INSERT INTO sensaciones_dia (fecha, sin_entreno) VALUES ('2026-10-22', 'pereza')")
    with pytest.raises(sqlite3.IntegrityError):
        with con:
            con.execute("INSERT INTO sensaciones_dia (fecha, sintomas) VALUES ('2026-10-22', 'no es json')")
    with con:
        con.execute("INSERT INTO sensaciones_dia (fecha, hambre) VALUES ('2026-10-22', 5)")
    assert sen.leer(con, "2026-10-22")["sintomas"] == []


def test_zona_baja_y_hambre():
    assert sen.zona_baja({"energia": 2, "estres": 4, "hambre": 1, "animo": 3}) == [("energia", 2), ("estres", 4)]
    assert not sen.avisa({"hambre": 1, "estres": 3})


def test_formulario_radios_y_sin_dato(cliente):
    html = cliente.get("/rendimiento/sensaciones").text
    for k in sen.CLAVES_ESCALA:
        assert len(re.findall(rf'type="radio" name="{k}"', html)) == 6
        assert re.search(rf'name="{k}" value="" checked', html)
    assert "de 1, nada, a 5, mucho" in html and "cuello, lado derecho, 6 de 10" in html
    for texto in ("Descansé", "No: enfermedad", "No: lesión", "No: otro motivo", "¿Entrenaste?"):
        assert texto in html


def test_valor_fuera_de_rango(cliente, con):
    r = cliente.post("/rendimiento/sensaciones", data={"fecha": "2026-10-22", "energia": "7"})
    assert r.status_code == 422 and "Las escalas van de 1 a 5" in r.text
    assert sen.leer(con, "2026-10-22") is None


def test_texto_demasiado_largo(cliente, con):
    r = cliente.post("/rendimiento/sensaciones", data={"fecha": "2026-10-22", "dolor": "x" * 301})
    assert r.status_code == 422 and "El dolor admite hasta 300 caracteres" in r.text
    assert sen.leer(con, "2026-10-22") is None


def test_sintoma_desconocido_y_fechas(cliente, con):
    r = cliente.post("/rendimiento/sensaciones", data={"fecha": "2026-10-22", "sintomas": "pereza"})
    assert r.status_code == 422
    for f in ("2026-10-14", "2026-10-23"):
        r = cliente.post("/rendimiento/sensaciones", data={"fecha": f, "energia": "3"})
        assert r.status_code == 422 and "Solo se pueden registrar los últimos 7 días" in r.text
    r = cliente.post("/rendimiento/sensaciones", data={"fecha": "22/10/2026", "energia": "3"})
    assert r.status_code == 422 and "Fecha no válida" in r.text
    assert cliente.get("/rendimiento/sensaciones?fecha=2026-10-01").status_code == 422
    assert con.execute("SELECT COUNT(*) FROM sensaciones_dia").fetchone()[0] == 0


def test_guardar_y_volver(cliente, con):
    r = cliente.post("/rendimiento/sensaciones", data={
        "fecha": "2026-10-21", "volver": "dia", "energia": "2", "sintomas": ["diarrea", "mareo"],
        "dolor": " cuello,  lado derecho ", "sin_entreno": "enfermedad", "notas": "acostado"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/rendimiento/dia/2026-10-21"
    f = sen.leer(con, "2026-10-21")
    assert f["energia"] == 2 and f["sintomas"] == ["diarrea", "mareo"] and f["dolor"] == "cuello, lado derecho"
    assert f["sin_entreno"] == "enfermedad" and f["notas"] == "acostado"
    r = cliente.post("/rendimiento/sensaciones", data={"fecha": "2026-10-22", "volver": "historial", "animo": "4"},
                     follow_redirects=False)
    assert r.headers["location"] == "/rendimiento/sensaciones/historial"
    r = cliente.post("/rendimiento/sensaciones", data={"fecha": "2026-10-22", "volver": "otro", "animo": "4"},
                     follow_redirects=False)
    assert r.headers["location"] == "/rendimiento"


def test_editar_no_borra_el_relato(cliente, con):
    sen.guardar(con, "2026-10-22", energia=2, relato="me sentía muy malo")
    html = cliente.get("/rendimiento/sensaciones?fecha=2026-10-22").text
    assert "Lo que dijiste" in html and "me sentía muy malo" in html
    cliente.post("/rendimiento/sensaciones", data={"fecha": "2026-10-22", "energia": "3"})
    f = sen.leer(con, "2026-10-22")
    assert f["energia"] == 3 and f["relato"] == "me sentía muy malo"


def test_vaciar_la_fila(cliente, con):
    sen.guardar(con, "2026-10-21", energia=3)
    cliente.post("/rendimiento/sensaciones", data={"fecha": "2026-10-21", "energia": ""})
    assert sen.leer(con, "2026-10-21") is None


# Por voz -----------------------------------------------------------------------

def test_esquema_y_reglas():
    variantes = ESQ = voz.ESQUEMA["properties"]["items"]["items"]["anyOf"]
    s = next(v for v in variantes if v["properties"]["tipo"] == {"const": "sensaciones"})
    assert set(s["required"]) >= {"fecha", "citas", "sintomas", "dolor", "sin_entreno", *sen.CLAVES_ESCALA}
    reglas = voz.system_prompt()
    assert "El campo \"sensaciones\" de una sesión describe solo esa sesión" in reglas
    assert "nunca a motivación" in reglas and "no tengo" in reglas and ESQ


def test_el_relato_del_22_de_octubre(cliente, con, config, home):
    eid = borrador(cliente, home, RELATO_22, r_sens(
        [RELATO_22], energia=(2, "me sentía muy malo"),
        sintomas=[("diarrea", "he tenido diarrea"), ("malestar_general", "indispuesto")],
        dolor=("cuello", "dolor en el cuello"), sin_entreno=("enfermedad", "no fui al gimnasio")))
    [t] = tarjetas(con, config, eid)
    m = marcas(t)
    assert m == {"energia": ["entendi"], "sintomas.malestar_general": ["entendi"]}
    assert t.extra["estado"] == {"energia": "entendi", "sintomas.diarrea": "ok", "sintomas.malestar_general": "entendi",
                                 "dolor": "ok", "sin_entreno": "ok"}
    textos = [x.texto for ms in t.marcas.values() for x in ms]
    assert "Entendí «me sentía muy malo» como energía 2/5" in textos
    assert "Entendí «indispuesto» como malestar general" in textos
    html = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "Cómo me sentí · jueves 22" in html and "data-guardar-todo" in html
    # Guardar queda bloqueado hasta confirmar las dos marcas «Entendí»
    datos = form_voz(cliente, eid)
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos)
    assert r.status_code == 422 and sen.leer(con, "2026-10-22") is None
    datos["0.confirmo"] = ["energia", "sintomas.malestar_general"]
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos, follow_redirects=False)
    assert r.status_code == 303
    f = sen.leer(con, "2026-10-22")
    assert f["energia"] == 2 and f["sintomas"] == ["diarrea", "malestar_general"] and f["dolor"] == "cuello"
    assert f["sin_entreno"] == "enfermedad" and RELATO_22 in f["relato"]
    registros = json.loads(voz.entrada(con, eid)["registros"])
    assert registros == [{"tipo": "sensaciones", "fecha": "2026-10-22", "texto": "Cómo me sentí el 2026-10-22",
                          "url": "/rendimiento/dia/2026-10-22"}]


@pytest.mark.parametrize("texto,escala,valor,dicho,esperado", [
    ("dormí mal, como un dos, y el estrés en cuatro", "sueno", 2, "dormí mal", "ok"),
    ("dormí mal, como un dos, y el estrés en cuatro", "estres", 4, "el estrés en cuatro", "ok"),
    ("tengo la energía un poco baja", "energia", 1, "la energía un poco baja", "entendi"),
    ("dormí 4 horas, el estrés de 4 horas de reunión me mató", "sueno", 4, "dormí 4 horas", "entendi"),
    ("dormí 4 horas, el estrés de 4 horas de reunión me mató", "estres", 4, "el estrés de 4 horas de reunión", "entendi"),
    ("dormí 4 horas, el estrés de 4 horas de reunión me mató", "estres", 4, "estrés altísimo", None),
    ("dormí como un 4", "sueno", 4, "dormí como un 4", "ok"),
    ("la energía en 3", "energia", 2, "la energía en 3", "revisa"),
    ("me dio un hambre tremenda", "motivacion", 4, "me dio un hambre tremenda", "entendi"),
    ("tengo ganas de comer como un 4", "motivacion", 4, "ganas de comer", "entendi"),
    ("tengo ganas de comer como un 4", "hambre", 4, "ganas de comer", "ok"),
    ("la energía un 1 de 5", "energia", 1, "la energía un 1 de 5", "ok"),
    ("la energía una de 5", "energia", 1, "la energía una de 5", "ok"),
])
def test_numeros_que_si_y_que_no(cliente, con, config, home, texto, escala, valor, dicho, esperado):
    eid = borrador(cliente, home, texto, r_sens([texto], **{escala: (valor, dicho)}))
    ts = tarjetas(con, config, eid)
    if esperado is None:
        assert ts == [] and items(con, eid) == []   # descartado sin marca: el ítem vacío se quita
        return
    [t] = ts
    assert t.extra["estado"][escala] == esperado
    if esperado == "revisa":
        assert "Revisa: oí energía 3" in [m.texto for m in t.marcas["energia"]] and t.item["energia"] == 3


def test_numeros_escala_unidades():
    assert voz.numeros_escala("dormí 4 horas", "sueno") == []
    assert voz.numeros_escala("el estrés de 8 de 10", "estres") == []
    assert voz.numeros_escala("el ánimo como un dos", "animo") == [2.0]
    assert voz.numeros_escala("el ánimo como un día raro", "animo") == []
    assert voz.numeros_escala("la pila mas o menos en 3", "energia") == [3.0]
    assert voz.numeros_escala("motivado tipo 5 veces", "motivacion") == []


def test_negaciones(cliente, con, config, home):
    texto = "no tengo diarrea, ya no me duele el cuello"
    eid = borrador(cliente, home, texto, r_sens([texto], sintomas=[("diarrea", "no tengo diarrea")],
                                                dolor=("cuello", "ya no me duele el cuello")))
    assert items(con, eid) == [] and tarjetas(con, config, eid) == []
    assert voz.dicho_negado(texto, "diarrea") and not voz.dicho_negado("he tenido diarrea", "he tenido diarrea")


def test_valor_inventado(cliente, con, config, home):
    eid = borrador(cliente, home, "hoy bien", r_sens(["hoy bien"], animo=(4, "hoy me siento genial")))
    assert items(con, eid) == []
    assert "No encontré comidas, entrenamientos ni cómo te sentiste" in cliente.get(f"/rendimiento/voz/{eid}").text


def test_sin_cita_verificada_pasa_a_revisa(cliente, con, config, home):
    texto = "la energía en dos"
    eid = borrador(cliente, home, texto, r_sens(["algo que no dije"], energia=(2, "la energía en dos")))
    [t] = tarjetas(con, config, eid)
    assert "cita" in t.marcas and [m.clase for m in t.marcas["energia"]] == ["revisa"]


def test_ya_hay_registro_ese_dia(cliente, con, config, home):
    sen.guardar(con, "2026-10-22", energia=3, animo=4, sintomas=["fiebre"], relato="tenía fiebre")
    texto = "hoy tengo la energía en dos y tengo diarrea"
    eid = borrador(cliente, home, texto, r_sens([texto], energia=(2, "la energía en dos"),
                                                sintomas=[("diarrea", "tengo diarrea")]))
    [t] = tarjetas(con, config, eid)
    assert not t.bloqueada and t.extra["antes"] == {"energia": 3}
    html = cliente.get(f"/rendimiento/voz/{eid}").text
    assert "Energía: antes 3, ahora 2" in html
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_voz(cliente, eid), follow_redirects=False)
    assert r.status_code == 303
    f = sen.leer(con, "2026-10-22")
    assert f["energia"] == 2 and f["animo"] == 4 and f["sintomas"] == ["fiebre", "diarrea"]
    assert f["relato"].splitlines() == ["tenía fiebre", texto]


def test_dolor_se_agrega_y_rango_si_se_pasa(cliente, con, config, home):
    sen.guardar(con, "2026-10-22", dolor="rodilla " + "x" * 290)
    texto = "me duele el cuello"
    eid = borrador(cliente, home, texto, r_sens([texto], dolor=("cuello", "me duele el cuello")))
    [t] = tarjetas(con, config, eid)
    assert [m.clase for m in t.marcas["dolor"]] == ["rango"]
    assert voz.combinar_texto("rodilla", "cuello") == "rodilla; cuello"
    assert voz.combinar_texto("cuello", "Cuello") == "cuello"


def test_relato_se_recorta():
    viejo = "\n".join(f"linea vieja {i} " + "x" * 90 for i in range(25))
    texto, recortado = voz.combinar_relato(viejo, ["nueva cita"])
    assert recortado and len(texto) <= 2000 and texto.endswith("nueva cita") and "linea vieja 0 " not in texto


def test_comidas_y_sensaciones_en_un_mismo_relato(cliente, con, config, home):
    texto = "almorcé arepa con queso; tengo poca energía, como un dos"
    comida = {"tipo": "comida", "indice": None, "cita": "almorcé arepa con queso", "fecha": None, "momento": "almuerzo",
              "hora": None, "franja": None, "texto": "arepa con queso", "intercambios": {}, "segun_plan": False}
    eid = borrador(cliente, home, texto, comida, r_sens(["tengo poca energía, como un dos"], energia=(2, "poca energía")))
    ts = tarjetas(con, config, eid)
    assert [t.item["tipo"] for t in ts] == ["comida", "sensaciones"] and ts[1].extra["estado"]["energia"] == "ok"
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_voz(cliente, eid), follow_redirects=False)
    assert r.status_code == 303
    assert con.execute("SELECT texto FROM comidas_registro WHERE fecha = '2026-10-22'").fetchone()[0] == "arepa con queso"
    assert sen.leer(con, "2026-10-22")["energia"] == 2
    assert [x["tipo"] for x in json.loads(voz.entrada(con, eid)["registros"])] == ["comida", "sensaciones"]


def test_atomico_si_falla_la_fila(cliente, con, config, home, monkeypatch):
    texto = "almorcé arepa con queso; tengo poca energía, como un dos"
    comida = {"tipo": "comida", "indice": None, "cita": "almorcé arepa con queso", "fecha": None, "momento": "almuerzo",
              "hora": None, "franja": None, "texto": "arepa con queso", "intercambios": {}, "segun_plan": False}
    eid = borrador(cliente, home, texto, comida, r_sens(["tengo poca energía, como un dos"], energia=(2, "poca energía")))

    def falla(*a, **k):
        raise sqlite3.OperationalError("disco lleno")
    monkeypatch.setattr(sen, "_upsert_sensaciones", falla)
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_voz(cliente, eid))
    assert r.status_code == 500
    assert con.execute("SELECT COUNT(*) FROM comidas_registro").fetchone()[0] == 0
    assert voz.entrada(con, eid)["estado"] == "borrador"


def test_dos_registros_el_mismo_dia(cliente, con, config, home):
    texto = "la energía en dos; el ánimo en tres"
    eid = borrador(cliente, home, texto, r_sens(["la energía en dos"], energia=(2, "la energía en dos")),
                   r_sens(["el ánimo en tres"], animo=(3, "el ánimo en tres")))
    ts = tarjetas(con, config, eid)
    assert "rango" in [m.clase for m in ts[1].marcas["fecha"]]


def test_fecha_se_revalida_al_guardar(cliente, con, config, home, monkeypatch):
    texto = "el jueves pasado la energía en dos"
    eid = borrador(cliente, home, texto, r_sens([texto], fecha="2026-10-15", energia=(2, "la energía en dos")))
    [t] = tarjetas(con, config, eid)
    assert "fecha" not in t.marcas
    monkeypatch.setattr(rutas, "hoy", lambda: date(2026, 10, 29))
    [t] = tarjetas(con, config, eid)
    assert [m.texto for m in t.marcas["fecha"]][0].startswith("Fecha fuera de rango")
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_voz(cliente, eid))
    assert r.status_code == 422 and sen.leer(con, "2026-10-15") is None


def test_sin_entreno_con_otra_sesion_y_sin_motivo(cliente, con, config, home):
    q._insertar_sesion(con, "2026-10-22", "fuerza", "fuerza", guardada=True)
    con.commit()
    texto = "no fui a judo hoy"
    eid = borrador(cliente, home, texto, r_sens([texto], sin_entreno=("enfermedad", "no fui a judo")))
    [t] = tarjetas(con, config, eid)
    textos = [m.texto for m in t.marcas["sin_entreno"]]
    assert "Ya hay una sesión ese día" in textos and "Entendí que no entrenaste por enfermedad" in textos


def test_editar_cuenta_como_confirmar(cliente, con, config, home):
    eid = borrador(cliente, home, RELATO_22, r_sens([RELATO_22], energia=(2, "me sentía muy malo")))
    datos = form_voz(cliente, eid)
    datos["0.energia"] = "1"
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos, follow_redirects=False)
    assert r.status_code == 303 and sen.leer(con, "2026-10-22")["energia"] == 1


def test_sintoma_marcado_a_mano(cliente, con, config, home):
    texto = "la energía en dos"
    eid = borrador(cliente, home, texto, r_sens([texto], energia=(2, "la energía en dos")))
    datos = form_voz(cliente, eid)
    datos["0.sintomas"] = ["tos"]
    r = cliente.post(f"/rendimiento/voz/{eid}/guardar", data=datos, follow_redirects=False)
    assert r.status_code == 303 and sen.leer(con, "2026-10-22")["sintomas"] == ["tos"]


def test_repregunta_conserva_los_dichos(cliente, con, config, home):
    item = r_sens([RELATO_22], energia=(2, "me sentía muy malo"))
    salida = voz.desde_claude({"items": [item]})
    assert salida[0][1]["dichos"] == {"energia": "me sentía muy malo"}
    esquema = voz.a_esquema(salida[0][1])
    assert esquema["energia"] == {"valor": 2, "dicho": "me sentía muy malo"} and esquema["sintomas"] == []


# Aviso en Hoy ------------------------------------------------------------------

def test_nada_que_avisar(cliente, con):
    sen.guardar(con, "2026-10-21", energia=4)
    html = cliente.get("/rendimiento").text
    assert "Cómo vienes" not in html and "¿Cómo te sientes hoy?" in html


def test_hoy_mal_sin_reloj_de_hoy(cliente, con):
    sen.guardar(con, "2026-10-22", sintomas=["diarrea"])
    html = unescape(cliente.get("/rendimiento").text)
    assert "Cómo vienes" in html and "Hoy:</b> diarrea" in html
    assert "Reloj de anoche: aún sin sincronizar (Garmin trae hasta ayer)" in html
    assert "¿Cómo te sientes hoy?" not in html and 'href="/rendimiento/dia/2026-10-22">Ver o editar' in html


def test_ayer_sin_reloj(cliente, con):
    sen.guardar(con, "2026-10-21", sintomas=["diarrea"])
    a = sen.aviso_hoy(con, vault.importar(cliente.app.state.config.vault_path), HOY)
    assert [(l.cuando, l.texto, l.reloj) for l in a["lineas"]] == [("Ayer", "diarrea", [])]


def test_aviso_con_el_reloj(cliente, con, boveda):
    salud(boveda, "2026-10-14_2026-10-21_salud-diaria-garmin-mcp.csv",
          fila_salud("2026-10-20", hrv_ms=50, resting_hr=52),
          fila_salud("2026-10-21", sleep_h=6.0333, sleep_score=73, hrv_ms=94, hrv_status="BALANCED", resting_hr=50,
                     body_battery_charged=76, body_battery_low=5, hrv_baseline_low=76, hrv_baseline_high=110))
    sen.guardar(con, "2026-10-21", sintomas=["diarrea", "malestar_general"], dolor="cuello", sin_entreno="enfermedad",
                energia=2, hambre=1)
    a = sen.aviso_hoy(con, vault.importar(boveda), HOY)
    [l] = a["lineas"]
    assert l.texto == "diarrea, malestar general, dolor: cuello, no entrenaste (enfermedad), energía 2/5"
    assert l.reloj == ["Sueño 6 h 2 min · puntaje 73", "HRV 94 ms (tu rango: 76 a 110), equilibrada",
                       "Body Battery: cargó 76, mínimo 5", "FC en reposo 50 (tu promedio: 51)"]
    html = unescape(cliente.get("/rendimiento").text)
    assert "Ayer:</b> diarrea, malestar general" in html and "Body Battery: cargó 76, mínimo 5" in html
    for palabra in ("recomend", "deberías", "diagnóstico"):
        assert palabra not in html.split("Cómo vienes")[1].split("</section>")[0].lower()


def test_hrv_sin_linea_base_usa_el_promedio(boveda):
    s = vault.DiaSalud("2026-10-21", hrv_ms=94)
    assert sen.lineas_reloj(s, sen.Promedios(52, None)) == ["HRV 94 ms (tu promedio: 52)"]


def test_aviso_hace_una_sola_consulta(con, boveda):
    consultas = []
    con.set_trace_callback(lambda sql: consultas.append(sql))
    sen.aviso_hoy(con, vault.importar(boveda), HOY)
    con.set_trace_callback(None)
    assert len([c for c in consultas if "sensaciones_dia" in c]) == 1


# Historial ---------------------------------------------------------------------

def test_historial_lado_a_lado(cliente, con, boveda):
    salud(boveda, "2026-10-14_2026-10-21_salud-diaria-garmin-mcp.csv",
          fila_salud("2026-10-20", sleep_h=7.5, hrv_ms=60, body_battery_charged=50, body_battery_low=20, resting_hr=52,
                     stress_avg=31),
          fila_salud("2026-10-01", steps=100))
    sen.guardar(con, "2026-10-21", energia=2, estres=5, sintomas=["tos"])
    sen.guardar(con, "2026-10-08", animo=4)   # fuera de los 14 días
    sid = q._insertar_sesion(con, "2026-10-21", "fuerza", "fuerza", guardada=True, duracion_s=3000)
    con.commit()
    html = unescape(cliente.get("/rendimiento/sensaciones/historial").text)
    assert html.count('class="tarjeta dia-sentir"') == 2
    assert "baja</span>" in html and "alto</span>" in html and "Tos" in html
    assert "Sin registro" in html and 'href="/rendimiento/sensaciones?fecha=2026-10-20&volver=historial">Registrar' in html
    assert "cargó 50, mín. 20" in html and f'href="/rendimiento/sesiones/{sid}"' in html
    assert 'href="/rendimiento/dia/2026-10-21"' in html
    assert "correlaci" not in html.lower() and "conclusi" not in html.lower().replace("sin conclusiones", "")


# Body Battery, fases y línea base --------------------------------------------------

def test_archivo_viejo(boveda):
    salud(boveda, "2026-09-11_2026-10-11_salud-diaria-garmin-mcp.csv",
          "2026-10-01,3000,55,30,80,7.25,60,300,80,20,78,70,BALANCED,30,10", cabecera=CABECERA_VIEJA)
    d = vault.importar(boveda).salud["2026-10-01"]
    assert d.bb_min is None and d.bb_cargado is None and d.hrv_base_baja is None
    assert d.bb_max == 80 and d.profundo_min == 60 and d.rem_min == 80 and d.hrv_estado == "BALANCED"


def test_relleno_superpuesto(boveda):
    salud(boveda, "2026-09-11_2026-10-11_salud-diaria-garmin-mcp.csv",
          "2026-10-01,3000,55,30,80,7.25,60,300,80,20,78,70,BALANCED,30,10", cabecera=CABECERA_VIEJA)
    salud(boveda, "2026-09-11_2026-09-30_salud-diaria-relleno-garmin-mcp.csv", fila_salud("2026-09-30", steps=10))
    salud(boveda, "2026-10-01_2026-10-20_salud-diaria-relleno-garmin-mcp.csv",
          fila_salud("2026-10-01", body_battery_low=12, hrv_status="NONE"), fila_salud("2026-10-20", steps=1))
    imp = vault.importar(boveda)
    d = imp.salud["2026-10-01"]
    assert d.pasos == 3000 and d.bb_min == 12 and d.hrv_estado == "BALANCED" and d.sueno_s == 7.25 * 3600
    # El relleno no mueve la fecha desde la que sincroniza la app
    assert imp.ultima_fecha["garmin"] == "2026-10-01"


def test_vacio_nunca_es_cero(boveda):
    salud(boveda, "2026-10-01_2026-10-02_salud-diaria-garmin-mcp.csv", fila_salud("2026-10-02", steps="abc"))
    d = vault.importar(boveda).salud["2026-10-02"]
    assert all(getattr(d, c) is None for c in vault.CAMPOS_SALUD)


def test_prompt_de_la_sincronizacion_con_columnas():
    p = trabajos.prompt_sincronizar({"garmin": "2026-10-20"}, "2026-10-22")
    assert CABECERA in p and "hrv_ms: hrv_last_night" in p and "vigorous_min: vigorous_minutes" in p
    assert "nunca en 0" in p and "día en que despertó" in p and CABECERA.endswith("hrv_baseline_high")


# Relleno y guarda de imports --------------------------------------------------------

FALSO_TRABAJO = r'''#!{python}
import json, os, sys
from pathlib import Path
modo = os.environ.get("FALSO_MODO", "relleno")
Path(os.environ["FALSO_ARGS"]).write_text(json.dumps(sys.argv[1:]))
g = Path("03_Training/imports/garmin")
if modo == "relleno":
    import re
    for a, b in re.findall(r"(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})_salud-diaria-relleno", sys.argv[2]):
        (g / f"{{a}}_{{b}}_salud-diaria-relleno-garmin-mcp.csv").write_text("{cabecera}\n" + b + ",,,,,,,,,,,,,,,12,40,30,70,100\n")
if modo == "edita":
    viejo = next(g.glob("*salud*.csv"))
    viejo.write_text(viejo.read_text() + "2026-02-09,1,1,1,1,1,1,1,1,1,1,1,BALANCED,1,1\n")
if modo == "sync_edita":
    viejo = next(g.glob("*actividades*.md"))
    viejo.write_text(viejo.read_text() + "\n")
print(json.dumps({{"type": "result", "is_error": False, "result": json.dumps({{"archivos": [], "dias_garmin": 60, "avisos": []}})}}))
'''


def _git(boveda, *args):
    subprocess.run(["git", "-C", str(boveda), "-c", "user.name=prueba", "-c", "user.email=p@p", *args],
                   check=True, capture_output=True)


@pytest.fixture
def vault_git(boveda):
    _git(boveda, "init", "-q")
    _git(boveda, "add", "-A")
    _git(boveda, "commit", "-q", "-m", "base")
    return boveda


@pytest.fixture
def cfg_trabajo(tmp_path, vault_git, monkeypatch):
    ruta = tmp_path / "claude-trabajo"
    ruta.write_text(FALSO_TRABAJO.format(python=sys.executable, cabecera=CABECERA))
    ruta.chmod(0o755)
    monkeypatch.setenv("FALSO_ARGS", str(tmp_path / "args.json"))
    cfg = Config(pin=PIN, secreto="s", db_path=tmp_path / "trab.db", exports_path=tmp_path / "exports",
                 vault_path=vault_git, fotos_path=tmp_path / "fotos", claude_cmd=str(ruta), tiempo_max_s=20)
    c = conectar(cfg.db_path)
    migrar(c)
    c.close()
    return cfg


def _correr(cfg, tipo, params):
    c = conectar(cfg.db_path)
    try:
        tid, _ = trabajos.encolar(c, tipo, params)
    finally:
        c.close()
    trabajos.lanzar(cfg, tid, en_hilo=False)
    c = conectar(cfg.db_path)
    try:
        return trabajos.trabajo(c, tid)
    finally:
        c.close()


def test_tramos_del_relleno():
    t = trabajos.tramos_relleno(HOY)
    assert t[0][0] == date(2026, 8, 23) and t[-1][1] == date(2026, 10, 21)
    assert [(b - a).days + 1 for a, b in t] == [20, 20, 20]
    assert trabajos.archivo_relleno(*t[0]).endswith("2026-08-23_2026-09-11_salud-diaria-relleno-garmin-mcp.csv")


def test_relleno_escribe_archivos_nuevos_sin_edit(cfg_trabajo, tmp_path, monkeypatch):
    monkeypatch.setenv("FALSO_MODO", "relleno")
    ya = cfg_trabajo.vault_path / trabajos.archivo_relleno(*trabajos.tramos_relleno(HOY)[0])
    ya.write_text(CABECERA + "\n")
    _git(cfg_trabajo.vault_path, "add", "-A")
    _git(cfg_trabajo.vault_path, "commit", "-q", "-m", "tramo")
    antes = vault.importar(cfg_trabajo.vault_path).ultima_fecha["garmin"]
    t = _correr(cfg_trabajo, trabajos.RELLENAR, {"hoy": HOY.isoformat()})
    assert t["estado"] == "listo", t["error"]
    args = json.loads((tmp_path / "args.json").read_text())
    tools = args[args.index("--tools") + 1]
    assert "Edit" not in tools and "Write" in tools
    permitidos = args[args.index("--allowedTools") + 1:args.index("--permission-mode")]
    assert permitidos == ["Read", "Glob", "Grep", "Edit(03_Training/imports/garmin/**)", "mcp__garmin"]
    assert "2026-08-23_2026-09-11" not in args[1] and "2026-10-02_2026-10-21" in args[1] and "2026-10-22" not in args[1]
    res = json.loads(t["resultado"])
    assert len(res["archivos_nuevos"]) == 2 and res["tramos"] == ["2026-09-12_2026-10-01", "2026-10-02_2026-10-21"]
    vault.limpiar_cache()
    imp = vault.importar(cfg_trabajo.vault_path)
    assert imp.salud["2026-10-21"].bb_min == 12 and imp.ultima_fecha["garmin"] == antes == "2026-02-05"


def test_relleno_sin_archivos_falla(cfg_trabajo, monkeypatch):
    monkeypatch.setenv("FALSO_MODO", "nada")
    t = _correr(cfg_trabajo, trabajos.RELLENAR, {"hoy": HOY.isoformat()})
    assert t["estado"] == "fallido" and "no escribió ningún archivo" in t["error"]


def test_relleno_que_edita_un_archivo_existente(cfg_trabajo, monkeypatch):
    monkeypatch.setenv("FALSO_MODO", "edita")
    t = _correr(cfg_trabajo, trabajos.RELLENAR, {"hoy": HOY.isoformat()})
    assert t["estado"] == "fallido" and "Se modificó un archivo existente de imports" in t["error"]


def test_sincronizacion_que_edita_un_archivo_existente(cfg_trabajo, monkeypatch):
    monkeypatch.setenv("FALSO_MODO", "sync_edita")
    t = _correr(cfg_trabajo, "sincronizar", {"ultima": {}, "hoy": HOY.isoformat()})
    assert t["estado"] == "fallido" and "Se modificó un archivo existente de imports" in t["error"]


def test_boton_del_relleno(cliente, con):
    html = cliente.get("/rendimiento/ia").text
    assert "Traer Body Battery y fases de sueño (60 días)" in html
    with con:
        con.execute("INSERT INTO trabajos_ia (tipo, estado, error) VALUES ('rellenar_salud', 'fallido', 'Garmin no respondió')")
    html = cliente.get("/rendimiento/ia").text
    assert "Traer Body Battery" in html and "Garmin no respondió" in html
    with con:
        con.execute("INSERT INTO trabajos_ia (tipo, estado, resultado) VALUES ('rellenar_salud', 'listo', ?)",
                    (json.dumps({"archivos": [], "archivos_nuevos": [], "tramos": ["2026-09-12_2026-10-01"]}),))
    assert "Traer Body Battery" in cliente.get("/rendimiento/ia").text
    with con:
        con.execute("INSERT INTO trabajos_ia (tipo, estado) VALUES ('rellenar_salud', 'listo')")
    assert "Traer Body Battery" not in cliente.get("/rendimiento/ia").text


def test_boton_encola_el_relleno(cliente, con, monkeypatch):
    lanzados = []
    monkeypatch.setattr(trabajos, "lanzar", lambda cfg, tid, en_hilo=True: lanzados.append(tid))
    with con:  # un relleno "listo" que no escribió archivos no bloquea el siguiente
        con.execute("INSERT INTO trabajos_ia (tipo, estado, resultado) VALUES ('rellenar_salud', 'listo', ?)",
                    (json.dumps({"archivos_nuevos": [], "tramos": ["2026-09-12_2026-10-01"]}),))
    r = cliente.post("/rendimiento/ia/rellenar-salud", follow_redirects=False)
    assert r.status_code == 303 and lanzados
    t = trabajos.trabajo(con, lanzados[0])
    assert t["tipo"] == "rellenar_salud" and json.loads(t["parametros"]) == {"hoy": "2026-10-22"}


# Registrar con fecha ----------------------------------------------------------------

def test_selector_de_dia(cliente, con):
    html = cliente.get("/rendimiento/registrar").text
    for nombre in ("Hoy", "Ayer", "Martes 20", "Lunes 19", "Jueves 15"):
        assert f">{nombre}</a>" in html
    assert html.count('href="/rendimiento/registrar?fecha=') == 8 and "Miércoles 14" not in html
    assert 'name="fecha" value="2026-10-22"' in html
    sid = q.crear_sesion(con, "2026-10-20", "fuerza", "fuerza")
    html = cliente.get("/rendimiento/registrar?fecha=2026-10-20").text
    assert 'name="fecha" value="2026-10-20"' in html and "Continuar la de este día" in html
    assert "Continuar" not in cliente.get("/rendimiento/registrar").text
    assert sid


def test_sesion_de_anteayer(cliente, con):
    r = cliente.post("/rendimiento/sesiones", data={"tipo": "fuerza", "fecha": "2026-10-20"}, follow_redirects=False)
    sid = int(r.headers["location"].rsplit("/", 1)[1])
    assert q.sesion(con, sid)["fecha"] == "2026-10-20"
    r = cliente.post("/rendimiento/sesiones", data={"tipo": "fuerza", "fecha": "2026-10-20"}, follow_redirects=False)
    assert int(r.headers["location"].rsplit("/", 1)[1]) == sid   # reutiliza el borrador de esa fecha y tipo
    for f in ("2026-10-14", "2026-10-23", "ayer"):
        r = cliente.post("/rendimiento/sesiones", data={"tipo": "combate", "fecha": f})
        assert r.status_code == 422 and "Solo se pueden registrar los últimos 7 días" in r.text
    assert con.execute("SELECT COUNT(*) FROM sesiones").fetchone()[0] == 1


def test_sesion_de_anteayer_vinculada_al_reloj(cliente, con, boveda):
    md = next((boveda / vault.GARMIN).glob("*actividades*.md"))
    md.write_text(md.read_text().replace("\n## Totales", "| 2026-10-20 | mar | 18:00 | Fuerza | 50,0 | 20,0 | - | 110 | 150 | 200 |\n\n## Totales"))
    vault.limpiar_cache()
    sid = q.crear_sesion(con, "2026-10-20", "fuerza", "fuerza")
    q.guardar_sesion(con, sid, duracion_s=3000, molestia=None, sensaciones=None, notas="", clave_importada=None)
    html = cliente.get("/rendimiento").text
    assert f'action="/rendimiento/sesiones/{sid}/vincular"' in html


def test_al_arrancar_borra_borradores_viejos(config):
    c = conectar(config.db_path)
    migrar(c)
    viejo = q.crear_sesion(c, "2026-10-01", "fuerza", "fuerza")
    q.agregar_serie(c, viejo, q.ejercicios(c)[0]["id"], reps=8, carga_g=1000)
    reciente = q.crear_sesion(c, "2026-10-16", "fuerza", "fuerza")
    guardada = q.crear_sesion(c, "2026-09-01", "fuerza", "fuerza")
    q.guardar_sesion(c, guardada, duracion_s=60, molestia=None, sensaciones=None, notas="", clave_importada=None)
    c.close()
    crear_app(config)
    c = conectar(config.db_path)
    ids = {r[0] for r in c.execute("SELECT id FROM sesiones")}
    assert ids == {reciente, guardada}
    assert c.execute("SELECT COUNT(*) FROM series WHERE sesion_id = ?", (viejo,)).fetchone()[0] == 0
    c.close()


# Vista del día --------------------------------------------------------------------

def _dia_completo(cliente, con, boveda):
    agregar = next((boveda / vault.POLAR).glob("*.csv"))
    agregar.write_text(agregar.read_text() + "2026-10-21,19:10:00,Judo,5280,,140,170,600,,\n")
    salud(boveda, "2026-10-14_2026-10-21_salud-diaria-garmin-mcp.csv",
          fila_salud("2026-10-21", sleep_h=7.5, deep_min=80, light_min=250, rem_min=90, awake_min=20, sleep_score=80,
                     hrv_ms=94, hrv_status="BALANCED", hrv_baseline_low=76, hrv_baseline_high=110, resting_hr=50,
                     stress_avg=30, steps=9000, body_battery_high=90, body_battery_low=5, body_battery_charged=76,
                     body_battery_drained=80))
    sid = q.crear_sesion(con, "2026-10-21", "combate", "judo")
    q.guardar_sesion(con, sid, duracion_s=5280, molestia=2, sensaciones=4, notas="", clave_importada="polar|2026-10-21|19:10:00")
    from app.modules.rendimiento import nutricion as nu
    for m in ("desayuno", "almuerzo", "cena", "media_tarde"):
        if m in nu.MOMENTOS:
            nu.guardar_comida(con, "2026-10-21", m, None, f"comida de {m}", {})
    nu.guardar_dia(con, "2026-10-21", agua_vasos=6)
    with con:
        con.execute("INSERT INTO pesajes (fecha, hora, peso_g, condicion) VALUES ('2026-10-21', '07:00', 81500, 'ropa_interior')")
    sen.guardar(con, "2026-10-21", energia=2, sintomas=["diarrea"], relato="me sentía muy malo")
    return sid


def test_dia_con_de_todo(cliente, con, boveda):
    sid = _dia_completo(cliente, con, boveda)
    html = unescape(cliente.get("/rendimiento/dia/2026-10-21").text)
    for seccion in ("Miércoles 21 de octubre", "Ayer", "Cómo me sentí", "Entrenamiento", "Reloj", "Comidas", "Peso y cuerpo"):
        assert seccion in html, seccion
    assert 'href="/rendimiento/comparar?b=2026-W43"' in html
    assert f'href="/rendimiento/sesiones/{sid}"' in html and "FC 140, máx 170" in html and "1 bloque" not in html
    assert "máximo 90, mínimo 5, cargó 76, gastó 80" in html and "(tu rango: 76 a 110)" in html and "profundo 80 min" in html
    assert "Frente al plan actual" in html or "frente al plan actual" in html.lower()
    assert "81,5 kg" in html or "81.5" in html
    assert 'href="/rendimiento/sensaciones?fecha=2026-10-21&volver=dia">Editar' in html
    assert 'href="/rendimiento/registrar?fecha=2026-10-21"' in html
    assert 'href="/rendimiento/dia/2026-10-20"' in html and 'href="/rendimiento/dia/2026-10-22"' in html
    assert "Tests" not in html.split("Peso y cuerpo")[1] and "Contado por voz" not in html


def test_dia_viejo_con_solo_reloj(cliente, con, boveda):
    salud(boveda, "2026-09-01_2026-09-30_salud-diaria-garmin-mcp.csv", fila_salud("2026-09-30", steps=5000))
    html = unescape(cliente.get("/rendimiento/dia/2026-09-30").text)
    assert 'id="h-reloj"' in html and "Pasos" in html and "Comparar esta semana" in html
    for nada in ('id="h-sentir"', 'id="h-entreno"', 'id="h-comidas"', 'id="h-cuerpo"', 'id="h-tests"', 'id="h-voz"',
                 "Registrar una sesión", "Registrar cómo me sentí"):
        assert nada not in html, nada


def test_limites_de_fecha(cliente, boveda):
    assert cliente.get("/rendimiento/dia/2026-10-23").status_code == 404
    assert cliente.get("/rendimiento/dia/2025-12-31").status_code == 404   # antes del primer mes del calendario
    assert cliente.get("/rendimiento/dia/2026-01-01").status_code == 200
    assert cliente.get("/rendimiento/dia/2026-13-01").status_code == 422
    assert cliente.get("/rendimiento/dia/hoy").status_code == 422
    html = cliente.get("/rendimiento/dia/2026-10-22").text
    assert 'aria-label="Día siguiente"' not in html and "Garmin trae hasta ayer" in html
    assert 'aria-label="Día anterior"' not in cliente.get("/rendimiento/dia/2026-01-01").text


def test_dia_contado_por_voz(cliente, con, config, home):
    texto = "la energía en dos"
    eid = borrador(cliente, home, texto, r_sens([texto], energia=(2, "la energía en dos")))
    cliente.post(f"/rendimiento/voz/{eid}/guardar", data=form_voz(cliente, eid))
    html = cliente.get("/rendimiento/dia/2026-10-22").text
    assert "Contado por voz" in html and f'href="/rendimiento/voz/{eid}"' in html and "la energía en dos" in html


def test_calendario_enlaza_al_dia(cliente):
    html = unescape(cliente.get("/rendimiento").text)
    assert 'href="/rendimiento/dia/2026-10-15"' in html
    assert 'aria-label="Ver el jueves 22: 0 sesiones"' in html
    assert 'href="/rendimiento/dia/2026-10-30"' not in html
    assert '<div class="dia futuro" aria-disabled="true"><span class="n">30</span></div>' in html
    assert "/rendimiento/comparar?b=" not in cliente.get("/rendimiento/calendario?mes=2026-10").text


def test_mas_tiene_la_entrada(cliente):
    assert 'href="/rendimiento/sensaciones/historial"' in cliente.get("/rendimiento/mas").text
