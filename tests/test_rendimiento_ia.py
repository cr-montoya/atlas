"""Requirement: Trabajos de Claude (análisis de semana, combate y fotos). Claude se simula: nunca se llama."""

import io
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Config
from app.core.db import conectar, migrar
from app.modules.rendimiento import analisis, consultas as q, rutas, trabajos, vault
from app.modules.rendimiento.filtros import md_ia
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
HOY = date(2026, 10, 17)

RESPUESTA = ("## Lo que veo\n- Hiciste 3 sesiones — una menos que la semana anterior.\n- **Sueño** estable.\n"
             "## Qué ajustar\n- [I] Sube el sueño a 8 h <script>alert(1)</script>\n"
             "## Para hablar con tus profesionales\n- ¿Puedo volver al press?")

FALSO = r'''#!{python}
import json, os, sys, time
from pathlib import Path
modo = os.environ.get("FALSO_MODO", "ok")
args = sys.argv[1:]
vistos = []
for i, a in enumerate(args):
    if a == "--add-dir":
        vistos += sorted(os.listdir(args[i + 1]))
Path(os.environ["FALSO_ARGS"]).write_text(json.dumps({{"args": args, "stdin": sys.stdin.read(), "cwd": os.getcwd(),
                                                      "vistos": vistos}}))
if modo == "lento":
    time.sleep(5)
if modo == "error":
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": True, "result": "Credit balance is too low"}}))
    sys.exit(1)
if modo == "vacio":
    sys.exit(2)
print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": {respuesta},
                  "total_cost_usd": 0.12, "duration_ms": 61000, "num_turns": 4}}))
'''


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    vault.limpiar_cache()
    return destino


@pytest.fixture
def falso(tmp_path, monkeypatch):
    ruta = tmp_path / "claude-falso"
    ruta.write_text(FALSO.format(python=sys.executable, respuesta=repr(RESPUESTA)))
    ruta.chmod(0o755)
    monkeypatch.setenv("FALSO_ARGS", str(tmp_path / "args.json"))
    return ruta


@pytest.fixture
def config(tmp_path, boveda, falso):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db", exports_path=tmp_path / "exports",
                  vault_path=boveda, fotos_path=tmp_path / "fotos", claude_cmd=str(falso), tiempo_max_s=2)


@pytest.fixture(autouse=True)
def sincrono(monkeypatch):
    real = trabajos.lanzar
    monkeypatch.setattr(trabajos, "lanzar", lambda cfg, tid, en_hilo=True: real(cfg, tid, en_hilo=False))
    monkeypatch.setattr(rutas, "hoy", lambda: HOY)


def _llamada(tmp_path) -> dict:
    return json.loads((tmp_path / "args.json").read_text())


def _semana(cliente, semana="2026-W42"):
    return cliente.post("/rendimiento/ia/semana", data={"semana": semana}, follow_redirects=False)


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (60, 80), (120, 90, 60)).save(buf, "JPEG")
    return buf.getvalue()


def _fotos(cliente, con):
    for fecha in ("2026-08-01", "2026-10-17"):
        cliente.post("/rendimiento/fotos", data={"fecha": fecha, "pose": "frente"},
                     files={"foto": ("f.jpg", _jpeg(), "image/jpeg")}, follow_redirects=False)
    cliente.post("/rendimiento/fotos", data={"fecha": "2026-10-17", "pose": "espalda"},
                 files={"foto": ("f.jpg", _jpeg(), "image/jpeg")}, follow_redirects=False)
    return {r["fecha"] + r["pose"]: r["id"] for r in con.execute("SELECT * FROM fotos_cuerpo")}


def _combate(con, n=3):
    t = con.execute("SELECT id FROM tecnicas WHERE disciplina = 'judo' AND nombre = 'Uchi mata'").fetchone()[0]
    for i in range(n):
        sid = q.crear_sesion(con, f"2026-10-1{i}", "combate", "judo")
        b = q.crear_bloque(con, sid, "randori", 1500, 5)
        q.agregar_entrada(con, b, tecnica_id=t, resultado="funciono")
        q.guardar_sesion(con, sid, duracion_s=3600, molestia=2, sensaciones=None, notas="", clave_importada=None)


