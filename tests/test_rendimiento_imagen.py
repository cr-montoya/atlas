"""Spec openspec/changes/v1-imagen-proyectada, con un Codex falso (tests/codex_falso.py): nunca llama a OpenAI."""

import base64
import io
import json
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import Config
from app.modules.rendimiento import codex, resumen_ia, rutas, trabajos, vault
from app.modules.rendimiento import evaluaciones as ev
from app.modules.rendimiento import fotos as fx
from app.modules.rendimiento import imagen_proyectada as ip
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
FALSO = Path(__file__).parent / "codex_falso.py"
HOY = date(2026, 10, 19)
FRENTE = ["2025-01-23", "2025-05-04", "2025-05-08", "2025-07-21", "2025-10-23", "2026-05-17", "2026-09-16", "2026-09-24"]
ZONA = {"magnitud": "leve", "direccion": "menos_grasa", "nota": "un poco menos de grasa"}


def _analisis(**zonas) -> dict:
    return {"zonas": {z: dict(zonas.get(z, ZONA)) for z in ip.ZONAS}, "supuestos": ["el plan se mantiene"],
            "faltantes": ["sin pliegues recientes"], "confianza": "media"}


def _png(tam=(60, 80)) -> str:
    buf = io.BytesIO()
    Image.new("RGB", tam, (90, 120, 150)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _jpeg(tam=(60, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", tam, (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    vault.limpiar_cache()
    return destino


@pytest.fixture
def codex_home(tmp_path):
    h = tmp_path / "codex-home"
    h.mkdir()
    (h / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "gpt-6.1-sol", "priority": 1, "visibility": "list", "input_modalities": ["text", "image"],
         "supported_reasoning_levels": [{"effort": "high"}, {"effort": "max"}]}]}))
    return h


def _modo(codex_home: Path, **modo) -> None:
    datos = {"analisis": _analisis(), "imagen_b64": _png()} | modo
    (codex_home / "modo.json").write_text(json.dumps(datos))


def _llamadas(codex_home: Path) -> list[dict]:
    f = codex_home / "llamadas.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines()] if f.is_file() else []


@pytest.fixture
def config(tmp_path, boveda, codex_home):
    _modo(codex_home)
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db", exports_path=tmp_path / "exports",
                  vault_path=boveda, fotos_path=tmp_path / "fotos", codex_cmd=str(FALSO), codex_home=codex_home,
                  tiempo_max_s=20, tiempo_max_imagen_s=60)


@pytest.fixture(autouse=True)
def sincrono(monkeypatch):
    real = trabajos.lanzar
    monkeypatch.setattr(trabajos, "lanzar", lambda cfg, tid, en_hilo=True: real(cfg, tid, en_hilo=False))
    monkeypatch.setattr(rutas, "hoy", lambda: HOY)
    monkeypatch.setattr(trabajos, "path_extendido", lambda: f"{Path(sys.executable).parent}:/usr/bin:/bin")


def _fotos(con, config, pose="frente", fechas=FRENTE, tam=(60, 80)):
    for f in fechas:
        fx.guardar(con, config.fotos_path, f, pose, _jpeg(tam))


def _generar(cliente, fecha="2026-12-13", poses=("frente",), acepto=True):
    datos = {"fecha": fecha, "poses": list(poses)}
    if acepto:
        datos["acepto"] = "1"
    return cliente.post("/rendimiento/imagen", data=datos, follow_redirects=False)


def _ultimo(con):
    return con.execute("SELECT * FROM trabajos_ia WHERE tipo = 'imagen' ORDER BY id DESC LIMIT 1").fetchone()


# Fecha y horizonte ----------------------------------------------------------

def test_rango(cliente, con, config):
    _fotos(con, config)
    r = cliente.get("/rendimiento/imagen")
    assert 'min="2026-11-30"' in r.text and 'max="2027-04-19"' in r.text
    for fecha in ("2026-11-29", "2027-04-20"):
        r = _generar(cliente, fecha)
        assert r.status_code == 422 and "Elige una fecha entre el 30 nov 2026 y el 19 abr 2027" in r.text
    assert _ultimo(con) is None


