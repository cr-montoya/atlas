"""Requirement: Sincronizar sensores (botón con claude -p, escritura acotada a 03_Training/imports/)."""

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Config
from app.core.db import conectar, migrar
from app.modules.rendimiento import rutas, trabajos, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"

FALSO = r'''#!{python}
import json, os, sys, time
from pathlib import Path
modo = os.environ.get("FALSO_MODO", "ok")
Path(os.environ["FALSO_ARGS"]).write_text(json.dumps(sys.argv[1:]))
if modo == "lento":
    time.sleep(5)
if modo in ("ok", "fuera", "sin_polar"):
    destino = Path("03_Training/imports/garmin/2026-02-06_2026-02-07_salud-diaria-garmin-mcp.csv")
    destino.write_text("day,steps,resting_hr,stress_avg,body_battery_high,sleep_h,deep_min,light_min,rem_min,awake_min,"
                       "sleep_score,hrv_ms,hrv_status,intensity_min,vigorous_min\n2026-02-06,9100,53,25,90,7.5,70,300,90,20,80,72,BALANCED,30,5\n")
if modo == "fuera":
    Path("03_Training/objetivos-deportivos.md").write_text("editado")
avisos = ["POLAR_SIN_AUTORIZACION"] if modo == "sin_polar" else []
res = {{"archivos": ["x"], "dias_garmin": 1, "sesiones_polar": 0, "avisos": avisos}}
print(json.dumps({{"type": "result", "is_error": False, "result": "Listo.\n" + json.dumps(res)}}))
'''


def _git(boveda, *args):
    subprocess.run(["git", "-C", str(boveda), "-c", "user.name=prueba", "-c", "user.email=p@p", *args],
                   check=True, capture_output=True)


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    _git(destino, "init", "-q")
    _git(destino, "add", "-A")
    _git(destino, "commit", "-q", "-m", "base")
    vault.limpiar_cache()
    return destino


@pytest.fixture
def falso(tmp_path, monkeypatch):
    ruta = tmp_path / "claude-falso"
    ruta.write_text(FALSO.format(python=sys.executable))
    ruta.chmod(0o755)
    monkeypatch.setenv("FALSO_ARGS", str(tmp_path / "args.json"))
    return ruta


@pytest.fixture
def config(tmp_path, boveda, falso):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db", exports_path=tmp_path / "exports",
                  vault_path=boveda, fotos_path=tmp_path / "fotos", claude_cmd=str(falso), tiempo_max_s=2)


@pytest.fixture(autouse=True)
def sincrono(monkeypatch):
    """Ejecuta el trabajo en el mismo hilo para poder verificarlo."""
    real = trabajos.lanzar
    monkeypatch.setattr(trabajos, "lanzar", lambda cfg, tid, en_hilo=True: real(cfg, tid, en_hilo=False))
    monkeypatch.setattr(rutas, "hoy", lambda: date(2026, 2, 8))


def _args(tmp_path) -> list[str]:
    return json.loads((tmp_path / "args.json").read_text())


def _sincronizar(cliente) -> dict:
    r = cliente.post("/rendimiento/sincronizar", headers={"HX-Request": "true"})
    assert r.status_code == 200
    return r


def test_escritura_acotada_en_el_comando(cliente, tmp_path):
    _sincronizar(cliente)
    args = _args(tmp_path)
    assert "--strict-mcp-config" in args and "--mcp-config" in args
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    permitidas = args[args.index("--allowedTools") + 1: args.index("--permission-mode")]
    assert "Write(03_Training/imports/**)" in permitidas and "Edit(03_Training/imports/**)" in permitidas
    assert not any(p.startswith("Bash") for p in permitidas)
    assert not any(h in " ".join(permitidas) for h in ("polar_profile_update", "polar_revoke_access", "polar_exchange_code"))
    assert args[args.index("--tools") + 1] == "Read,Glob,Grep,Write,Edit"
    prompt = args[args.index("-p") + 1]
    assert "Escribe SOLO archivos nuevos dentro de 03_Training/imports/" in prompt
    assert "[I]" in prompt and "sin el carácter de raya larga" in prompt