# Solo lectura y reglas de contenido ----------------------------------------

def test_analisis_de_semana_solo_lectura(cliente, con, tmp_path, boveda):
    r = _semana(cliente)
    assert r.status_code == 303
    t = trabajos.ultimo(con, "analisis_semana")
    assert t["estado"] == "listo", t["error"]
    llamada = _llamada(tmp_path)
    args = llamada["args"]
    assert llamada["cwd"] == str(boveda)
    assert args[args.index("--tools") + 1] == "Read,Grep,Glob"
    permitidas = args[args.index("--allowedTools") + 1: args.index("--permission-mode")]
    assert permitidas == ["Read", "Grep", "Glob"]
    assert "--strict-mcp-config" in args and "--mcp-config" not in args  # sin MCP
    assert not any(h in " ".join(args) for h in ("Write", "Edit", "Bash", "mcp__"))
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--permission-mode") + 1] == "dontAsk"


def test_prompt_con_reglas_de_contenido_y_datos(cliente, tmp_path):
    _semana(cliente)
    prompt = _llamada(tmp_path)["stdin"]
    for regla in ("[I]", "sin el carácter de raya larga", "No hagas diagnósticos",
                  "ni reemplaces al entrenador, al fisio, a la nutricionista ni al ortopedista",
                  "solo resume lo que ellos indicaron", "español"):
        assert regla in prompt
    assert "2026-W42" in prompt and "2026-W41" in prompt and '"metricas"' in prompt
    assert "02_Health/lesiones.md" in prompt


def test_resultado_guardado_y_visible_sin_raya_larga(cliente, con):
    _semana(cliente)
    t = trabajos.ultimo(con, "analisis_semana")
    res = json.loads(t["resultado"])
    assert "—" not in res["texto"] and res["costo_usd"] == 0.12 and res["turnos"] == 4
    r = cliente.get(f"/rendimiento/ia/{t['id']}")
    assert r.status_code == 200
    assert "<h2>Qué ajustar</h2>" in r.text and "[I] Sube el sueño" in r.text
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;" in r.text
    assert "—" not in r.text
    assert "Registro del trabajo" in r.text


def test_tablero_muestra_la_ultima_recomendacion(cliente, con):
    assert "Sin análisis de Claude todavía" in cliente.get("/rendimiento").text
    _semana(cliente)
    r = cliente.get("/rendimiento")
    assert "Última recomendación de Claude" in r.text
    assert "[I] Sube el sueño" in r.text and "Hiciste 3 sesiones" not in r.text  # solo "Qué ajustar"
    assert "Ver el análisis completo" in r.text


# Estado en vivo y fallas ---------------------------------------------------

def test_estado_en_vivo(cliente, con):
    tid, _ = trabajos.encolar(con, "analisis_semana", {"semana": "2026-W42"})
    with con:
        con.execute("UPDATE trabajos_ia SET estado = 'corriendo' WHERE id = ?", (tid,))
    pagina = cliente.get("/rendimiento/ia")
    assert "Pensando…" in pagina.text and f'hx-get="/rendimiento/ia/estado/{tid}"' in pagina.text
    assert pagina.text.count("disabled") >= 2  # no se puede lanzar otro
    r = cliente.get(f"/rendimiento/ia/estado/{tid}", headers={"HX-Request": "true"})
    assert "Pensando…" in r.text and 'hx-trigger="every 2s"' in r.text and "HX-Redirect" not in r.headers
    with con:
        con.execute("UPDATE trabajos_ia SET estado = 'listo', resultado = '{\"texto\": \"ok\"}' WHERE id = ?", (tid,))
    r = cliente.get(f"/rendimiento/ia/estado/{tid}", headers={"HX-Request": "true"})
    assert r.headers["HX-Redirect"] == f"/rendimiento/ia/{tid}" and "every 2s" not in r.text