def test_atajos(cliente, con, config):
    _fotos(con, config)
    r = cliente.get("/rendimiento/imagen").text
    assert "Inicio del viaje a la costa (6 dic)" in r and "Fin del viaje a la costa (16 dic)" in r
    assert "Antes de la cirugía (1 ene 2027)" in r and "fecha=2026-12-06" in r


def test_despues_de_la_cirugia(con, config, boveda):
    _fotos(con, config)
    h = ip.horizonte(HOY, date(2027, 2, 15), boveda)
    assert h.cortado and h.dias == 74 and h.efectivo == date(2027, 1, 1)
    assert h.aviso.startswith("La ilustración extiende tus últimas 4 semanas solo hasta el 1 ene 2027; en el primer trimestre de 2027")
    prompt = ip.prompt_paso1(ip.preparar(con, boveda, HOY, date(2027, 2, 15), ["frente"]))
    assert h.aviso in prompt and "No comentes la cirugía ni la recuperación." in prompt


# Poses y fotos --------------------------------------------------------------

def test_pose_sin_foto_y_foto_vieja(cliente, con, config):
    _fotos(con, config)
    r = cliente.get("/rendimiento/imagen").text
    assert "Toma una foto de perfil derecho" in r and "Toma una foto de espalda" in r
    assert "/rendimiento/fotos/nueva?pose=espalda" in r
    assert "Tu última foto de frente es del 24 sep 2026 (25 días). Para una ilustración más fiel, toma una nueva." in r


def test_fotos_fijas(con, config, boveda):
    _fotos(con, config)
    prep = ip.preparar(con, boveda, HOY, date(2026, 12, 13), ["frente"])
    fx.guardar(con, config.fotos_path, "2026-10-18", "frente", _jpeg())
    fija = ip.preparar(con, boveda, HOY, date(2026, 12, 13), ["frente"], prep.ids)
    assert fija.bases["frente"].fecha == "2026-09-24"


# Tendencia y calibración ----------------------------------------------------

def _m(fecha, peso, evaluador="Ana", metodo="Matriz Centro Uno"):
    return ev.Medicion("antropometria", fecha, metodo=metodo, evaluador=evaluador,
                       valores={"Peso": ev.Valor("Peso", peso, "kg", "neutra")})


def test_tendencia():
    t, motivo = ip.tendencia([_m("2026-04-10", 81300, "Andrés"), _m("2026-10-19", 77000, "Pablo")], HOY)
    assert t is None and motivo == ("sin tendencia de peso válida: las dos últimas mediciones de Matriz Centro Uno son de "
                                    "evaluadores distintos")
    t, _ = ip.tendencia([_m("2026-09-01", 78000), _m("2026-10-13", 77400)], HOY)
    assert t["g_semana"] == -100 and t["evaluador"] == "Ana"
    assert ip.tendencia([_m("2026-06-01", 78000), _m("2026-07-13", 77400)], HOY)[0] is None   # más de 60 días
    assert ip.tendencia([_m("2026-10-01", 78000), _m("2026-10-13", 77400)], HOY)[0] is None   # menos de 28


def _foto(i, fecha, pose="frente"):
    return fx.Foto(i, fecha, pose, f"{fecha}.jpg", 60, 80)


def test_calibracion_con_las_fotos_actuales():
    fotos = [_foto(i, f) for i, f in enumerate(FRENTE, 1)]
    cal = ip.calibracion(fotos, fotos[-1], 55, [], None)
    assert [f.fecha for f in cal.par] == ["2025-05-08", "2025-07-21"]
    assert [f.fecha for f in cal.ruido] == ["2025-05-04", "2025-05-08"] and not cal.filtrado


