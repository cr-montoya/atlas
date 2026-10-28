"""Codex CLI para la imagen proyectada (openspec/changes/v1-imagen-proyectada): comando acotado, entorno mínimo,
grupo de procesos con tope y cancelación, lectura del hilo y limpieza.

Verificado con codex-cli 0.162.1 el 2026-10-19: la imagen de `image_gen` queda en
`$CODEX_HOME/generated_images/<thread_id>/` aunque Codex diga que la copió a otra parte, así que lo que Codex
afirme sobre archivos no se usa. Codex puede leer archivos del disco; las herramientas de comandos, navegador,
apps y plugins van desactivadas, y el proceso no recibe las variables de la app (PIN, secreto).
"""

import json
import os
import select
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

MODELO_PREFERIDO = "gpt-6.1-sol"
DESACTIVADAS = ("shell_tool", "unified_exec", "shell_snapshot", "browser_use", "browser_use_external", "computer_use",
                "in_app_browser", "apps", "plugins", "multi_agent", "goals", "hooks", "daemon_auto_start")
EXTENSIONES = (".png", ".webp", ".jpg", ".jpeg")


class Cancelado(RuntimeError):
    pass


class FalloCodex(RuntimeError):
    """Codex terminó mal; el mensaje es legible para la pantalla."""


@dataclass
class Corrida:
    thread_id: str | None = None
    eventos: dict[str, int] = field(default_factory=dict)
    errores: list[str] = field(default_factory=list)
    mensajes: list[str] = field(default_factory=list)
    codigo: int | None = None
    segundos: float = 0.0


def modelo(codex_home: Path) -> str | None:
    """gpt-6.1-sol si está; si no, el de `priority` más bajo, visible, con imagen y nivel max; None si no se sabe."""
    try:
        datos = json.loads((codex_home / "models_cache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lista = datos.get("models", datos) if isinstance(datos, dict) else datos
    validos = []
    for m in lista if isinstance(lista, list) else []:
        if not isinstance(m, dict) or m.get("visibility") != "list" or "image" not in (m.get("input_modalities") or []):
            continue
        if "max" not in {n.get("effort") for n in m.get("supported_reasoning_levels") or [] if isinstance(n, dict)}:
            continue
        validos.append(m)
    if any(m.get("slug") == MODELO_PREFERIDO for m in validos):
        return MODELO_PREFERIDO
    validos.sort(key=lambda m: m.get("priority", 10 ** 6))
    return validos[0].get("slug") if validos else None


def comando(codex_cmd: str, carpeta: Path, slug: str | None, fotos: list[Path], esquema: Path | None = None,
            salida: Path | None = None) -> list[str]:
    cmd = [codex_cmd, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "-s", "read-only"]
    if slug:
        cmd += ["-m", slug]
    cmd += ["-c", 'model_reasoning_effort="max"']
    for f in DESACTIVADAS:
        cmd += ["--disable", f]
    if esquema is not None:
        cmd += ["--disable", "image_generation", "--output-schema", str(esquema), "-o", str(salida)]
    cmd += ["--json", "-C", str(carpeta)]
    if fotos:
        cmd += ["-i", *map(str, fotos)]   # -i acepta varios valores: va al final y el prompt entra por stdin
    return cmd


def entorno(path: str, codex_home: Path) -> dict[str, str]:
    """Entorno mínimo: nada de BRAIN_*, tokens ni variables de la app."""
    env = {"PATH": path, "HOME": str(Path.home()), "LANG": "C.UTF-8", "TZ": "America/Bogota"}
    if codex_home != Path.home() / ".codex":
        env["CODEX_HOME"] = str(codex_home)
    return env


def correr(cmd: list[str], prompt: str, env: dict[str, str], limite_s: float, cancelado=lambda: False,
           al_hilo=lambda tid: None) -> Corrida:
    """Corre Codex en su propio grupo de procesos. Lee el JSONL en vivo: guarda el thread_id apenas llega (para
    limpiar aunque se interrumpa), los tipos de evento y los errores; nunca el stdout crudo."""
    c = Corrida()
    inicio = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                start_new_session=True, text=True)
    except FileNotFoundError:
        raise FalloCodex("No encontré Codex CLI (el comando codex). Instálalo o define BRAIN_CODEX con su ruta.") from None
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
        stderr: list[str] = []
        abiertos = [proc.stdout, proc.stderr]
        while abiertos:
            if cancelado():
                raise Cancelado("Cancelado")
            if time.monotonic() - inicio > limite_s:
                raise FalloCodex(f"Pasó el tiempo máximo de {max(1, int(limite_s) // 60)} min y detuve el trabajo.")
            listos, _, _ = select.select(abiertos, [], [], 1.0)
            for flujo in listos:
                linea = flujo.readline()
                if not linea:
                    abiertos.remove(flujo)
                    continue
                if flujo is proc.stderr:
                    stderr.append(linea.strip())
                    continue
                _evento(c, linea, al_hilo)
        c.codigo = proc.wait(timeout=30)
        if c.codigo != 0 and not c.errores:
            ultimo = next((l for l in reversed(stderr) if l and not l.startswith("Reading")), "")
            c.errores.append(ultimo[:300] or f"Codex terminó con código {c.codigo}.")
    finally:
        if proc.poll() is None:
            _matar(proc)
        c.segundos = round(time.monotonic() - inicio, 1)
    return c


def _evento(c: Corrida, linea: str, al_hilo) -> None:
    try:
        e = json.loads(linea)
    except ValueError:
        return
    tipo = str(e.get("type", ""))
    item = e.get("item") if isinstance(e.get("item"), dict) else {}
    clave = tipo + (f":{item.get('type')}" if item.get("type") else "")
    c.eventos[clave] = c.eventos.get(clave, 0) + 1
    if tipo == "thread.started" and e.get("thread_id"):
        c.thread_id = str(e["thread_id"])
        al_hilo(c.thread_id)
    if tipo in ("error", "turn.failed"):
        err = e.get("error")
        msg = err.get("message") if isinstance(err, dict) else (err or e.get("message"))
        c.errores.append(str(msg or tipo)[:300])
    if item.get("type") == "agent_message" and item.get("text"):
        c.mensajes.append(str(item["text"])[:300])


def _matar(proc: subprocess.Popen) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            continue


def imagen_del_hilo(codex_home: Path, thread_id: str | None) -> Path | None:
    """La imagen más reciente que dejó image_gen en la carpeta del hilo."""
    if not thread_id:
        return None
    carpeta = codex_home / "generated_images" / thread_id
    if not carpeta.is_dir():
        return None
    imagenes = [p for p in carpeta.iterdir() if p.suffix.lower() in EXTENSIONES and p.is_file()]
    return max(imagenes, key=lambda p: p.stat().st_mtime_ns) if imagenes else None


def limpiar_hilo(codex_home: Path, thread_id: str) -> None:
    if not thread_id or "/" in thread_id or thread_id in (".", ".."):
        return
    shutil.rmtree(codex_home / "generated_images" / thread_id, ignore_errors=True)
    carpeta = codex_home / "shell_snapshots"
    if carpeta.is_dir():
        for p in carpeta.glob(f"{thread_id}*"):
            p.unlink(missing_ok=True)


def mensaje_error(c: Corrida) -> str:
    texto = " ".join(c.errores)
    if any(p in texto.lower() for p in ("moderation", "safety", "policy", "rate limit", "usage limit", "quota")):
        return f"Codex rechazó la solicitud: {texto}"
    return texto or "Codex terminó con error."