@pytest.mark.parametrize("modo, mensaje", [
    ("error", "Claude respondió con error: Credit balance is too low"),
    ("vacio", "Claude terminó con error (código 2)"),
    ("lento", "Pasó el tiempo máximo"),
])
def test_falla_legible_y_la_app_sigue(cliente, con, monkeypatch, modo, mensaje):
    monkeypatch.setenv("FALSO_MODO", modo)
    r = cliente.post("/rendimiento/ia/semana", data={"semana": "2026-W42"})
    t = trabajos.ultimo(con, "analisis_semana")
    assert t["estado"] == "fallido" and mensaje in t["error"]
    assert "Analiza mi semana falló" in r.text
    assert cliente.get("/rendimiento").status_code == 200
    estado = cliente.get(f"/rendimiento/ia/estado/{t['id']}", headers={"HX-Request": "true"})
    assert estado.headers.get("HX-Refresh") == "true"


def test_sin_claude_instalado(tmp_path, boveda):
    cfg = Config(pin=PIN, secreto="s", db_path=tmp_path / "otra.db", vault_path=boveda, claude_cmd=str(tmp_path / "no-existe"))
    con = conectar(cfg.db_path)
    migrar(con)
    tid, _ = trabajos.encolar(con, "analisis_semana", {"semana": "2026-W42", "hoy": "2026-10-17"})
    trabajos.lanzar(cfg, tid, en_hilo=False)
    t = trabajos.trabajo(con, tid)
    assert t["estado"] == "fallido" and "No encontré Claude Code" in t["error"]
    con.close()


def test_un_trabajo_a_la_vez(cliente, con):
    tid, _ = trabajos.encolar(con, "sincronizar", {})
    r = _semana(cliente)
    assert r.status_code == 409 and "La sincronización sigue corriendo" in r.text
    assert trabajos.ultimo(con, "analisis_semana") is None
    with con:
        con.execute("UPDATE trabajos_ia SET estado = 'listo' WHERE id = ?", (tid,))
    trabajos.encolar(con, "analisis_combate", {"n": 5})
    act = cliente.get("/rendimiento/actividades")
    assert "Claude está haciendo un análisis" in act.text and "<span>Sincronizando…</span>" not in act.text


def test_semana_fuera_de_rango(cliente, con):
    r = _semana(cliente, "2020-W01")
    assert r.status_code == 422 and "Elige una de las últimas 12 semanas" in r.text


# Combate -------------------------------------------------------------------

def test_combate_con_referente(cliente, con, tmp_path):
    _combate(con)
    r = cliente.post("/rendimiento/ia/combate", data={"n": "10", "disciplina": "judo", "referente": "Sanshiro Murao"},
                     follow_redirects=False)
    assert r.status_code == 303
    t = trabajos.ultimo(con, "analisis_combate")
    assert t["estado"] == "listo", t["error"]
    prompt = _llamada(tmp_path)["stdin"]
    assert "últimas 10 sesiones de Judo" in prompt and "Sanshiro Murao" in prompt and "Uchi mata" in prompt
    assert "si no conoces bien su estilo, dilo" in prompt
    assert "Últimas 10 sesiones de Judo, frente a Sanshiro Murao" in cliente.get(f"/rendimiento/ia/{t['id']}").text


def test_combate_sin_sesiones(cliente, con):
    r = cliente.post("/rendimiento/ia/combate", data={"n": "10", "disciplina": "bjj"})
    assert r.status_code == 422 and "No hay sesiones de BJJ registradas" in r.text
    assert trabajos.ultimo(con, "analisis_combate") is None


# Fotos ---------------------------------------------------------------------

def test_fotos_piden_confirmacion(cliente, con):
    ids = _fotos(cliente, con)
    r = cliente.post("/rendimiento/ia/fotos", data={"pose": "frente", "a": ids["2026-08-01frente"], "b": ids["2026-10-17frente"]})
    assert r.status_code == 422 and "Confirma que aceptas enviar las dos fotos a Anthropic" in r.text
    assert trabajos.ultimo(con, "comparar_fotos") is None


def test_fotos_misma_pose(cliente, con):
    ids = _fotos(cliente, con)
    r = cliente.post("/rendimiento/ia/fotos", data={"a": ids["2026-08-01frente"], "b": ids["2026-10-17espalda"], "confirmo": "1"})
    assert r.status_code == 422 and "misma pose" in r.text