def test_calibracion_por_sentido():
    fotos = [_foto(1, "2026-01-01"), _foto(2, "2026-02-20"), _foto(3, "2026-03-01"), _foto(4, "2026-04-20"), _foto(5, "2026-10-01")]
    meds = [_m("2026-01-02", 80000), _m("2026-02-19", 79000), _m("2026-03-02", 78000), _m("2026-04-19", 79500)]
    sube = {"g_semana": 100}
    cal = ip.calibracion(fotos, fotos[-1], 55, meds, sube)
    assert [f.fecha for f in cal.par] == ["2026-03-01", "2026-04-20"] and cal.filtrado
    baja = ip.calibracion(fotos, fotos[-1], 55, meds, {"g_semana": -100})
    assert [f.fecha for f in baja.par] == ["2026-01-01", "2026-03-01"]


def test_sin_par():
    base = _foto(1, "2026-09-24", "espalda")
    cal = ip.calibracion([base], base, 55, [], None)
    assert cal.par is None and cal.motivo == "sin calibración (no hay dos fotos de espalda separadas de 42 a 82 días)"


# Datos del paso 1 -----------------------------------------------------------

def test_datos_sin_cifras_futuras_registro_y_fuerza(con, config, boveda):
    _fotos(con, config)
    for momento in ("desayuno", "media_manana", "almuerzo", "cena"):
        con.execute("INSERT INTO comidas_registro (fecha, momento, texto) VALUES ('2026-10-19', ?, 'algo')", (momento,))
    con.commit()
    prompt = ip.prompt_paso1(ip.preparar(con, boveda, HOY, date(2026, 12, 13), ["frente"]))
    assert ("4 de 5 comidas registradas desde 2026-10-19 (registro, no adherencia; no cuenta lo anotado a mano en "
            "el vault)") in prompt
    assert "Fuerza: sin registro de cargas en la app" in prompt and "0 kg" not in prompt
    for linea in prompt.splitlines():
        if "2026-12-13" in linea:
            assert not any(u in linea for u in (" kg", "%", " cm")), linea
    assert "Es contexto, no resultado" in prompt and trabajos.REGLAS_CONTENIDO in prompt
    assert "No ejecutes comandos ni leas archivos" in prompt


# Ejecución completa ---------------------------------------------------------

