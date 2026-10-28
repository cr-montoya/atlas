"""Spec openspec/changes/v1-demo: configuración aislada, acciones externas apagadas, semilla reproducible y sin datos
reales, pantallas con datos y cookies separadas. Todo corre en tmp_path, con un HOME y una app "real" ficticios."""

import hashlib
import json
import sqlite3
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config as cfgmod
from app.core.config import Config
from app.demo import semilla
from app.main import crear_app
from app.modules.rendimiento import competencia, rutas, trabajos

HOY = date(2026, 10, 26)
PIN_DEMO = "2468"
# Palabras que nunca pueden aparecer en la demo. La lista con los nombres reales (personas, empresas, bancos,
# profesionales) vive fuera del repo, en tests/prohibidas.local.txt (una por línea); sin ella se usa esta base.
_LOCAL = Path(__file__).with_name("prohibidas.local.txt")
PROHIBIDAS = ("rappi", "mastercard", "black", "lenovo") + (
    tuple(l.strip().lower() for l in _LOCAL.read_text().splitlines() if l.strip()) if _LOCAL.exists() else ())
# Columnas con la hora de creación: lo único que puede cambiar entre dos corridas iguales.
MARCAS = {"creado", "creada", "actualizado", "actualizada"}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    """Una app real ficticia en tmp_path/real, un HOME ficticio con su vault y la demo en tmp_path/demo-wt."""
    casa, real = tmp_path / "casa", tmp_path / "real"
    for p in (casa / "Documents" / "vault", casa / ".codex", real / "data", real / "exports"):
        p.mkdir(parents=True)
    (real / ".env").write_text("BRAIN_PIN=1111\nBRAIN_SECRETO=real\nBRAIN_VAULT=~/Documents/vault\n"
                               "BRAIN_ESCRIBIR_COMIDAS=1\n")
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("BRAIN_RAIZ_REAL", str(real))
    for v in ("BRAIN_DEMO", "BRAIN_PIN", "BRAIN_SECRETO", "BRAIN_DB", "BRAIN_VAULT", "BRAIN_FOTOS", "BRAIN_EXPORTS",
              "CODEX_HOME", "BRAIN_COOKIE", "BRAIN_ESCRIBIR_COMIDAS", "BRAIN_SINCRONIZAR_AL_ARRANCAR"):
        monkeypatch.delenv(v, raising=False)
    wt = tmp_path / "demo-wt"
    wt.mkdir()
    return {"casa": casa, "real": real, "wt": wt}


def _env_demo(wt: Path, **extra) -> None:
    valores = {"BRAIN_PIN": PIN_DEMO, "BRAIN_SECRETO": "secreto-demo", "BRAIN_DB": "demo/datos/demo.db",
               "BRAIN_VAULT": "demo/datos/vault", "BRAIN_FOTOS": "demo/datos/fotos",
               "BRAIN_EXPORTS": "demo/datos/exports", "CODEX_HOME": "demo/datos/codex"} | extra
    (wt / ".env").write_text("".join(f"{k}={v}\n" for k, v in valores.items() if v is not None))


def _cfg(raiz: Path) -> Config:
    d = raiz / "demo" / "datos"
    return Config(pin=PIN_DEMO, secreto="secreto-demo", db_path=d / "demo.db", vault_path=d / "vault",
                  fotos_path=d / "fotos", exports_path=d / "exports", codex_home=d / "codex", demo=True,
                  cookie=cfgmod.COOKIE_DEMO, datos_demo=d)


# Configuración aislada -------------------------------------------------------

def test_lee_la_config_de_su_worktree(entorno, monkeypatch):
    _env_demo(entorno["wt"])
    monkeypatch.setenv("BRAIN_ESCRIBIR_COMIDAS", "1")
    monkeypatch.setenv("BRAIN_SINCRONIZAR_AL_ARRANCAR", "1")
    cfg = cfgmod.leer_config_demo(entorno["wt"])
    assert cfg.demo and cfg.cookie == "atlas_demo_sesion" and cfg.pin == PIN_DEMO
    assert cfg.db_path == entorno["wt"] / "demo/datos/demo.db" and cfg.vault_path == entorno["wt"] / "demo/datos/vault"
    assert not cfg.escribir_comidas and not cfg.sincronizar_al_arrancar