def test_fotos_solo_las_dos_elegidas_y_envio_registrado(cliente, con, tmp_path, config):
    ids = _fotos(cliente, con)
    r = cliente.post("/rendimiento/ia/fotos", data={"pose": "frente", "a": ids["2026-10-17frente"],
                                                    "b": ids["2026-08-01frente"], "confirmo": "1"}, follow_redirects=False)
    assert r.status_code == 303
    t = trabajos.ultimo(con, "comparar_fotos")
    assert t["estado"] == "listo", t["error"]
    llamada = _llamada(tmp_path)
    # Solo una copia temporal con las dos fotos (ordenadas antes y después), nunca toda data/fotos
    assert llamada["vistos"] == ["antes_2026-08-01_frente.jpg", "despues_2026-10-17_frente.jpg"]
    carpeta = Path(llamada["args"][llamada["args"].index("--add-dir") + 1])
    assert not carpeta.exists() and str(config.fotos_path) not in llamada["args"]
    assert "Lee las dos imágenes con Read" in llamada["stdin"] and "no estimes porcentaje graso" in llamada["stdin"]
    res = json.loads(t["resultado"])
    assert "enviadas a Anthropic (Claude)" in res["envio"]
    pagina = cliente.get(f"/rendimiento/ia/{t['id']}")
    assert "enviadas a Anthropic (Claude)" in pagina.text and "Frente: 2026-08-01 y 2026-10-17" in pagina.text


def test_enlace_desde_antes_y_despues(cliente, con):
    ids = _fotos(cliente, con)
    r = cliente.get("/rendimiento/fotos?pose=frente")
    assert f"/rendimiento/ia?pose=frente&amp;a={ids['2026-08-01frente']}&amp;b={ids['2026-10-17frente']}" in r.text


# Pantalla y filtro ---------------------------------------------------------

def test_pantalla_y_menu(cliente):
    assert "Analiza mi semana" in cliente.get("/rendimiento/ia").text
    r = cliente.get("/rendimiento/ia")
    assert r.status_code == 200
    for texto in ("Analiza mi semana", "Analiza mi combate", "Compara mis fotos", "Todavía no has pedido ningún análisis"):
        assert texto in r.text
    assert "—" not in r.text


def test_md_ia_escapa_html():
    html = md_ia("## Hola\n- <b>x</b> **y** ([nota](02_Health/x.md))\n1. uno\ntexto")
    assert "(nota)" in html and "02_Health/x.md" not in html
    assert "&lt;b&gt;" in html and "<strong>y</strong>" in html and "<ol>" in html and "<p>texto</p>" in html


def test_resultado_entiende_errores():
    with pytest.raises(RuntimeError, match="Claude respondió con error"):
        analisis.resultado(json.dumps({"is_error": True, "result": "x"}))
    with pytest.raises(RuntimeError, match="sin texto"):
        analisis.resultado(json.dumps({"is_error": False, "result": ""}))
    assert analisis.resultado("texto suelto")["texto"] == "texto suelto"


def test_portada_de_analisis_en_la_navegacion(cliente, con):
    r = cliente.get("/rendimiento/analisis")
    assert r.status_code == 200
    nav = r.text
    assert 'href="/rendimiento/analisis"' in nav and ">Comparar<" not in nav
    for ruta in ("/rendimiento/comparar", "/rendimiento/ia", "/rendimiento/combate", "/rendimiento/fotos"):
        assert f'href="{ruta}"' in r.text
    assert "Imagen proyectada" in r.text and 'href="/rendimiento/imagen"' in r.text and "Imagen a 3 meses" not in r.text
    mas = cliente.get("/rendimiento/mas").text
    assert 'href="/rendimiento/ia"' not in mas and 'href="/rendimiento/fotos"' not in mas
    for ruta in ("/rendimiento/comparar", "/rendimiento/ia", "/rendimiento/combate", "/rendimiento/fotos"):
        assert 'aria-current="page"' in cliente.get(ruta).text.split('href="/rendimiento/analisis"')[1][:80]