def test_flujo_completo_comando_entorno_y_registro(cliente, con, config, codex_home, monkeypatch):
    monkeypatch.setenv("BRAIN_PIN", "1234")
    monkeypatch.setenv("BRAIN_SECRETO", "no-debe-salir")
    _fotos(con, config)
    r = _generar(cliente)
    assert r.status_code == 303
    t = _ultimo(con)
    assert t["estado"] == "listo", t["error"]
    llamadas = _llamadas(codex_home)
    assert len(llamadas) == 3
    for ll in llamadas:
        a = ll["args"]
        for bandera in ("--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--json"):
            assert bandera in a
        assert a[a.index("-s") + 1] == "read-only" and a[a.index("-m") + 1] == "gpt-6.1-sol"
        assert 'model_reasoning_effort="max"' in a
        assert {"shell_tool", "unified_exec", "shell_snapshot", "apps", "plugins"} <= {a[i + 1] for i, x in enumerate(a) if x == "--disable"}
        assert "BRAIN_PIN" not in ll["env"] and "BRAIN_SECRETO" not in ll["env"]
        assert set(ll["env"]) <= {"PATH", "HOME", "LANG", "TZ", "CODEX_HOME"}
        carpeta = Path(a[a.index("-C") + 1])
        assert carpeta.parent == config.fotos_path and carpeta.name == f"tmp-codex-{t['id']}"
    paso1, paso2, verif = llamadas
    assert "image_generation" in verif["args"] and len(verif["args"][verif["args"].index("-i") + 1:]) == 2
    assert verif["prompt"].startswith("## Tarea\nEres revisor")
    assert "--output-schema" in paso1["args"] and "image_generation" in paso1["args"]
    assert "--output-schema" not in paso2["args"] and paso2["args"][paso2["args"].index("-i") + 1:].__len__() == 1
    # Paso 2: secciones en orden y sin dígitos
    p2 = paso2["prompt"]
    pos = [p2.index(s) for s in ("## Invariantes", "## Qué puede cambiar", "## Análisis", "## Reglas de realismo", "## Salida")]
    assert pos == sorted(pos) and not any(c.isdigit() for c in p2)
    assert p2.startswith("Imagen adjunta: edit target, identity-preserve")
    # Registro sin rutas temporales ni JSONL crudo
    reg = t["registro"]
    assert "tmp-codex-" not in reg and '"type": "thread.started"' not in reg
    assert "Prompt del análisis:" in reg and "Prompt de frente (intento 1):" in reg and "Modelo: gpt-6.1-sol" in reg
    # Imagen guardada, 600, sin metadatos; limpieza hecha
    fila = con.execute("SELECT * FROM imagenes_proyectadas WHERE trabajo_id = ?", (t["id"],)).fetchone()
    archivo = config.fotos_path / "generadas" / fila["archivo"]
    assert fila["estado"] == "lista" and archivo.is_file() and oct(archivo.stat().st_mode)[-3:] == "600"
    assert not list((codex_home / "generated_images").iterdir()) and not list((codex_home / "shell_snapshots").iterdir())
    assert not list(config.fotos_path.glob("tmp-codex-*"))
    assert con.execute("SELECT COUNT(*) FROM imagen_limpieza").fetchone()[0] == 0
    # Pantalla del resultado
    res = cliente.get(f"/rendimiento/imagen/{t['id']}").text
    assert "Ilustración generada por IA, no es una predicción." in res and "Ilustración IA" in res
    assert ("Enviado a OpenAI (Codex, gpt-6.1-sol) el 2026-10-19: análisis con frente 2026-09-24 y calibración "
            "2025-05-08 y 2025-07-21; imagen de frente con la foto del 2026-09-24") in res
    assert 'id="ad-frente"' in res and 'aria-valuetext="50 % ilustración"' in res and "Confianza media" in res


def test_consentimiento(cliente, con, config, codex_home):
    _fotos(con, config)
    r = _generar(cliente, acepto=False)
    assert r.status_code == 422 and "Confirma que aceptas enviar las fotos a OpenAI (Codex)" in r.text
    assert _ultimo(con) is None and _llamadas(codex_home) == []


def test_lo_que_se_envia_antes_de_confirmar(cliente, con, config):
    _fotos(con, config)
    r = cliente.get("/rendimiento/imagen?fecha=2026-12-13&poses=frente").text
    assert "Lo que se envía a OpenAI" in r and "calibración de frente, antes, 2025-05-08" in r
    assert "solo la foto base del 24 sep 2026" in r and 'name="acepto"' in r


def test_cifras_en_el_analisis(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, analisis=_analisis(abdomen={"magnitud": "leve", "direccion": "menos_grasa",
                                                  "nota": "perder 2 kg de grasa abdominal"}))
    _generar(cliente)
    t = _ultimo(con)
    assert t["estado"] == "fallido" and t["error"] == "El análisis trajo cifras; no se generó ninguna imagen"
    assert len(_llamadas(codex_home)) == 1


def test_techo(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, analisis=_analisis(abdomen={"magnitud": "moderado", "direccion": "menos_grasa", "nota": "algo"}))
    _generar(cliente)
    t = _ultimo(con)
    assert "abdomen: moderado bajado a leve por el techo de 55 días" in t["registro"]
    assert json.loads(t["resultado"])["analisis"]["zonas"]["abdomen"]["magnitud"] == "leve"
    assert "- abdomen: leve, menos grasa" in _llamadas(codex_home)[1]["prompt"]


def test_json_invalido(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, texto="Te cuento: bajarás de peso.")
    _generar(cliente)
    t = _ultimo(con)
    assert t["estado"] == "fallido" and t["error"] == "Codex no devolvió el análisis en el formato pedido"
    assert len(_llamadas(codex_home)) == 1


