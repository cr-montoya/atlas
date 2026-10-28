"""Trabajos de fondo con Claude Code (`claude -p`) o, para la imagen proyectada, Codex CLI; uno a la vez, con
tiempo máximo y registro.

Sincronizar sensores: Claude corre con el vault como carpeta de trabajo, solo con los MCP de Garmin y
Polar (de Polar, solo herramientas de lectura) y escritura limitada a 03_Training/imports/. Al terminar se
revisa `git status` del vault: si cambió algo fuera de imports, el trabajo queda fallido.

Análisis (semana, combate y fotos, ver analisis.py): sin MCP y solo con Read, Grep y Glob. El prompt va por
la entrada estándar, porque los datos de la app pueden pasar el límite de un argumento.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from app.core.config import Config
from app.core.db import conectar
from app.core.demo import exigir_externo

from . import vault

IMPORTS = "03_Training/imports/"

REGLAS_CONTENIDO = (
    "Reglas: responde en español y sin el carácter de raya larga. Toda recomendación va marcada [I]. "
    "No hagas diagnósticos ni reemplaces al entrenador, al fisio, a la nutricionista ni al ortopedista; "
    "durante la rehabilitación posquirúrgica del hombro solo resume lo que ellos indicaron."
)

# Herramientas de solo lectura del MCP de Polar (el servidor también tiene herramientas que escriben en la cuenta).
POLAR_LECTURA = (
    "polar_connection_status", "polar_data_inventory", "polar_list_training_sessions", "polar_heart_series",
    "polar_list_sleeps", "polar_list_nightly_recharge", "polar_daily_summary", "polar_weekly_summary",
    "polar_list_activity", "polar_list_sports",
)

# Tipos de análisis de solo lectura y su nombre en la interfaz.
ANALISIS = {"analisis_semana": "Analiza mi semana", "analisis_combate": "Analiza mi combate",
            "comparar_fotos": "Compara mis fotos"}
LECTURA = ("Read", "Grep", "Glob")
IMAGEN = "imagen"   # imagen proyectada con Codex (imagen_proyectada.py)


RELLENAR = "rellenar_salud"   # relleno único de 60 días de salud de Garmin (Body Battery y fases de sueño)
DIAS_RELLENO = 60
TRAMO_RELLENO = 20
TIEMPO_RELLENO_S = 1800

# Columnas del CSV de salud diaria de Garmin, en orden; las cinco últimas se agregaron en v1-dia-y-sensaciones.
COLUMNAS_SALUD = ("day", "steps", "resting_hr", "stress_avg", "body_battery_high", "sleep_h", "deep_min", "light_min",
                  "rem_min", "awake_min", "sleep_score", "hrv_ms", "hrv_status", "intensity_min", "vigorous_min",
                  "body_battery_low", "body_battery_charged", "body_battery_drained", "hrv_baseline_low",
                  "hrv_baseline_high")
MAPEO_SALUD = """- day: la fecha del día (AAAA-MM-DD)
- steps: steps
- resting_hr: resting_hr
- stress_avg: stress_avg
- body_battery_high, body_battery_low, body_battery_charged, body_battery_drained: los body_battery_* del mismo nombre
- sleep_h, deep_min, light_min, rem_min, awake_min: los del objeto sleep (sleep_h en horas con punto decimal)
- sleep_score: sleep.score
- hrv_ms: hrv_last_night
- hrv_status: hrv_status
- hrv_baseline_low, hrv_baseline_high: los del mismo nombre
- intensity_min: intensity_minutes
- vigorous_min: vigorous_minutes
Un campo que falta o viene en null se deja vacío, nunca en 0. Garmin pone el sueño en el día en que despertó."""


def bloque_salud() -> str:
    return ("Garmin salud: CSV con estas columnas, en este orden (si el README del vault dice otra cosa, mandan "
            "estas):\n  " + ",".join(COLUMNAS_SALUD) + "\n  Mapeo desde get_daily_health:\n"
            + "\n".join("  " + l for l in MAPEO_SALUD.splitlines()))


def nombre(tipo: str) -> str:
    if tipo == RELLENAR:
        return "El relleno de salud"
    return ANALISIS.get(tipo) or ("Imagen proyectada" if tipo == IMAGEN else "La sincronización")

_candado = threading.Lock()


class SinClaude(RuntimeError):
    pass


def path_extendido() -> str:
    """PATH para los trabajos. Bajo systemd el PATH es mínimo: se agregan ~/.local/bin y las carpetas de
    Node de nvm (la versión más nueva primero), porque Claude Code y el MCP de Polar viven ahí."""
    extra = [str(Path.home() / ".local" / "bin")]
    nvm = sorted((Path.home() / ".nvm" / "versions" / "node").glob("*/bin"), reverse=True)
    extra += [str(p) for p in nvm]
    actual = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return os.pathsep.join(dict.fromkeys([*extra, *actual.split(os.pathsep)]))


def comando_claude(cfg: Config) -> str:
    if "/" in cfg.claude_cmd:
        return cfg.claude_cmd
    return shutil.which(cfg.claude_cmd, path=path_extendido()) or str(Path.home() / ".local" / "bin" / cfg.claude_cmd)


def herramientas_sincronizar() -> list[str]:
    return ["Read", "Glob", "Grep", f"Write({IMPORTS}**)", f"Edit({IMPORTS}**)", "mcp__garmin",
            *[f"mcp__polar__{h}" for h in POLAR_LECTURA]]


def mcp_desde_usuario(nombres: tuple[str, ...] = ("garmin", "polar")) -> dict:
    """Toma la definición de los MCP del usuario (~/.claude.json) para pasarla con --strict-mcp-config."""
    ruta = Path.home() / ".claude.json"
    try:
        servidores = json.loads(ruta.read_text(encoding="utf-8")).get("mcpServers", {})
    except (OSError, ValueError):
        servidores = {}
    salida = {}
    for n in nombres:
        if n not in servidores:
            continue
        srv = dict(servidores[n])
        cmd = srv.get("command")
        if cmd and "/" not in cmd:
            srv["command"] = shutil.which(cmd, path=path_extendido()) or cmd  # ruta absoluta para systemd
        salida[n] = srv
    return {"mcpServers": salida}


def prompt_sincronizar(ultima: dict[str, str | None], hoy: str) -> str:
    """Pide hasta ayer: el día en curso queda para la próxima sincronización, porque los archivos de
    imports no se editan después de guardados y un día a medias no se podría completar."""
    desde_g = ultima.get("garmin") or "2026-09-01"
    desde_p = ultima.get("polar") or "2026-02-01"
    try:
        hoy = (date.fromisoformat(hoy) - timedelta(days=1)).isoformat()
    except ValueError:
        pass
    return f"""Sincroniza los datos nuevos de los sensores con el vault siguiendo .agents/ingesta.md y los README de
{IMPORTS}garmin/ y {IMPORTS}polar/.

