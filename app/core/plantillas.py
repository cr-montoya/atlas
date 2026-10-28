"""Entorno Jinja2 compartido: busca plantillas en core y en cada módulo."""

import importlib
from datetime import date
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import ChoiceLoader, FileSystemLoader

from app.core import dinero
from app.core.modulos import MODULOS, modulo_de

BASE = Path(__file__).resolve().parents[1]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def fecha_larga(valor) -> str:
    d = date.fromisoformat(valor) if isinstance(valor, str) else valor
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def fecha_corta(valor) -> str:
    d = date.fromisoformat(valor) if isinstance(valor, str) else valor
    return f"{d.day} {MESES[d.month - 1][:3]} {d.year}"


def crear_templates() -> Jinja2Templates:
    tpl = Jinja2Templates(directory=str(BASE / "core" / "templates"))
    tpl.env.loader = ChoiceLoader([
        FileSystemLoader(str(BASE / "core" / "templates")),
        *[FileSystemLoader(str(p)) for p in sorted((BASE / "modules").glob("*/templates"))],
    ])
    tpl.env.filters.update(
        cop=dinero.fmt_cop, usd=dinero.fmt_usd, trm=dinero.fmt_trm, moneda=dinero.fmt_moneda,
        fecha_larga=fecha_larga, fecha_corta=fecha_corta, pct=dinero.fmt_tasa,
    )
    # Filtros propios de cada módulo: app/modules/<m>/filtros.py con un diccionario FILTROS.
    for carpeta in sorted((BASE / "modules").glob("*/filtros.py")):
        propios = importlib.import_module(f"app.modules.{carpeta.parent.name}.filtros").FILTROS
        repetidos = set(propios) & set(tpl.env.filters)
        if repetidos:
            raise RuntimeError(f"Filtros de plantilla repetidos en {carpeta.parent.name}: {sorted(repetidos)}")
        tpl.env.filters.update(propios)
    tpl.env.globals.update(modulos=MODULOS, modulo_de=modulo_de)
    return tpl