def test_trae_lo_que_falta_desde_la_ultima_fecha(cliente, tmp_path):
    _sincronizar(cliente)
    prompt = _args(tmp_path)[_args(tmp_path).index("-p") + 1]
    assert "desde el día siguiente a 2026-02-05 hasta 2026-02-07" in prompt  # hasta ayer: el día en curso no se escribe


def test_sincronizacion_lista_y_datos_nuevos(cliente, con, boveda):
    r = _sincronizar(cliente)
    t = trabajos.ultimo(con, "sincronizar")
    assert t["estado"] == "listo", t["error"]
    res = json.loads(t["resultado"])
    assert res["archivos_nuevos"] == ["03_Training/imports/garmin/2026-02-06_2026-02-07_salud-diaria-garmin-mcp.csv"]
    assert "2026-02-06" in vault.importar(boveda).salud
    assert "Última sincronización: hoy." in r.text and "Llegaron 1 día de Garmin" in r.text


def test_cambio_fuera_de_imports_falla(cliente, con, monkeypatch):
    monkeypatch.setenv("FALSO_MODO", "fuera")
    r = _sincronizar(cliente)
    t = trabajos.ultimo(con, "sincronizar")
    assert t["estado"] == "fallido"
    assert "03_Training/objetivos-deportivos.md" in t["error"]
    assert "La sincronización falló" in r.text


def test_polar_sin_autorizacion(cliente, con, monkeypatch):
    monkeypatch.setenv("FALSO_MODO", "sin_polar")
    r = _sincronizar(cliente)
    assert trabajos.ultimo(con, "sincronizar")["estado"] == "listo"
    assert "Polar necesita autorización: abre una sesión de Claude Code en el vault y autoriza" in r.text
    assert "Garmin se sincronizó igual" in r.text


def test_tiempo_maximo(cliente, con, monkeypatch):
    monkeypatch.setenv("FALSO_MODO", "lento")
    _sincronizar(cliente)
    t = trabajos.ultimo(con, "sincronizar")
    assert t["estado"] == "fallido" and "Pasó el tiempo máximo" in t["error"]
    assert cliente.get("/rendimiento/registrar").status_code == 200  # el resto de la app sigue


def test_sin_claude_instalado(tmp_path, boveda):
    cfg = Config(pin=PIN, secreto="s", db_path=tmp_path / "otra.db", vault_path=boveda, claude_cmd=str(tmp_path / "no-existe"))
    con = conectar(cfg.db_path)
    migrar(con)
    tid, _ = trabajos.encolar(con, "sincronizar", {"ultima": {}, "hoy": "2026-02-08"})
    trabajos.lanzar(cfg, tid, en_hilo=False)
    t = trabajos.trabajo(con, tid)
    assert t["estado"] == "fallido" and "No encontré Claude Code" in t["error"]


def test_vault_sin_git_no_se_arriesga(tmp_path):
    sin_git = tmp_path / "sin-git"
    shutil.copytree(DATOS, sin_git)
    cfg = Config(pin=PIN, secreto="s", db_path=tmp_path / "otra.db", vault_path=sin_git, claude_cmd="claude")
    con = conectar(cfg.db_path)
    migrar(con)
    tid, _ = trabajos.encolar(con, "sincronizar", {})
    trabajos.lanzar(cfg, tid, en_hilo=False)
    assert "no es un repositorio git" in trabajos.trabajo(con, tid)["error"]