- Garmin (MCP garmin): actividades y salud diaria desde el día siguiente a {desde_g} hasta {hoy} (ayer, el último
  día completo; no incluyas el día en curso).
- Polar (MCP polar, solo herramientas de lectura): sesiones de entrenamiento desde el día siguiente a {desde_p} hasta {hoy},
  con los minutos en cada zona de FC si el servidor los da. Si Polar pide autorización o no está conectado,
  no lo intentes más, sigue con Garmin y avisa con el texto POLAR_SIN_AUTORIZACION.

Escribe SOLO archivos nuevos dentro de {IMPORTS} (nunca sobrescribas ni edites un archivo existente, nunca toques
otra carpeta del vault ni las notas canónicas). Usa los mismos formatos de los archivos que ya existen:
- Polar: CSV con las columnas date,start,sport_polar,duration_s,distance_m,hr_avg,hr_max,kcal,running_index,note
  y, al final, z1_s,z2_s,z3_s,z4_s,z5_s (segundos por zona, vacío si no hay dato).
- {bloque_salud()}
- Garmin actividades: Markdown con la misma tabla del archivo existente (decimales con coma) y, al final de cada fila,
  las columnas Z1 a Z5 en minutos si el servidor las da.
Nombre: AAAA-MM-DD_AAAA-MM-DD_<tipo>-<fuente>-mcp.<ext> con el rango de fechas que contiene.
Si no hay días nuevos en una fuente, no escribas archivo para ella.

{REGLAS_CONTENIDO}