def test_dijo_que_guardo_y_no(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, sin_imagen=True)
    _generar(cliente)
    t = _ultimo(con)
    fila = con.execute("SELECT * FROM imagenes_proyectadas WHERE trabajo_id = ?", (t["id"],)).fetchone()
    assert fila["estado"] == "fallida" and fila["error"].startswith("Codex no generó la imagen. Respondió: ") and fila["archivo"] is None
    assert t["estado"] == "fallido" and not list((config.fotos_path / "generadas").glob("*.png"))
    assert not list((codex_home / "generated_images").glob("*")) if (codex_home / "generated_images").exists() else True
    assert not list((codex_home / "shell_snapshots").iterdir()) and not list(config.fotos_path.glob("tmp-codex-*"))


def test_error_de_codex_legible(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, error="usage limit reached")
    _generar(cliente)
    t = _ultimo(con)
    assert t["estado"] == "fallido" and t["error"] == "Codex rechazó la solicitud: usage limit reached"


def test_reinicio_durante_el_paso_2(con, config, codex_home):
    hilo = codex_home / "generated_images" / "hilo-x"
    hilo.mkdir(parents=True)
    (hilo / "exec-1.png").write_bytes(b"x")
    tmp = config.fotos_path / "tmp-codex-7"
    tmp.mkdir(parents=True)
    tid = con.execute("INSERT INTO trabajos_ia (tipo, estado) VALUES ('imagen', 'corriendo')").lastrowid
    con.execute("INSERT INTO imagenes_proyectadas (trabajo_id, pose, fecha_base, fecha_objetivo) VALUES (?, 'frente', "
                "'2026-09-24', '2026-12-13')", (tid,))
    con.executemany("INSERT INTO imagen_limpieza (trabajo_id, tipo, valor) VALUES (?, ?, ?)",
                    [(tid, "hilo", "hilo-x"), (tid, "carpeta", str(tmp))])
    con.commit()
    trabajos.recuperar_interrumpidos(con)
    ip.limpiar_interrumpidos(config)
    assert not hilo.exists() and not tmp.exists()
    assert con.execute("SELECT estado FROM trabajos_ia WHERE id = ?", (tid,)).fetchone()[0] == "fallido"
    assert con.execute("SELECT estado FROM imagenes_proyectadas").fetchone()[0] == "fallida"


def test_cancelar_mata_el_proceso(tmp_path, codex_home):
    _modo(codex_home, dormir=30)
    cmd = codex.comando(str(FALSO), tmp_path, "gpt-6.1-sol", [])
    env = codex.entorno(f"{Path(sys.executable).parent}:/usr/bin:/bin", codex_home)
    with pytest.raises(codex.Cancelado):
        codex.correr(cmd, "hola", env, 20, cancelado=lambda: len(_llamadas(codex_home)) > 0)


def test_tiempo_maximo(tmp_path, codex_home):
    _modo(codex_home, dormir=30)
    cmd = codex.comando(str(FALSO), tmp_path, None, [])
    env = codex.entorno(f"{Path(sys.executable).parent}:/usr/bin:/bin", codex_home)
    with pytest.raises(codex.FalloCodex, match="tiempo máximo"):
        codex.correr(cmd, "hola", env, 1.5)


def test_cancelar_por_la_ruta(cliente, con):
    tid = con.execute("INSERT INTO trabajos_ia (tipo, estado, parametros) VALUES ('imagen', 'corriendo', '{}')").lastrowid
    con.commit()
    cliente.post(f"/rendimiento/imagen/{tid}/cancelar")
    assert tid in ip.CANCELADOS
    ip.CANCELADOS.discard(tid)


def test_modelo_de_respaldo(tmp_path):
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [
        {"slug": "oculto", "priority": 0, "visibility": "hide", "input_modalities": ["text", "image"],
         "supported_reasoning_levels": [{"effort": "max"}]},
        {"slug": "sin-max", "priority": 1, "visibility": "list", "input_modalities": ["text", "image"],
         "supported_reasoning_levels": [{"effort": "high"}]},
        {"slug": "bueno", "priority": 3, "visibility": "list", "input_modalities": ["text", "image"],
         "supported_reasoning_levels": [{"effort": "max"}]}]}))
    assert codex.modelo(tmp_path) == "bueno"
    assert codex.modelo(tmp_path / "no-existe") is None


