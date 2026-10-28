#!/usr/bin/env python3
"""Codex CLI falso para las pruebas de la imagen proyectada: nunca llama a OpenAI.

Lee lo que debe hacer de $CODEX_HOME/modo.json y anota cada llamada (argumentos, entorno y prompt) en
$CODEX_HOME/llamadas.jsonl. Imita lo verificado con codex-cli 0.162.1: eventos JSONL por stdout, el JSON del
paso 1 en el archivo de -o, y la imagen en $CODEX_HOME/generated_images/<thread_id>/.
"""

import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path

home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
modo = json.loads((home / "modo.json").read_text(encoding="utf-8")) if (home / "modo.json").is_file() else {}
args = sys.argv[1:]
prompt = sys.stdin.read()
with (home / "llamadas.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps({"args": args, "env": dict(os.environ), "prompt": prompt}) + "\n")

tid = str(uuid.uuid4())
print(json.dumps({"type": "thread.started", "thread_id": tid}), flush=True)
print(json.dumps({"type": "turn.started"}), flush=True)
(home / "shell_snapshots").mkdir(parents=True, exist_ok=True)
(home / "shell_snapshots" / f"{tid}.1.sh").write_text("export X=1\n")
time.sleep(modo.get("dormir", 0))
if modo.get("error"):
    print(json.dumps({"type": "error", "message": modo["error"]}), flush=True)
    sys.exit(1)

paso1 = "--output-schema" in args
verificacion = paso1 and "Eres revisor" in prompt
if verificacion:
    cuenta = home / "verificaciones.txt"
    n = int(cuenta.read_text()) if cuenta.is_file() else 0
    cuenta.write_text(str(n + 1))
    lista = modo.get("verificaciones") or [{"zonas_excedidas": [], "luz_cambio": False, "nota": "dentro del análisis"}]
    v = lista[min(n, len(lista) - 1)]
    Path(args[args.index("-o") + 1]).write_text(v if isinstance(v, str) else json.dumps(v), encoding="utf-8")
elif paso1:
    salida = Path(args[args.index("-o") + 1])
    salida.write_text(modo.get("texto") or json.dumps(modo["analisis"]), encoding="utf-8")
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "listo"}}), flush=True)
else:
    if not modo.get("sin_imagen"):
        carpeta = home / "generated_images" / tid
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "exec-1.png").write_bytes(base64.b64decode(modo["imagen_b64"]))
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "./resultado.png"}}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