Al final responde SOLO con un objeto JSON, sin texto alrededor:
{{"archivos": ["ruta relativa", ...], "dias_garmin": n, "sesiones_polar": n, "avisos": ["...", ...]}}"""


def comando_sincronizar(cfg: Config, prompt: str, mcp_config: Path) -> list[str]:
    return [
        comando_claude(cfg), "-p", prompt, "--output-format", "json",
        "--strict-mcp-config", "--mcp-config", str(mcp_config),
        "--tools", "Read,Glob,Grep,Write,Edit",
        "--allowedTools", *herramientas_sincronizar(),
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--no-session-persistence",
    ]


def tramos_relleno(hoy: date) -> list[tuple[date, date]]:
    """De ayer - 59 a ayer, en tramos de hasta 20 días, del más viejo al más nuevo. Nunca incluye hoy."""
    fin = hoy - timedelta(days=1)
    inicio = fin - timedelta(days=DIAS_RELLENO - 1)
    salida = []
    a = inicio
    while a <= fin:
        b = min(a + timedelta(days=TRAMO_RELLENO - 1), fin)
        salida.append((a, b))
        a = b + timedelta(days=1)
    return salida


def archivo_relleno(a: date, b: date) -> str:
    return f"{IMPORTS}garmin/{a.isoformat()}_{b.isoformat()}_salud-diaria-{vault.RELLENO}-garmin-mcp.csv"


def prompt_rellenar(tramos: list[tuple[date, date]]) -> str:
    lista = "\n".join(f"- del {a} al {b}: {archivo_relleno(a, b)}" for a, b in tramos)
    return f"""Relleno único de la salud diaria de Garmin (MCP garmin, get_daily_health), para traer Body Battery, fases de
sueño y la línea base de HRV de días que ya están en el vault. Escribe un archivo NUEVO por tramo, con estos nombres:
{lista}

Cada archivo lleva una fila por día del tramo con datos. {bloque_salud()}

Reglas: escribe SOLO esos archivos nuevos; no cambies ningún otro archivo, no edites ni sobrescribas archivos
existentes y no toques otra carpeta del vault. Si un archivo de la lista ya existe, sáltalo.

{REGLAS_CONTENIDO}

