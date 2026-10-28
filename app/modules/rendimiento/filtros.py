"""Filtros de plantilla de rendimiento (los registra app/core/plantillas.py)."""

import re
from datetime import date

from markupsafe import Markup, escape

from . import logica
from .vault import NOMBRES

MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_test(fecha: str, precision: str = "dia", aproximada: bool = False) -> str:
    """'2025-01-01', 'mes', True -> '~ene 2025'; '2026-08-18' -> '18 ago 2026'."""
    d = date.fromisoformat(fecha)
    texto = f"{MESES_CORTOS[d.month - 1]} {d.year}" if precision == "mes" else f"{d.day} {MESES_CORTOS[d.month - 1]} {d.year}"
    return ("~" if aproximada else "") + texto


def delta_txt(d: logica.Delta | None, unidad: str = "", escala: str = "mil") -> str:
    """Texto del delta con signo: '+4,59 cm', '-4.000 kg', '-1 sesión'."""
    if d is None:
        return "sin dato"
    if d.valor == 0:
        return "sin cambio"
    if escala == "g":
        cuerpo = logica.fmt_kg(abs(d.valor))
    elif escala == "conteo":
        if unidad == "sesiones" and abs(d.valor) == 1:
            unidad = "sesión"
        cuerpo = f"{logica.fmt_decimal(abs(d.valor) * 1000)}{(' ' + unidad) if unidad else ''}"
    elif escala == "s":
        cuerpo = logica.fmt_duracion(abs(d.valor))
    else:
        cuerpo = f"{logica.fmt_decimal(abs(d.valor))}{(' ' + unidad) if unidad else ''}"
    return f"{d.signo}{cuerpo}"


def valor_metrica(v: int | None, escala: str, unidad: str = "") -> str:
    """Valor de una métrica semanal según su escala; None es "sin dato", nunca 0."""
    if v is None:
        return "sin dato"
    if escala == "s":
        return logica.fmt_duracion(v) if v else "0 min"
    if escala == "g":
        return logica.fmt_kg(v)
    if escala == "mil":
        return f"{logica.fmt_decimal(v, 1)}{(' ' + unidad) if unidad else ''}"
    texto = logica.fmt_decimal(v * 1000)
    return f"{texto} {unidad}" if unidad and unidad != "sesiones" else texto


def _seccion_md(texto: str, nombre: str) -> str:
    """Las líneas bajo el primer título que contiene `nombre` (sin el título); si no está, la primera sección."""
    bloques: list[tuple[str, list[str]]] = []
    for linea in texto.splitlines():
        m = re.match(r"^\s*#{1,4}\s+(.*)$", linea)
        if m:
            bloques.append((m.group(1), []))
        elif bloques:
            bloques[-1][1].append(linea)
    for titulo, lineas in bloques:
        if nombre.lower() in titulo.lower():
            return "\n".join(lineas)
    return "\n".join(bloques[0][1]) if bloques else texto


def md_ia(texto: str | None, seccion: str | None = None, nivel: int = 2) -> Markup:
    """Markdown simple de los análisis de Claude a HTML seguro: títulos ##, viñetas, listas numeradas,
    párrafos y **negrita**. Todo se escapa antes; no se admite HTML ni enlaces del modelo.
    Con `seccion`, solo el contenido de esa sección (para el tablero)."""
    texto = _seccion_md(texto or "", seccion) if seccion else (texto or "")
    salida: list[str] = []
    lista: str | None = None

    def cerrar_lista():
        nonlocal lista
        if lista:
            salida.append(f"</{lista}>")
            lista = None

    def inline(s: str) -> str:
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s.strip())  # enlaces del modelo: solo su texto
        s = str(escape(s))
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

    for linea in texto.splitlines():
        s = linea.strip()
        if not s:
            cerrar_lista()
            continue
        m = re.match(r"^#{1,4}\s+(.*)$", s)
        if m:
            cerrar_lista()
            salida.append(f"<h{nivel}>{inline(m.group(1))}</h{nivel}>")
            continue
        m = re.match(r"^[-*•]\s+(.*)$", s) or re.match(r"^\d+[.)]\s+(.*)$", s)
        if m:
            tipo = "ul" if re.match(r"^[-*•]", s) else "ol"
            if lista != tipo:
                cerrar_lista()
                salida.append(f"<{tipo}>")
                lista = tipo
            salida.append(f"<li>{inline(m.group(1))}</li>")
            continue
        cerrar_lista()
        salida.append(f"<p>{inline(s)}</p>")
    cerrar_lista()
    return Markup("\n".join(salida))


FILTROS = {
    "fecha_obj": lambda texto: date.fromisoformat(texto),
    "md_ia": md_ia,
    "valor_metrica": valor_metrica,
    "kg": logica.fmt_kg,
    "carga": logica.fmt_carga,
    "duracion": logica.fmt_duracion,
    "rpe": logica.fmt_rpe,
    "decimal": logica.fmt_decimal,
    "pct_delta": logica.fmt_pct,
    "delta_txt": delta_txt,
    "fecha_test": fecha_test,
    "disciplina": lambda clave: NOMBRES.get(clave, clave),
}