def test_demo_desde_la_carpeta_real(entorno, monkeypatch):
    leidos = []
    monkeypatch.setattr(cfgmod, "cargar_env", lambda ruta=None: leidos.append(ruta))
    with pytest.raises(RuntimeError, match="propio worktree"):
        cfgmod.leer_config_demo(entorno["real"])
    with pytest.raises(RuntimeError, match="propio worktree"):
        cfgmod.leer_config_demo(entorno["real"] / "sub")
    assert leidos == []


def test_el_env_real_no_rellena_huecos(entorno):
    _env_demo(entorno["wt"], BRAIN_VAULT=None)
    with pytest.raises(RuntimeError, match="BRAIN_VAULT"):
        cfgmod.leer_config_demo(entorno["wt"])


def test_brain_demo_no_se_toma_de_un_env(entorno, monkeypatch):
    (entorno["wt"] / "otro.env").write_text("BRAIN_DEMO=1\nBRAIN_PIN=9\n")
    cfgmod.cargar_env(entorno["wt"] / "otro.env")
    assert not cfgmod.es_demo()
    monkeypatch.delenv("BRAIN_PIN")


def test_una_ruta_apunta_a_la_base_real(entorno):
    real_db = entorno["real"] / "data" / "finanzas.db"
    cfg = _cfg(entorno["wt"])
    malo = Config(**{**cfg.__dict__, "db_path": real_db})
    with pytest.raises(RuntimeError, match="db_path"):
        crear_app(malo)
    assert not real_db.exists()
    _env_demo(entorno["wt"], BRAIN_DB=str(real_db))
    with pytest.raises(RuntimeError, match="db_path"):
        cfgmod.leer_config_demo(entorno["wt"])


def test_ruta_fuera_de_demo_datos(entorno, tmp_path):
    cfg = _cfg(entorno["wt"])
    with pytest.raises(RuntimeError, match="exports_path"):
        cfgmod.validar_demo(Config(**{**cfg.__dict__, "exports_path": tmp_path / "otra"}))


def test_enlace_simbolico_hacia_el_vault_real(entorno):
    cfg = _cfg(entorno["wt"])
    cfg.vault_path.parent.mkdir(parents=True)
    cfg.vault_path.symlink_to(entorno["casa"] / "Documents" / "vault")
    with pytest.raises(RuntimeError, match="vault_path"):
        cfgmod.validar_demo(cfg)


def test_codex_home_real(entorno):
    cfg = _cfg(entorno["wt"])
    with pytest.raises(RuntimeError, match="codex_home"):
        cfgmod.validar_demo(Config(**{**cfg.__dict__, "codex_home": entorno["casa"] / ".codex"}))


def test_fuera_de_la_demo_nada_cambia(config):
    assert not config.demo and config.cookie == "brain_sesion"
    crear_app(config)  # sin validar_demo


# La demo generada ------------------------------------------------------------

@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("demo-wt")
    cfg = _cfg(raiz)
    semilla.generar(cfg, HOY)
    return cfg


@pytest.fixture
def cliente_demo(demo, monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: HOY)
    monkeypatch.setattr(competencia, "ahora", lambda: datetime(2026, 10, 26, 9, 0))
    with TestClient(crear_app(demo)) as c:
        c.post("/login", data={"pin": PIN_DEMO})
        yield c


def _filas(db: Path) -> dict[str, list[tuple]]:
    con = sqlite3.connect(db)
    tablas = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                                        " AND name != '_migraciones'")]  # su fecha es la de aplicar la migración
    salida = {}
    for t in tablas:
        cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})") if c[1] not in MARCAS]
        salida[t] = sorted(con.execute(f"SELECT {', '.join(cols)} FROM {t}").fetchall(), key=repr)
    con.close()
    return salida