# Resultado, borrar, resumen, navegación ---------------------------------------

def test_lado_a_lado_si_cambia_el_encuadre(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, imagen_b64=_png((100, 100)))
    _generar(cliente)
    r = cliente.get(f"/rendimiento/imagen/{_ultimo(con)['id']}").text
    assert "La ilustración cambió el encuadre" in r and "data-ad" not in r


def test_borrar_y_fuera_del_resumen(cliente, con, config, boveda):
    _fotos(con, config)
    _generar(cliente)
    fila = con.execute("SELECT * FROM imagenes_proyectadas").fetchone()
    datos = json.dumps(resumen_ia.construir(con, boveda, HOY), ensure_ascii=False)
    assert "generadas" not in datos and "imagenes_proyectadas" not in datos and "Ilustración" not in datos
    archivo = config.fotos_path / "generadas" / fila["archivo"]
    cliente.post(f"/rendimiento/imagen/archivo/{fila['id']}/borrar")
    assert not archivo.exists() and con.execute("SELECT COUNT(*) FROM imagenes_proyectadas").fetchone()[0] == 0
    assert fx.ultima(con, "frente").fecha == "2026-09-24"


def test_navegacion_y_cola_ocupada(cliente, con):
    r = cliente.get("/rendimiento/analisis").text
    assert 'href="/rendimiento/imagen"' in r and "Imagen proyectada" in r and "Imagen a 3 meses" not in r
    con.execute("INSERT INTO trabajos_ia (tipo, estado, parametros) VALUES ('imagen', 'corriendo', '{}')")
    con.commit()
    r = cliente.post("/rendimiento/ia/semana", data={"semana": "2026-W42"})
    assert "Imagen proyectada sigue corriendo" in r.text


# Ajuste tras la primera generación real -------------------------------------

def test_indicio_con_evaluadores_distintos():
    meds = [_m("2026-04-10", 81300, "Andrés"), _m("2026-10-19", 77000, "Pablo")]
    assert ip.indicio(meds) == ("indicativo (evaluadores distintos): bajó de 81,3 kg el 2026-04-10 a 77 kg el "
                                "2026-10-19, Matriz Centro Uno")
    assert ip.indicio([_m("2026-10-01", 78000), _m("2026-10-13", 77400)]) == ""   # menos de 28 días


def test_escenario_en_prompt_y_resultado(cliente, con, config, codex_home):
    _fotos(con, config)
    cliente.post("/rendimiento/imagen", data={"fecha": "2026-12-13", "poses": ["frente"], "acepto": "1",
                                              "escenario": "plan"})
    t = _ultimo(con)
    assert json.loads(t["parametros"])["escenario"] == "plan"
    p1 = _llamadas(codex_home)[0]["prompt"]
    assert "Escenario: cumpliendo el plan: entrena con esa misma frecuencia" in p1
    assert "La falta de datos baja la confianza; no obliga a poner sin_cambio" in p1
    assert "si los datos no sostienen un cambio" not in p1.lower()
    assert "Escenario: cumpliendo el plan." in cliente.get(f"/rendimiento/imagen/{t['id']}").text


def test_escenario_por_defecto(cliente, con, config):
    _fotos(con, config)
    for esc in (None, "inventado"):
        datos = {"fecha": "2026-12-13", "poses": ["frente"], "acepto": "1"} | ({"escenario": esc} if esc else {})
        cliente.post("/rendimiento/imagen", data=datos)
        assert json.loads(_ultimo(con)["parametros"])["escenario"] == "como_vas"
    r = cliente.get("/rendimiento/imagen").text
    assert 'value="como_vas" checked' in r and "Cumpliendo el plan" in r