def test_estado_en_vivo_y_un_trabajo_a_la_vez(cliente, con):
    tid, nuevo = trabajos.encolar(con, "sincronizar", {})
    assert nuevo
    assert trabajos.encolar(con, "sincronizar", {}) == (tid, False)
    with con:
        con.execute("UPDATE trabajos_ia SET estado = 'corriendo' WHERE id = ?", (tid,))
    r = cliente.get(f"/rendimiento/trabajos/{tid}", headers={"HX-Request": "true"})
    assert "Sincronizando…" in r.text and 'hx-trigger="every 2s"' in r.text and "HX-Refresh" not in r.headers
    with con:
        con.execute("UPDATE trabajos_ia SET estado = 'listo', fin = '2026-02-08T10:00:00', resultado = '{}' WHERE id = ?", (tid,))
    r = cliente.get(f"/rendimiento/trabajos/{tid}", headers={"HX-Request": "true"})
    assert "every 2s" not in r.text and r.headers.get("HX-Refresh") == "true"
    assert "Última sincronización: hoy." in r.text


def test_trabajo_interrumpido_al_reiniciar(app, config):
    con = conectar(config.db_path)
    tid, _ = trabajos.encolar(con, "sincronizar", {})
    from app.main import crear_app
    crear_app(config)
    t = trabajos.trabajo(con, tid)
    assert t["estado"] == "fallido" and "se reinició" in t["error"]
    con.close()


def test_boton_en_actividades(cliente):
    r = cliente.get("/rendimiento/actividades")
    assert 'hx-post="/rendimiento/sincronizar"' in r.text and "Nunca se ha sincronizado" in r.text


def test_zonas_de_un_csv_sincronizado(boveda):
    csv = next((boveda / vault.POLAR).glob("*.csv"))
    texto = csv.read_text().splitlines()
    texto[0] += ",z1_s,z2_s,z3_s,z4_s,z5_s"
    texto = [texto[0]] + [l + ",,,,," for l in texto[1:]] + ["2026-07-01,18:00:00,Judo,3600,,140,180,800,,,600,1200,1200,500,100"]
    csv.write_text("\n".join(texto) + "\n")
    a = next(x for x in vault.importar(boveda).actividades if x.fecha == "2026-07-01")
    assert a.zonas_s == (600, 1200, 1200, 500, 100)
    assert next(x for x in vault.importar(boveda).actividades if x.fecha == "2026-01-06").zonas_s is None


def test_vault_dentro_de_un_repo_mas_grande(tmp_path, falso, monkeypatch):
    """Como ~/Documents/vault dentro del repo ~/Documents: las rutas de git llevan el prefijo vault/."""
    raiz = tmp_path / "Documents"
    boveda = raiz / "vault"
    shutil.copytree(DATOS, boveda)
    _git(raiz, "init", "-q")
    _git(raiz, "add", "-A")
    _git(raiz, "commit", "-q", "-m", "base")
    vault.limpiar_cache()
    cfg = Config(pin=PIN, secreto="s", db_path=tmp_path / "otra.db", vault_path=boveda, claude_cmd=str(falso), tiempo_max_s=10)
    con = conectar(cfg.db_path)
    migrar(con)
    tid, _ = trabajos.encolar(con, "sincronizar", {"ultima": {}, "hoy": "2026-02-08"})
    trabajos.lanzar(cfg, tid, en_hilo=False)
    t = trabajos.trabajo(con, tid)
    assert t["estado"] == "listo", t["error"]
    assert json.loads(t["resultado"])["archivos_nuevos"] == [
        "03_Training/imports/garmin/2026-02-06_2026-02-07_salud-diaria-garmin-mcp.csv"]
    monkeypatch.setenv("FALSO_MODO", "fuera")
    tid, _ = trabajos.encolar(con, "sincronizar", {"ultima": {}, "hoy": "2026-02-08"})
    trabajos.lanzar(cfg, tid, en_hilo=False)
    t = trabajos.trabajo(con, tid)
    assert t["estado"] == "fallido" and "03_Training/objetivos-deportivos.md" in t["error"]
    assert "vault/" not in t["error"]