Al final responde SOLO con un objeto JSON, sin texto alrededor:
{{"archivos": ["ruta relativa", ...], "dias_garmin": n, "avisos": ["...", ...]}}"""


def comando_rellenar(cfg: Config, prompt: str, mcp_config: Path) -> list[str]:
    """Sin la herramienta Edit: solo Write dentro de imports/garmin/ y el MCP de Garmin. La regla de permiso
    tiene que ser Edit(...): Claude Code no reconoce Write(...) y deniega la escritura en modo dontAsk."""
    return [
        comando_claude(cfg), "-p", prompt, "--output-format", "json",
        "--strict-mcp-config", "--mcp-config", str(mcp_config),
        "--tools", "Read,Glob,Grep,Write",
        "--allowedTools", "Read", "Glob", "Grep", f"Edit({IMPORTS}garmin/**)", "mcp__garmin",
        "--permission-mode", "dontAsk", "--permission-prompts", "none",
        "--no-session-persistence",
    ]


def comando_analisis(cfg: Config, carpetas: list[Path] = ()) -> list[str]:
    """Solo lectura: sin MCP (--strict-mcp-config sin --mcp-config), sin Bash ni escritura. Las carpetas
    extra (por ejemplo, la copia temporal de dos fotos) se agregan con --add-dir para poder leerlas."""
    cmd = [
        comando_claude(cfg), "-p", "--output-format", "json", "--strict-mcp-config",
        "--tools", ",".join(LECTURA), "--allowedTools", *LECTURA,
        "--permission-mode", "dontAsk", "--permission-prompts", "none", "--no-session-persistence",
    ]
    for c in carpetas:
        cmd += ["--add-dir", str(c)]
    return cmd


# Cola ----------------------------------------------------------------------

def activo(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM trabajos_ia WHERE estado IN ('en_cola', 'corriendo') ORDER BY id LIMIT 1").fetchone()


def trabajo(con: sqlite3.Connection, trabajo_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM trabajos_ia WHERE id = ?", (trabajo_id,)).fetchone()


def ultimo(con: sqlite3.Connection, tipo: str, estado: str | None = None) -> sqlite3.Row | None:
    sql = "SELECT * FROM trabajos_ia WHERE tipo = ?" + (" AND estado = ?" if estado else "") + " ORDER BY id DESC LIMIT 1"
    return con.execute(sql, (tipo, estado) if estado else (tipo,)).fetchone()


def encolar(con: sqlite3.Connection, tipo: str, parametros: dict) -> tuple[int, bool]:
    """Devuelve (id, nuevo). Si ya hay un trabajo activo, devuelve ese: un trabajo a la vez."""
    with _candado:
        ya = activo(con)
        if ya:
            return ya["id"], False
        with con:
            tid = con.execute("INSERT INTO trabajos_ia (tipo, parametros) VALUES (?, ?)",
                              (tipo, json.dumps(parametros, ensure_ascii=False))).lastrowid
        return tid, True


def recuperar_interrumpidos(con: sqlite3.Connection) -> None:
    """Al arrancar la app, un trabajo que quedó corriendo se marca fallido."""
    with con:
        con.execute("UPDATE trabajos_ia SET estado = 'fallido', fin = ?, error = 'Se interrumpió porque la app se reinició.'"
                    " WHERE estado IN ('en_cola', 'corriendo')", (_ahora(),))


def sincronizar_al_arrancar(cfg: Config, hoy: date | None = None) -> int | None:
    """Al levantar la app, sincroniza sola una vez al día: trae hasta ayer, así que más veces no aporta.
    Devuelve el id del trabajo lanzado, o None si ya hubo una sincronización exitosa hoy o hay una corriendo."""
    exigir_externo(cfg, "sincronizar")
    hoy = hoy or date.today()
    con = conectar(cfg.db_path)
    try:
        ok = ultimo(con, "sincronizar", "listo")
        if ok and (ok["fin"] or "")[:10] == hoy.isoformat():
            return None
        if activo(con):
            return None
        tid, nuevo = encolar(con, "sincronizar", {"ultima": vault.importar(cfg.vault_path).ultima_fecha,
                                                  "hoy": hoy.isoformat(), "origen": "arranque"})
    finally:
        con.close()
    if nuevo:
        lanzar(cfg, tid)
    return tid


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _marcar(db_path: Path, trabajo_id: int, **campos) -> None:
    con = conectar(db_path)
    try:
        sets = ", ".join(f"{k} = ?" for k in campos)
        with con:
            con.execute(f"UPDATE trabajos_ia SET {sets} WHERE id = ?", (*campos.values(), trabajo_id))
    finally:
        con.close()


def lanzar(cfg: Config, trabajo_id: int, en_hilo: bool = True) -> None:
    exigir_externo(cfg, "trabajo de fondo")
    if en_hilo:
        threading.Thread(target=_ejecutar, args=(cfg, trabajo_id), daemon=True).start()
    else:
        _ejecutar(cfg, trabajo_id)


# Ejecución -----------------------------------------------------------------

def _git_cambios(boveda: Path) -> set[str] | None:
    """Rutas con cambios dentro del vault según git, relativas al vault; None si no está en un repo git.

    El vault puede estar dentro de un repo más grande (por ejemplo ~/Documents): git da las rutas desde la
    raíz del repo, así que se mira solo el vault (pathspec ".") y se le quita el prefijo del vault.
    """
    try:
        pref = subprocess.run(["git", "-C", str(boveda), "rev-parse", "--show-prefix"],
                              capture_output=True, text=True, timeout=30)
        if pref.returncode != 0:
            return None
        r = subprocess.run(["git", "-C", str(boveda), "status", "--porcelain", "--untracked-files=all", "-z", "--", "."],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    prefijo = pref.stdout.strip()
    rutas = set()
    for item in r.stdout.split("\0"):
        if len(item) > 3:
            ruta = item[3:]
            rutas.add(ruta[len(prefijo):] if prefijo and ruta.startswith(prefijo) else ruta)
    return rutas


def _marcas(boveda: Path, rutas: set[str]) -> dict[str, int | None]:
    """Fecha de modificación de archivos que ya tenían cambios, para notar si el trabajo los volvió a tocar."""
    salida = {}
    for r in rutas:
        try:
            salida[r] = (boveda / r).stat().st_mtime_ns
        except OSError:
            salida[r] = None
    return salida


def huellas_imports(boveda: Path) -> dict[str, tuple[int, int]]:
    """mtime y tamaño de cada archivo de imports/, para notar si un trabajo tocó uno que ya existía."""
    base = boveda / IMPORTS
    salida = {}
    if base.is_dir():
        for p in base.rglob("*"):
            if p.is_file():
                st = p.stat()
                salida[str(p.relative_to(boveda))] = (st.st_mtime_ns, st.st_size)
    return salida


def revisar_imports(boveda: Path, antes: dict[str, tuple[int, int]]) -> None:
    despues = huellas_imports(boveda)
    cambiados = sorted(r for r, h in antes.items() if despues.get(r) != h)
    if cambiados:
        raise RuntimeError("Se modificó un archivo existente de imports: " + ", ".join(cambiados))


def _correr_claude(cfg: Config, cmd: list[str], registro: list[str], entrada: str | None = None,
                   tiempo_s: int | None = None) -> subprocess.CompletedProcess:
    """Corre Claude Code en el vault con el tiempo máximo; los errores salen como texto legible."""
    tiempo = tiempo_s or cfg.tiempo_max_s
    try:
        r = subprocess.run(cmd, cwd=cfg.vault_path, input=entrada, capture_output=True, text=True,
                           timeout=tiempo, env={**os.environ, "PATH": path_extendido()})
    except FileNotFoundError:
        raise SinClaude("No encontré Claude Code (el comando claude). Instálalo o define BRAIN_CLAUDE con su ruta.") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Pasó el tiempo máximo de {max(1, tiempo // 60)} min y detuve el trabajo.") from None
    registro.append(r.stdout[-20000:])
    if r.stderr:
        registro.append("stderr: " + r.stderr[-5000:])
    return r


def _ejecutar(cfg: Config, trabajo_id: int) -> None:
    con = conectar(cfg.db_path)
    try:
        t = trabajo(con, trabajo_id)
    finally:
        con.close()
    if t is None:
        return
    _marcar(cfg.db_path, trabajo_id, estado="corriendo", inicio=_ahora())
    registro: list[str] = []
    try:
        params = json.loads(t["parametros"] or "{}")
        if t["tipo"] == IMAGEN:
            from . import imagen_proyectada
            resultado = imagen_proyectada.ejecutar(cfg, trabajo_id, params, registro)
        elif t["tipo"] in ANALISIS:
            resultado = _analizar(cfg, t["tipo"], params, registro)
        elif t["tipo"] == RELLENAR:
            resultado = _rellenar(cfg, params, registro)
        else:
            resultado = _sincronizar(cfg, params, registro)
        _marcar(cfg.db_path, trabajo_id, estado="listo", fin=_ahora(), resultado=json.dumps(resultado, ensure_ascii=False),
                registro="\n".join(registro))
    except Exception as err:  # noqa: BLE001 - el error queda legible en el trabajo; el resto de la app sigue
        _marcar(cfg.db_path, trabajo_id, estado="fallido", fin=_ahora(), error=str(err), registro="\n".join(registro))


def _en_vault(cfg: Config, registro: list[str], armar, tiempo_s: int | None = None,
              servidores: tuple[str, ...] = ("garmin", "polar")) -> tuple[dict, set[str]]:
    """Corre un trabajo que escribe en imports/: revisa con git que no cambie nada fuera de imports y, con mtime y
    tamaño, que no toque un archivo de imports que ya existía. `armar(mcp_config)` da el comando."""
    boveda = cfg.vault_path
    antes = _git_cambios(boveda)
    marcas_antes = _marcas(boveda, antes or set())
    if antes is None:
        raise RuntimeError(f"El vault en {boveda} no es un repositorio git: no puedo verificar que solo se escriba en imports.")
    huellas = huellas_imports(boveda)
    mcp_tmp = None
    try:
        fd, nombre = tempfile.mkstemp(prefix="mcp-", suffix=".json", dir=cfg.db_path.parent)
        mcp_tmp = Path(nombre)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(mcp_desde_usuario(servidores), fh)
        os.chmod(mcp_tmp, 0o600)
        cmd = armar(mcp_tmp)
        registro.append("$ " + " ".join(c if c != cmd[2] else "<prompt>" for c in cmd))
        r = _correr_claude(cfg, cmd, registro, tiempo_s=tiempo_s)
        despues = _git_cambios(boveda) or set()
        tocados = {p for p, m in _marcas(boveda, antes).items() if marcas_antes.get(p) != m}
        # Con BRAIN_ESCRIBIR_COMIDAS la app misma puede escribir el inbox de comidas mientras Claude sincroniza;
        # Claude no tiene permiso de escritura ahí, así que esos cambios son de la app y no cuentan.
        propios = ("00_Inbox/comidas/",) if cfg.escribir_comidas else ()
        fuera = sorted(p for p in (despues - antes) | tocados if not p.startswith((IMPORTS, *propios)))
        if fuera:
            raise RuntimeError("El trabajo cambió archivos fuera de 03_Training/imports/: " + ", ".join(fuera)
                               + ". Revísalos en el vault con git.")
        revisar_imports(boveda, huellas)
        if r.returncode != 0:
            raise RuntimeError(f"Claude terminó con error (código {r.returncode}). " + (r.stderr.strip()[-300:] or ""))
        resultado = _resultado(r.stdout)
        resultado["archivos_nuevos"] = sorted(p for p in despues - antes if p.startswith(IMPORTS))
        vault.limpiar_cache()
        return resultado, set(huellas)
    finally:
        if mcp_tmp:
            mcp_tmp.unlink(missing_ok=True)


def _sincronizar(cfg: Config, params: dict, registro: list[str]) -> dict:
    prompt = prompt_sincronizar(params.get("ultima", {}), params.get("hoy", ""))
    resultado, _ = _en_vault(cfg, registro, lambda mcp: comando_sincronizar(cfg, prompt, mcp))
    return resultado


def _rellenar(cfg: Config, params: dict, registro: list[str]) -> dict:
    """Relleno único: los tramos que ya tienen su archivo se saltan; no toca la sincronización normal."""
    try:
        hoy = date.fromisoformat(params.get("hoy", ""))
    except ValueError:
        hoy = date.today()
    tramos = [(a, b) for a, b in tramos_relleno(hoy) if not (cfg.vault_path / archivo_relleno(a, b)).exists()]
    if not tramos:
        return {"archivos": [], "dias_garmin": 0, "avisos": ["Los tres tramos del relleno ya existían"],
                "archivos_nuevos": []}
    prompt = prompt_rellenar(tramos)
    resultado, _ = _en_vault(cfg, registro, lambda mcp: comando_rellenar(cfg, prompt, mcp), TIEMPO_RELLENO_S,
                             ("garmin",))
    if not resultado["archivos_nuevos"]:
        # Sin archivos el relleno no sirvió: falla para que el botón siga y muestre por qué.
        avisos = "; ".join(resultado.get("avisos") or [])[:300]
        raise RuntimeError("Claude no escribió ningún archivo del relleno." + (f" Dijo: {avisos}" if avisos else ""))
    resultado["tramos"] = [f"{a}_{b}" for a, b in tramos]
    return resultado


def _analizar(cfg: Config, tipo: str, params: dict, registro: list[str]) -> dict:
    """Análisis de solo lectura. No se revisa git: las herramientas no permiten escribir, y la sesión del
    vault puede estar editando notas al mismo tiempo, lo que daría fallas falsas."""
    from . import analisis
    con = conectar(cfg.db_path)
    try:
        prep = analisis.preparar(con, cfg, tipo, params)
    finally:
        con.close()
    try:
        cmd = comando_analisis(cfg, prep.carpetas)
        registro.append("$ " + " ".join(cmd) + " < prompt")
        registro.append("Prompt:\n" + prep.prompt)
        r = _correr_claude(cfg, cmd, registro, entrada=prep.prompt)
        if r.returncode != 0 and not r.stdout.strip():
            raise RuntimeError(f"Claude terminó con error (código {r.returncode}). " + (r.stderr.strip()[-300:] or ""))
        return {**analisis.resultado(r.stdout), **prep.extra}
    finally:
        prep.limpiar()


def _resultado(stdout: str) -> dict:
    """Saca el JSON final de la respuesta de `claude -p --output-format json` (campo result)."""
    try:
        sobre = json.loads(stdout)
    except ValueError:
        return {"texto": stdout.strip()[:2000]}
    texto = sobre.get("result", "") if isinstance(sobre, dict) else ""
    if isinstance(sobre, dict) and sobre.get("is_error"):
        raise RuntimeError("Claude respondió con error: " + str(texto)[:500])
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio >= 0 and fin > inicio:
        try:
            datos = json.loads(texto[inicio:fin + 1])
            if isinstance(datos, dict):
                return datos
        except ValueError:
            pass
    return {"texto": texto[:2000]}


def polar_sin_autorizacion(resultado: dict) -> bool:
    avisos = " ".join(str(a) for a in resultado.get("avisos", [])) + str(resultado.get("texto", ""))
    return "POLAR_SIN_AUTORIZACION" in avisos
