"""Piezas comunes de los resúmenes para IA de cada módulo: sobre del JSON y escritura atómica."""

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path


def escribir_atomico(ruta: Path, texto: str) -> None:
    """Escribe con permisos 600 y reemplazo atómico, para que nunca quede un archivo a medias."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(texto)
        os.chmod(tmp, 0o600)
        os.replace(tmp, ruta)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def sobre(modulo: str, hoy: date, schema_version: str, unidades: str) -> dict:
    """Encabezado común: versión, fecha de generación y la fuente con la que el vault cita los datos."""
    return {
        "schema_version": schema_version,
        "generado": datetime.now().isoformat(timespec="seconds"),
        "hoy": hoy.isoformat(),
        "fuente": f"[app {modulo} {hoy.isoformat()} | alta]",
        "unidades": unidades,
    }


def escribir_par(carpeta: Path, nombre: str, datos: dict, markdown: str) -> tuple[Path, Path]:
    """Escribe `nombre.json` y `nombre.md`, sin el carácter de raya larga."""
    js, md = carpeta / f"{nombre}.json", carpeta / f"{nombre}.md"
    escribir_atomico(js, json.dumps(datos, ensure_ascii=False, indent=2).replace("—", ",") + "\n")
    escribir_atomico(md, markdown.replace("—", ","))
    return js, md