def _archivos(carpeta: Path) -> dict[str, str]:
    return {str(p.relative_to(carpeta)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(carpeta.rglob("*")) if p.is_file()}


def test_reproducible(demo, tmp_path):
    otra = _cfg(tmp_path)
    semilla.generar(otra, HOY)
    assert _archivos(demo.vault_path) == _archivos(otra.vault_path)
    assert _archivos(demo.fotos_path) == _archivos(otra.fotos_path)
    assert _filas(demo.db_path) == _filas(otra.db_path)


def test_semilla_exige_modo_demo(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(RuntimeError, match="modo demo"):
        semilla.generar(Config(**{**cfg.__dict__, "demo": False}), HOY)


def _sin_tildes(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto) if not unicodedata.combining(c)).lower()


def test_nada_real_en_los_datos(demo):
    textos = []
    con = sqlite3.connect(demo.db_path)
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"):
        textos += [repr(fila) for fila in con.execute(f"SELECT * FROM {t}")]
    con.close()
    for carpeta in (demo.vault_path, demo.fotos_path):
        for p in carpeta.rglob("*"):
            textos.append(str(p.relative_to(carpeta)))
            if p.is_file() and p.suffix in (".md", ".csv"):
                textos.append(p.read_text(encoding="utf-8"))
    todo = _sin_tildes("\n".join(textos))
    encontradas = [w for w in PROHIBIDAS if w in todo]
    assert not encontradas, encontradas


PANTALLAS = {  # ruta -> texto que prueba que hay datos
    "/": "Tasa de ahorro", "/gasto": "Últimos 30 días", "/deudas": "Crédito apartamento", "/metas": "6 meses",
    "/futuro": "Proyección a 24 meses", "/rendimiento": "Cómo vienes",
    "/rendimiento/tests": "CMJ", "/rendimiento/comidas": "Comidas", "/rendimiento/competencia": "Open de Grappling",
    "/rendimiento/sensaciones/historial": "Body Battery", "/rendimiento/fotos": "Perfil derecho",
    "/rendimiento/ia": "Análisis anteriores", "/rendimiento/combate": "Guardia cerrada",
}


def test_pantallas_con_datos(cliente_demo, demo):
    con = sqlite3.connect(demo.db_path)
    carrera = con.execute("SELECT MAX(fecha) FROM sesiones WHERE disciplina = 'carrera'").fetchone()[0]
    con.close()
    for ruta, texto in {**PANTALLAS, f"/rendimiento/dia/{carrera}": "Carrera"}.items():
        r = cliente_demo.get(ruta)
        assert r.status_code == 200, ruta
        assert "Demo con datos ficticios" in r.text, ruta
        assert texto in r.text, (ruta, texto)


def test_running(demo):
    con = sqlite3.connect(demo.db_path)
    carreras = con.execute("SELECT COUNT(*) FROM sesiones WHERE disciplina = 'carrera'").fetchone()[0]
    con.close()
    assert carreras > 40
    garmin = next((demo.vault_path / "03_Training/imports/garmin").glob("*actividades*.md")).read_text()
    assert "| Carrera |" in garmin


def test_nada_real_en_las_pantallas(cliente_demo, demo):
    """Las plantillas tienen textos pensados para la app real (Tarjeta Uno, la tarjeta...): en la demo no se ven."""
    import re
    from app.core import auth
    from app.main import ROUTERS
    con = sqlite3.connect(demo.db_path)
    uno = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    extra = ["/rendimiento/sesiones/" + str(uno("SELECT id FROM sesiones WHERE tipo = 'combate'")),
             "/rendimiento/sesiones/" + str(uno("SELECT id FROM sesiones WHERE tipo = 'fuerza'")),
             f"/rendimiento/ia/{uno('SELECT id FROM trabajos_ia')}", f"/rendimiento/voz/{uno('SELECT id FROM voz_entradas')}",
             f"/quincena/{uno('SELECT MAX(id) FROM quincenas')}", "/deudas/1", "/fondos/1",
             f"/rendimiento/tests/{uno('SELECT id FROM tests')}", "/rendimiento/tests/nuevo?tipo=antropometria",
             "/rendimiento/comidas/2026-10-25/almuerzo", "/rendimiento/imagen?pose=frente", "/plantillas/15"]
    con.close()
    rutas_get = sorted({r.path for rt in (*ROUTERS, auth.router) for r in rt.routes
                        if "GET" in getattr(r, "methods", set()) and "{" not in r.path})
    for ruta in rutas_get + extra:
        r = cliente_demo.get(ruta)
        assert r.status_code < 500, ruta
        texto = _sin_tildes(re.sub(r"<script.*?</script>", "", r.text, flags=re.S))
        encontradas = [w for w in PROHIBIDAS if re.search(r"\b" + re.escape(w), texto)]
        assert not encontradas, (ruta, encontradas)


# Acciones externas apagadas --------------------------------------------------

ACCIONES = [("/rendimiento/sincronizar", {}), ("/rendimiento/ia/semana", {"semana": "2026-W43"}),
            ("/rendimiento/ia/combate", {"n": "8", "disciplina": "bjj"}), ("/rendimiento/ia/fotos", {}),
            ("/rendimiento/ia/rellenar-salud", {}), ("/rendimiento/imagen", {}),
            ("/rendimiento/voz", {"texto": "almorcé arroz"}), ("/rendimiento/voz/1/reintentar", {}),
            ("/rendimiento/voz/1/responder", {"texto": "sí"})]


def test_ningun_proceso_externo(cliente_demo, demo, monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError(f"Se intentó ejecutar un proceso en la demo: {a[:1]}")
    monkeypatch.setattr(subprocess, "run", prohibido)
    monkeypatch.setattr(subprocess, "Popen", prohibido)
    antes = sqlite3.connect(demo.db_path).execute("SELECT COUNT(*) FROM trabajos_ia").fetchone()[0]
    for ruta, datos in ACCIONES:
        r = cliente_demo.post(ruta, data=datos, headers={"Origin": "http://testserver"})
        assert r.status_code == 409, ruta
        assert "No disponible en la demo" in r.text, ruta
    rutas_get = sorted({r.path for r in crear_app(demo).routes if "GET" in getattr(r, "methods", set())})
    from app.main import ROUTERS
    rutas_get += sorted({r.path for rt in ROUTERS for r in rt.routes
                         if "GET" in getattr(r, "methods", set()) and "{" not in r.path})
    for ruta in rutas_get:
        cliente_demo.get(ruta)
    despues = sqlite3.connect(demo.db_path).execute("SELECT COUNT(*) FROM trabajos_ia").fetchone()[0]
    assert despues == antes


def test_htmx_recibe_el_aviso(cliente_demo):
    r = cliente_demo.post("/rendimiento/sincronizar", headers={"HX-Request": "true"})
    assert r.status_code == 409 and "No disponible en la demo" in r.text and "<html" not in r.text


def test_guardas_internas(demo):
    from app.core.demo import NoDisponibleEnDemo
    from app.modules.rendimiento import voz
    with pytest.raises(NoDisponibleEnDemo):
        trabajos.lanzar(demo, 1, en_hilo=False)
    with pytest.raises(NoDisponibleEnDemo):
        trabajos.sincronizar_al_arrancar(demo, HOY)
    with pytest.raises(NoDisponibleEnDemo):
        voz.interpretar(demo, "texto")
    with pytest.raises(NoDisponibleEnDemo):
        voz.transcribir(demo, demo.fotos_path / "x.webm", "")


def test_botones_deshabilitados(cliente_demo):
    html = cliente_demo.get("/rendimiento/ia").text
    assert html.count("No disponible en la demo") >= 4
    assert "data-grabar" not in cliente_demo.get("/rendimiento/voz").text
    assert "No disponible en la demo" in cliente_demo.get("/rendimiento/imagen").text


def test_comida_guardada_no_escribe_vault(cliente_demo, demo, monkeypatch):
    from app.modules.rendimiento import nutricion
    monkeypatch.setattr(nutricion, "escribir_vault", lambda *a, **k: pytest.fail("escribió en el vault"))
    antes = _archivos(demo.vault_path)
    r = cliente_demo.post("/rendimiento/comidas/2026-10-26/almuerzo", data={"accion": "plan", "texto": "arroz"})
    assert r.status_code in (200, 303)
    con = sqlite3.connect(demo.db_path)
    assert con.execute("SELECT texto FROM comidas_registro WHERE fecha = '2026-10-26' AND momento = 'almuerzo'").fetchone()
    con.close()
    assert _archivos(demo.vault_path) == antes


def test_certificado_raiz_404(cliente_demo):
    assert cliente_demo.get("/caddy-raiz.crt").status_code == 404


# Cookies separadas ------------------------------------------------------------

def test_cookies_separadas(demo, config):
    with TestClient(crear_app(demo)) as c:
        r = c.post("/login", data={"pin": PIN_DEMO}, follow_redirects=False)
        assert set(r.cookies) == {"atlas_demo_sesion"}
        cookie_demo = r.cookies["atlas_demo_sesion"]
    with TestClient(crear_app(config)) as real:
        real.cookies.set("atlas_demo_sesion", cookie_demo)
        assert real.get("/", follow_redirects=False).status_code == 303
        real.post("/login", data={"pin": config.pin})
        cookie_real = real.cookies.get("brain_sesion")
    with TestClient(crear_app(demo)) as c:
        c.cookies.set("brain_sesion", cookie_real)
        assert c.get("/", follow_redirects=False).status_code == 303
        c.cookies.set("atlas_demo_sesion", cookie_real)  # aunque se llame igual, otro secreto
        assert c.get("/", follow_redirects=False).status_code == 303
