"""Fase 0 de rendimiento: app multi-módulo sin romper finanzas."""

import json
import stat
from datetime import date

from fastapi.testclient import TestClient

from app.core import auth, config as cfg_mod, db
from app.core.modulos import FINANZAS, RENDIMIENTO, modulo_de
from app.core.resumen import escribir_atomico, escribir_par, sobre
from tests.conftest import PIN


# Requirement: App multi-módulo

def test_selector_lleva_a_rendimiento_con_su_navegacion(cliente):
    r = cliente.get("/rendimiento")
    assert r.status_code == 200
    html = r.text
    assert 'class="selector-modulo"' in html
    assert 'href="/rendimiento" aria-current="true">Rendimiento' in html
    for s in RENDIMIENTO.secciones:
        assert f'href="{s.ruta}"' in html and f"<span>{s.nombre}</span>" in html
    assert 'href="/rendimiento" aria-current="page"' in html  # Hoy activo
    assert "<span>Quincena</span>" not in html


def test_finanzas_intacta_con_su_navegacion(cliente):
    r = cliente.get("/quincena")
    assert r.status_code == 200
    for s in FINANZAS.secciones:
        assert f"<span>{s.nombre}</span>" in r.text
    assert 'href="/" aria-current="true">Finanzas' in r.text
    assert "<span>Registrar</span>" not in r.text