# Límites visuales y verificación --------------------------------------------

def _filas(con):
    return con.execute("SELECT * FROM imagenes_proyectadas ORDER BY id DESC").fetchone()


def test_limites_en_el_prompt():
    a = _analisis(abdomen={"magnitud": "leve", "direccion": "menos_grasa", "nota": ""},
                  pecho={"magnitud": "muy_leve", "direccion": "menos_grasa", "nota": ""})
    p2 = ip.prompt_paso2("frente", a)
    assert "abdomen: leve, menos grasa. Límite: algo menos de volumen" in p2
    assert "no aparecen músculos, líneas ni separaciones que no se vean ya en la foto" in p2
    assert "pecho: muy leve, casi imperceptible, menos grasa. Límite: casi idéntica" in p2
    assert "No cambies el contraste, las sombras, la exposición ni el tono de la piel" in p2
    assert not any(c.isdigit() for c in p2) and "Intento anterior" not in p2


def test_verificacion_dentro(cliente, con, config, codex_home):
    _fotos(con, config)
    _generar(cliente)
    f = _filas(con)
    assert f["estado"] == "lista" and f["verificacion"] == "dentro" and f["intentos"] == 1
    assert len(_llamadas(codex_home)) == 3
    assert "Verificada: dentro de lo que indica el análisis." in cliente.get(f"/rendimiento/imagen/{f['trabajo_id']}").text


def test_se_paso_y_se_corrige(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, verificaciones=[{"zonas_excedidas": ["abdomen"], "luz_cambio": False, "nota": "abdominales marcados"},
                                      {"zonas_excedidas": [], "luz_cambio": False, "nota": "bien"}])
    _generar(cliente)
    ll = _llamadas(codex_home)
    assert len(ll) == 5
    segundo = ll[3]["prompt"]
    assert "## Intento anterior" in segundo and "se pasó en abdomen" in segundo and "claramente por debajo" in segundo
    f = _filas(con)
    assert f["verificacion"] == "dentro" and f["intentos"] == 2


def test_se_paso_dos_veces(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, verificaciones=[{"zonas_excedidas": [], "luz_cambio": True, "nota": "más contraste en el torso"}])
    _generar(cliente)
    f = _filas(con)
    assert f["estado"] == "lista" and f["verificacion"] == "exagerada" and f["intentos"] == 2 and f["archivo"]
    assert "cambió la luz o el contraste" in _llamadas(codex_home)[3]["prompt"]
    r = cliente.get(f"/rendimiento/imagen/{f['trabajo_id']}").text
    assert "Más marcada de lo que indica el análisis: más contraste en el torso. No la tomes como referencia." in r


def test_verificacion_invalida(cliente, con, config, codex_home):
    _fotos(con, config)
    _modo(codex_home, verificaciones=["no sé"])
    _generar(cliente)
    f = _filas(con)
    assert f["estado"] == "lista" and f["verificacion"] == "sin_verificar" and f["archivo"]
    assert "No se pudo verificar." in cliente.get(f"/rendimiento/imagen/{f['trabajo_id']}").text
    assert len(_llamadas(codex_home)) == 3


def test_historial_con_icono_y_escenario(cliente, con, config):
    _fotos(con, config)
    cliente.post("/rendimiento/imagen", data={"fecha": "2026-12-13", "poses": ["frente"], "acepto": "1", "escenario": "plan"})
    r = cliente.get("/rendimiento/imagen").text
    fila = r[r.index('href="/rendimiento/imagen/'):]
    fila = fila[:fila.index("</a>")]
    assert fila.count("<svg") == 2 and "1 pose · cumpliendo el plan · lista" in fila


def test_auditoria_borrar_ilustracion_pide_confirmacion(cliente, con, config):
    _fotos(con, config)
    _generar(cliente)
    r = cliente.get(f"/rendimiento/imagen/{_ultimo(con)['id']}").text
    assert "return confirm('¿Borrar esta ilustración? No se puede deshacer.')" in r