def test_mcp_con_ruta_absoluta_y_path_para_systemd(tmp_path, monkeypatch):
    casa = tmp_path / "casa"
    bin_nvm = casa / ".nvm" / "versions" / "node" / "v24.1.0" / "bin"
    bin_nvm.mkdir(parents=True)
    polar = bin_nvm / "polar-mcp-unofficial"
    polar.write_text("#!/usr/bin/env node\n")
    polar.chmod(0o755)
    (casa / ".claude.json").write_text(json.dumps({"mcpServers": {
        "polar": {"type": "stdio", "command": "polar-mcp-unofficial", "args": []},
        "garmin": {"type": "stdio", "command": "/opt/garmin-mcp", "args": ["serve"]}, "otro": {"command": "x"}}}))
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # como bajo systemd
    cfg = trabajos.mcp_desde_usuario()
    assert set(cfg["mcpServers"]) == {"polar", "garmin"}
    assert cfg["mcpServers"]["polar"]["command"] == str(polar)
    assert cfg["mcpServers"]["garmin"]["command"] == "/opt/garmin-mcp"
    assert trabajos.path_extendido().split(":")[:2] == [str(casa / ".local" / "bin"), str(bin_nvm)]


def test_sincroniza_sola_al_arrancar_una_vez_al_dia(config, tmp_path):
    from dataclasses import replace
    from app.main import crear_app
    cfg = replace(config, sincronizar_al_arrancar=True)
    crear_app(cfg)
    con = conectar(cfg.db_path)
    t = trabajos.ultimo(con, "sincronizar")
    assert t["estado"] == "listo" and json.loads(t["parametros"])["origen"] == "arranque"
    crear_app(cfg)  # segundo arranque el mismo día: no repite
    assert con.execute("SELECT COUNT(*) FROM trabajos_ia").fetchone()[0] == 1
    con.close()


def test_no_sincroniza_al_arrancar_si_esta_apagado(app, config):
    con = conectar(config.db_path)
    assert con.execute("SELECT COUNT(*) FROM trabajos_ia").fetchone()[0] == 0
    con.close()


def test_inbox_de_comidas_de_la_app_no_hace_fallar_la_sincronizacion(tmp_path, boveda, falso, monkeypatch):
    from dataclasses import replace
    monkeypatch.setenv("FALSO_MODO", "ok")
    cfg = Config(pin=PIN, secreto="s", db_path=tmp_path / "otra.db", vault_path=boveda, claude_cmd=str(falso),
                 tiempo_max_s=10, escribir_comidas=True)
    con = conectar(cfg.db_path)
    migrar(con)
    real = trabajos._correr_claude

    def con_comida(*a, **k):  # la app escribe el día mientras Claude corre
        (boveda / "00_Inbox/comidas/2026-W06").mkdir(parents=True, exist_ok=True)
        (boveda / "00_Inbox/comidas/2026-W06/2026-02-08.md").write_text("# Comidas 2026-02-08\n")
        return real(*a, **k)
    monkeypatch.setattr(trabajos, "_correr_claude", con_comida)
    tid, _ = trabajos.encolar(con, "sincronizar", {"ultima": {}, "hoy": "2026-02-08"})
    trabajos.lanzar(cfg, tid, en_hilo=False)
    assert trabajos.trabajo(con, tid)["estado"] == "listo", trabajos.trabajo(con, tid)["error"]
    tid, _ = trabajos.encolar(con, "sincronizar", {"ultima": {}, "hoy": "2026-02-08"})
    (boveda / "00_Inbox/comidas/2026-W06/2026-02-08.md").unlink()
    trabajos.lanzar(replace(cfg, escribir_comidas=False), tid, en_hilo=False)
    assert trabajos.trabajo(con, tid)["estado"] == "fallido"  # apagado, un cambio ahí sí es sospechoso
    con.close()
