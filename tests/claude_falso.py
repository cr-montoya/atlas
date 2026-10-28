#!/usr/bin/env python3
"""Claude Code falso para el registro por voz: nunca llama a Anthropic.

Imita `claude -p --output-format json --json-schema ...`: lee el prompt de la entrada estándar y responde con un
sobre JSON con `structured_output`. Lo que debe responder sale de $HOME/modo_claude.json (una respuesta por llamada,
la última se repite) y cada llamada queda anotada (argumentos, entorno, carpeta y prompt) en
$HOME/llamadas_claude.jsonl.
"""

import json
import os
import sys
import time
from pathlib import Path

home = Path(os.environ.get("HOME", "."))
modo_ruta = home / "modo_claude.json"
modo = json.loads(modo_ruta.read_text(encoding="utf-8")) if modo_ruta.is_file() else {}
prompt = sys.stdin.read()
llamadas = home / "llamadas_claude.jsonl"
n = sum(1 for _ in llamadas.open(encoding="utf-8")) if llamadas.is_file() else 0
with llamadas.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"args": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd(), "prompt": prompt}) + "\n")

time.sleep(modo.get("dormir", 0))
if modo.get("codigo"):
    print("falla simulada", file=sys.stderr)
    sys.exit(modo["codigo"])
respuestas = modo.get("respuestas") or [{"items": [], "pregunta": None}]
salida = respuestas[min(n, len(respuestas) - 1)]
sobre = {"type": "result", "subtype": "success", "is_error": bool(modo.get("is_error")),
         "result": json.dumps(salida, ensure_ascii=False)}
if not modo.get("sin_structured"):
    sobre["structured_output"] = salida
print(json.dumps(sobre, ensure_ascii=False))