def test_rendimiento_pide_pin(anonimo):
    r = anonimo.get("/rendimiento", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_modulo_por_ruta():
    assert modulo_de("/") is FINANZAS
    assert modulo_de("/quincena/3") is FINANZAS
    assert modulo_de("/rendimiento") is RENDIMIENTO
    assert modulo_de("/rendimiento/tests") is RENDIMIENTO
    assert modulo_de("/rendimientos") is FINANZAS


def test_migraciones_por_modulo(tmp_path, monkeypatch):
    modulos = tmp_path / "modules"
    (modulos / "finanzas" / "migrations").mkdir(parents=True)
    (modulos / "finanzas" / "migrations" / "001_inicial.sql").write_text("CREATE TABLE a (x INTEGER);")
    monkeypatch.setattr(db, "MODULOS", modulos)
    con = db.conectar(tmp_path / "m.db")
    assert db.migrar(con) == ["finanzas/001_inicial.sql"]

    (modulos / "rendimiento" / "migrations").mkdir(parents=True)
    (modulos / "rendimiento" / "migrations" / "001_inicial.sql").write_text("CREATE TABLE b (y INTEGER);")
    # Si finanzas se volviera a aplicar, CREATE TABLE a fallaría.
    assert db.migrar(con) == ["rendimiento/001_inicial.sql"]
    nombres = [r[0] for r in con.execute("SELECT nombre FROM _migraciones ORDER BY nombre")]
    assert nombres == ["finanzas/001_inicial.sql", "rendimiento/001_inicial.sql"]
    assert db.migrar(con) == []
    con.close()


def test_migraciones_reales_de_todos_los_modulos(con):
    nombres = {r[0] for r in con.execute("SELECT nombre FROM _migraciones")}
    for carpeta in db.carpetas_migraciones():
        for archivo in carpeta.glob("*.sql"):
            assert f"{carpeta.parent.name}/{archivo.name}" in nombres


# Configuración y sesión

def test_brain_tiene_prioridad_y_finanzas_es_respaldo(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg_mod, "cargar_env", lambda *a, **k: None)
    for n in ("PIN", "SECRETO", "DB", "EXPORTS", "VAULT", "FOTOS"):
        monkeypatch.delenv(f"BRAIN_{n}", raising=False)
        monkeypatch.delenv(f"FINANZAS_{n}", raising=False)
    monkeypatch.delenv("BRAIN_ESCRIBIR_COMIDAS", raising=False)
    monkeypatch.setenv("FINANZAS_PIN", "1111")
    monkeypatch.setenv("FINANZAS_SECRETO", "viejo")
    monkeypatch.setenv("FINANZAS_DB", str(tmp_path / "f.db"))
    c = cfg_mod.leer_config()
    assert (c.pin, c.secreto, c.db_path, c.escribir_comidas) == ("1111", "viejo", tmp_path / "f.db", False)

    monkeypatch.setenv("BRAIN_PIN", "2222")
    monkeypatch.setenv("BRAIN_VAULT", str(tmp_path / "vault"))
    monkeypatch.setenv("BRAIN_ESCRIBIR_COMIDAS", "1")
    c = cfg_mod.leer_config()
    assert (c.pin, c.secreto, c.vault_path, c.escribir_comidas) == ("2222", "viejo", tmp_path / "vault", True)


def test_login_emite_las_dos_cookies(anonimo, datos):
    anonimo.post("/login", data={"pin": PIN}, follow_redirects=False)
    assert anonimo.cookies.get(auth.COOKIE) and anonimo.cookies.get(auth.COOKIE_ANTERIOR)


def _firma(app):
    from itsdangerous import TimestampSigner
    return TimestampSigner(app.state.config.secreto, salt="sesion").sign("usuario").decode()


def test_cookie_anterior_sola_sigue_entrando(app, datos):
    with TestClient(app) as c:
        c.cookies.set(auth.COOKIE_ANTERIOR, _firma(app))
        assert c.get("/rendimiento", follow_redirects=False).status_code == 200


def test_cookie_nueva_sola_entra(app, datos):
    with TestClient(app) as c:
        c.cookies.set(auth.COOKIE, _firma(app))
        assert c.get("/", follow_redirects=False).status_code == 200


def test_salir_borra_las_dos_cookies(cliente):
    r = cliente.post("/salir", follow_redirects=False)
    borradas = " ".join(r.headers.get_list("set-cookie"))
    assert f"{auth.COOKIE}=" in borradas and f"{auth.COOKIE_ANTERIOR}=" in borradas


# Resumen para IA común

def test_escritura_atomica_con_permisos_600(tmp_path):
    ruta = tmp_path / "sub" / "x.md"
    escribir_atomico(ruta, "hola")
    assert ruta.read_text() == "hola"
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    assert [p.name for p in ruta.parent.iterdir()] == ["x.md"]


def test_sobre_y_par_sin_raya_larga(tmp_path):
    datos = {**sobre("rendimiento", date(2026, 10, 17), "1", "u"), "nota": "a — b"}
    assert datos["fuente"] == "[app rendimiento 2026-10-17 | alta]"
    js, md = escribir_par(tmp_path, "rendimiento-ia", datos, "# T — x\n")
    assert json.loads(js.read_text())["nota"] == "a , b"
    assert "—" not in md.read_text()


def test_catalogos_iniciales(con):
    ej = {r["nombre"]: r for r in con.execute("SELECT * FROM ejercicios")}
    assert ej["Press militar"]["carga_hombro"] == 1 and ej["Dominadas"]["carga_hombro"] == 1
    assert ej["Sentadilla trasera"]["carga_hombro"] == 0
    assert ej["Dominadas"]["tipo_carga"] == "peso_corporal_lastre"
    familias = {(r[0], r[1]) for r in con.execute("SELECT DISTINCT disciplina, familia FROM tecnicas")}
    assert {("judo", f) for f in ("te-waza", "koshi-waza", "ashi-waza", "sutemi-waza", "ne-waza")} <= familias
    assert {("bjj", f) for f in ("guardias", "pasajes", "raspados", "sumisiones", "espalda")} <= familias
    assert {("muaythai", f) for f in ("golpes", "codos", "rodillas", "patadas", "clinch", "defensas")} <= familias
    assert con.execute("SELECT familia FROM tecnicas WHERE nombre = 'Uchi mata'").fetchone()[0] == "ashi-waza"


def test_certificado_raiz_sin_pin(anonimo, tmp_path, monkeypatch):
    crt = tmp_path / "raiz.crt"
    crt.write_text("-----BEGIN CERTIFICATE-----\nprueba\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("BRAIN_CA_RAIZ", str(crt))
    r = anonimo.get("/caddy-raiz.crt")
    assert r.status_code == 200 and r.headers["content-type"] == "application/x-x509-ca-cert"
    assert "BEGIN CERTIFICATE" in r.text
    monkeypatch.setenv("BRAIN_CA_RAIZ", str(tmp_path / "no-existe.crt"))
    assert anonimo.get("/caddy-raiz.crt").status_code == 404
