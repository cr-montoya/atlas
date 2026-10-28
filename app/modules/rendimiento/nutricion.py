"""Nutrición: plan vigente del vault (intercambios por momento), registro rápido de comidas y su escritura
opcional en el inbox del vault.

El plan es prescripción [O] de la nutricionista; lo registrado es [H], con las palabras y los intercambios que
marcal usuario. La app no estima porciones ni califica el día: eso lo hace la revisión semanal del vault
(.agents/nutricion.md). La única escritura de la app en el vault es 00_Inbox/comidas/AAAA-Www/AAAA-MM-DD.md,
solo con BRAIN_ESCRIBIR_COMIDAS=1, y nunca sobre un archivo que el usuario escribió a mano.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from app.core.resumen import escribir_atomico

from . import logica, vault

NUTRICION = Path("04_Nutrition")
INBOX = Path("00_Inbox/comidas")
MARCA = "<!-- Escrito por Atlas (app de rendimiento). Se reescribe al guardar en la app; para editarlo a mano, borra esta línea. -->"

MOMENTOS = {"desayuno": "Desayuno", "media_manana": "Media mañana", "almuerzo": "Almuerzo",
            "media_tarde": "Media tarde", "cena": "Cena", "extra": "Extra"}
CORTOS = {"media_manana": "M. mañana", "media_tarde": "M. tarde"}   # para la tabla de la semana a 360 px
GRUPOS = ("carbohidrato", "proteína", "carne", "grasa", "verdura", "fruta")
VASO_ML = 200
MAX_INTERCAMBIOS = 12


class RegistroInvalido(ValueError):
    """El registro no se pudo guardar; el mensaje dice cómo arreglarlo."""


# Plan vigente ---------------------------------------------------------------

@dataclass(frozen=True)
class MomentoPlan:
    clave: str
    nombre: str
    intercambios: tuple[tuple[str, int], ...]   # (grupo, cantidad)
    nota: str = ""
    ejemplo: str = ""

    @property
    def texto(self) -> str:
        return ", ".join(f"{n} {g}" for g, n in self.intercambios)


@dataclass(frozen=True)
class Plan:
    archivo: str
    titulo: str
    profesional: str
    control: str
    momentos: tuple[MomentoPlan, ...]
    liquidos_ml: int | None = None
    pasos: int | None = None

    def momento(self, clave: str) -> MomentoPlan | None:
        return next((m for m in self.momentos if m.clave == clave), None)


def _clave_momento(nombre: str) -> str | None:
    n = nombre.strip().lower().replace("ñ", "n")
    for clave, etiqueta in MOMENTOS.items():
        if etiqueta.lower().replace("ñ", "n") == n:
            return clave
    return None


def _grupo(texto: str) -> str | None:
    t = texto.strip().lower()
    for g in GRUPOS:
        if t.startswith(g) or t.startswith(g.replace("í", "i")):
            return g
    return None


def _intercambios(distribucion: str) -> tuple[tuple[tuple[str, int], ...], str]:
    """'1 carbohidrato, 1 carne, 1 grasa; alternativa de 5 porciones de proteína' -> intercambios y nota."""
    principal, _, resto = distribucion.partition(";")
    notas = [resto.strip()] if resto.strip() else []
    for parentesis in re.findall(r"\(([^)]*)\)", principal):
        notas.append(parentesis.strip())
    principal = re.sub(r"\([^)]*\)", "", principal)
    salida: list[tuple[str, int]] = []
    for parte in principal.split(","):
        m = re.match(r"\s*(\d+)\s+([^+]+?)\s*(\+.*)?$", parte)
        if not m:
            continue
        g = _grupo(m.group(2))
        if g:
            salida.append((g, int(m.group(1))))
        if m.group(3):
            notas.append("más " + m.group(3).lstrip("+ ").strip())
    return tuple(salida), "; ".join(notas)


def leer_plan(ruta: Path) -> Plan:
    texto = ruta.read_text(encoding="utf-8")
    titulo = next((l[2:].strip() for l in texto.splitlines() if l.startswith("# ")), ruta.stem)
    ejemplos: dict[str, str] = {}
    for m in re.finditer(r"^- \*\*([^:*]+):\*\*\s*(.+)$", texto, re.M):
        clave = _clave_momento(m.group(1))
        if clave:
            ejemplos[clave] = re.sub(r"\s*·\s*\[[^\]]*\]\s*$", "", m.group(2)).strip()
    momentos = []
    seccion = re.search(r"## Minuta patrón.*?\n(.*?)(?:\n## |\Z)", texto, re.S)
    for linea in (seccion.group(1) if seccion else "").splitlines():
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) < 2:
            continue
        clave = _clave_momento(celdas[0])
        if not clave:
            continue
        inter, nota = _intercambios(celdas[1])
        momentos.append(MomentoPlan(clave, MOMENTOS[clave], inter, nota, ejemplos.get(clave, "")))
    prof = re.search(r"Profesional:\s*([^,·\n]+)", texto)
    control = re.search(r"Próximo control:\s*([^·\n]+)", texto)
    litros = re.search(r"([\d,]+)\s*L mínimo de líquidos", texto)
    pasos = re.search(r"([\d.]+)\s*pasos mínimo", texto)
    return Plan(
        archivo=str(ruta.name), titulo=titulo, profesional=prof.group(1).strip() if prof else "",
        control=control.group(1).strip() if control else "", momentos=tuple(momentos),
        liquidos_ml=round(float(litros.group(1).replace(",", ".")) * 1000) if litros else None,
        pasos=int(pasos.group(1).replace(".", "")) if pasos else None,
    )


def _activo(ruta: Path) -> bool:
    cabeza = ruta.read_text(encoding="utf-8")[:400]
    return bool(re.search(r"^status:\s*active\s*$", cabeza, re.M))


def plan_vigente(boveda: Path) -> Plan | None:
    """El plan-nutricional-AAAA-MM.md con status active más reciente (los viejos quedan historical)."""
    carpeta = boveda / NUTRICION
    candidatos = sorted(carpeta.glob("plan-nutricional-*.md"), reverse=True) if carpeta.is_dir() else []
    for ruta in candidatos:
        if _activo(ruta):
            plan = vault._cacheado(ruta, leer_plan)
            if plan.momentos:
                return plan
    return None


# Registro -------------------------------------------------------------------

@dataclass
class Comida:
    momento: str
    hora: str | None = None
    texto: str = ""
    intercambios: dict[str, int] = field(default_factory=dict)
    segun_plan: bool = False

    @property
    def nombre(self) -> str:
        return MOMENTOS[self.momento]

    @property
    def texto_intercambios(self) -> str:
        return ", ".join(f"{n} {g}" for g, n in self.intercambios.items() if n)


@dataclass
class Dia:
    fecha: str
    comidas: dict[str, Comida]
    agua_vasos: int | None = None
    suplementos: str = ""
    notas: str = ""
    vault_estado: str | None = None

    @property
    def agua_ml(self) -> int | None:
        return self.agua_vasos * VASO_ML if self.agua_vasos is not None else None


def dia(con: sqlite3.Connection, fecha: str) -> Dia:
    comidas = {}
    for r in con.execute("SELECT * FROM comidas_registro WHERE fecha = ?", (fecha,)):
        comidas[r["momento"]] = Comida(r["momento"], r["hora"], r["texto"] or "", json.loads(r["intercambios"] or "{}"),
                                       bool(r["segun_plan"]))
    d = con.execute("SELECT * FROM comidas_dia WHERE fecha = ?", (fecha,)).fetchone()
    return Dia(fecha, comidas, d["agua_vasos"] if d else None, (d["suplementos"] or "") if d else "",
               (d["notas"] or "") if d else "", d["vault_estado"] if d else None)


def _fecha(fecha: str) -> str:
    try:
        return date.fromisoformat(fecha).isoformat()
    except ValueError:
        raise RegistroInvalido("La fecha va como 2026-10-19.") from None


def _hora(hora: str | None) -> str | None:
    hora = (hora or "").strip()
    if not hora:
        return None
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", hora):
        raise RegistroInvalido("La hora va como 13:30.")
    return hora.zfill(5)


def guardar_comida(con: sqlite3.Connection, fecha: str, momento: str, hora: str | None, texto: str,
                   intercambios: dict[str, int], segun_plan: bool = False) -> None:
    with con:
        _upsert_comida(con, fecha, momento, hora, texto, intercambios, segun_plan)


def _upsert_comida(con: sqlite3.Connection, fecha: str, momento: str, hora: str | None, texto: str,
                   intercambios: dict[str, int], segun_plan: bool = False) -> None:
    """Sin commit: para escribir varias cosas en una sola transacción (registro por voz)."""
    fecha = _fecha(fecha)
    if momento not in MOMENTOS:
        raise RegistroInvalido("Elige el momento del día.")
    texto = " ".join((texto or "").split())[:500]
    limpios = {g: n for g, n in intercambios.items() if g in GRUPOS and n}
    if any(n < 0 or n > MAX_INTERCAMBIOS for n in limpios.values()):
        raise RegistroInvalido(f"Los intercambios van de 0 a {MAX_INTERCAMBIOS}.")
    if not texto and not limpios:
        raise RegistroInvalido("Escribe qué comiste o marca los intercambios.")
    con.execute("INSERT INTO comidas_registro (fecha, momento, hora, texto, intercambios, segun_plan) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (fecha, momento) DO UPDATE SET hora = excluded.hora, texto = excluded.texto,"
                " intercambios = excluded.intercambios, segun_plan = excluded.segun_plan, actualizado = datetime('now')",
                (fecha, momento, _hora(hora), texto or None, json.dumps(limpios, ensure_ascii=False), int(segun_plan)))


def borrar_comida(con: sqlite3.Connection, fecha: str, momento: str) -> None:
    with con:
        con.execute("DELETE FROM comidas_registro WHERE fecha = ? AND momento = ?", (_fecha(fecha), momento))


def guardar_dia(con: sqlite3.Connection, fecha: str, agua_vasos: int | None = None, suplementos: str | None = None,
                notas: str | None = None) -> None:
    fecha = _fecha(fecha)
    if agua_vasos is not None and not 0 <= agua_vasos <= 40:
        raise RegistroInvalido("Los vasos de agua van de 0 a 40.")
    actual = dia(con, fecha)
    valores = (agua_vasos if agua_vasos is not None else actual.agua_vasos,
               " ".join(suplementos.split())[:300] if suplementos is not None else actual.suplementos,
               " ".join(notas.split())[:500] if notas is not None else actual.notas)
    with con:
        con.execute("INSERT INTO comidas_dia (fecha, agua_vasos, suplementos, notas) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (fecha) DO UPDATE SET agua_vasos = excluded.agua_vasos, suplementos = excluded.suplementos,"
                    " notas = excluded.notas, actualizado = datetime('now')", (fecha, *valores))


def _upsert_agua(con: sqlite3.Connection, fecha: str, agua_vasos: int) -> None:
    """Sin commit: fija los vasos del día y deja suplementos y notas como estaban."""
    fecha = _fecha(fecha)
    if not 0 <= agua_vasos <= 40:
        raise RegistroInvalido("Los vasos de agua van de 0 a 40.")
    con.execute("INSERT INTO comidas_dia (fecha, agua_vasos) VALUES (?, ?)"
                " ON CONFLICT (fecha) DO UPDATE SET agua_vasos = excluded.agua_vasos, actualizado = datetime('now')",
                (fecha, agua_vasos))


def _marcar_vault(con: sqlite3.Connection, fecha: str, estado: str) -> None:
    with con:
        con.execute("INSERT INTO comidas_dia (fecha, vault_estado) VALUES (?, ?)"
                    " ON CONFLICT (fecha) DO UPDATE SET vault_estado = excluded.vault_estado", (fecha, estado))


# Escritura en el inbox del vault -------------------------------------------

def ruta_inbox(boveda: Path, fecha: str) -> Path:
    d = date.fromisoformat(fecha)
    return boveda / INBOX / logica.semana_iso(d) / f"{fecha}.md"


def _celda(texto: str) -> str:
    return " ".join(texto.split()).replace("|", "/")


def markdown_dia(d: Dia, plan: Plan | None) -> str:
    """El día con el formato de 00_Inbox/comidas/plantilla-dia.md, más la marca de Atlas."""
    filas = []
    for clave, nombre in MOMENTOS.items():
        c = d.comidas.get(clave)
        if c is None:
            filas.append(f"| | {nombre} | |")
            continue
        partes = []
        if c.texto:
            partes.append(c.texto)
        if c.segun_plan:
            partes.append("según el plan")
        if c.texto_intercambios:
            partes.append(f"intercambios: {c.texto_intercambios}")
        filas.append(f"| {c.hora or ''} | {nombre} | {_celda('; '.join(partes))} |")
    agua = f"{d.agua_vasos} vasos de agua de {VASO_ML} ml (~{logica.fmt_decimal(d.agua_vasos * VASO_ML, 1)} L)" if d.agua_vasos is not None else ""
    return "\n".join([
        f"# Comidas {d.fecha}", "", MARCA, "",
        "| Hora | Momento | Qué comí y cuánto |", "| --- | --- | --- |", *filas, "",
        f"- Bebidas (agua aprox., gaseosa, alcohol): {agua}".rstrip(),
        f"- Suplementos: {_celda(d.suplementos)}".rstrip(),
        f"- Notas (hambre, antojos, salidas): {_celda(d.notas)}".rstrip(),
        f"- Registrado en la app Atlas{(' frente a ' + plan.archivo) if plan else ''}.",
    ]) + "\n"


def escribir_vault(con: sqlite3.Connection, boveda: Path, fecha: str, plan: Plan | None) -> str:
    """Escribe el día en el inbox. Devuelve el estado: escrito, manual (archivo escrito a mano: no se toca)
    o error. Solo escribe dentro de 00_Inbox/comidas/."""
    ruta = ruta_inbox(boveda, fecha)
    base = (boveda / INBOX).resolve()
    if not ruta.resolve().is_relative_to(base):
        raise RuntimeError("Ruta fuera de 00_Inbox/comidas")
    if ruta.exists() and MARCA not in ruta.read_text(encoding="utf-8"):
        estado = "manual"
    else:
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            escribir_atomico(ruta, markdown_dia(dia(con, fecha), plan))
            estado = "escrito"
        except OSError:
            estado = "error"
    _marcar_vault(con, fecha, estado)
    return estado


# Semana --------------------------------------------------------------------

def semana(con: sqlite3.Connection, plan: Plan | None, lunes: date, hoy: date) -> dict:
    """Tabla de la semana: qué momentos tienen registro cada día y la suma de intercambios marcados frente a
    lo que pide el plan en esos mismos momentos. No es una calificación del día."""
    dias = [lunes + timedelta(days=i) for i in range(7)]
    filas = con.execute("SELECT * FROM comidas_registro WHERE fecha BETWEEN ? AND ?",
                        (dias[0].isoformat(), dias[-1].isoformat())).fetchall()
    agua = {r["fecha"]: r["agua_vasos"] for r in con.execute(
        "SELECT fecha, agua_vasos FROM comidas_dia WHERE fecha BETWEEN ? AND ?", (dias[0].isoformat(), dias[-1].isoformat()))}
    marcas: dict[tuple[str, str], str] = {}
    marcado: dict[str, int] = {g: 0 for g in GRUPOS}
    pedido: dict[str, int] = {g: 0 for g in GRUPOS}
    for r in filas:
        marcas[(r["fecha"], r["momento"])] = "plan" if r["segun_plan"] else "si"
        inter = json.loads(r["intercambios"] or "{}")
        mp = plan.momento(r["momento"]) if plan else None
        if mp and inter:
            for g, n in mp.intercambios:
                pedido[g] += n
            for g, n in inter.items():
                marcado[g] = marcado.get(g, 0) + n
    grupos = [{"grupo": g, "marcado": marcado[g], "plan": pedido[g]} for g in GRUPOS if marcado[g] or pedido[g]]
    pasados = [d for d in dias if d <= hoy]
    return {
        "dias": [{"fecha": d.isoformat(), "letra": "LMMJVSD"[d.weekday()], "futuro": d > hoy,
                  "agua_vasos": agua.get(d.isoformat())} for d in dias],
        "momentos": [(k, CORTOS.get(k, n)) for k, n in MOMENTOS.items() if k != "extra"],
        "marcas": {f"{f}|{m}": v for (f, m), v in marcas.items()},
        "registrados": sum(1 for (f, m) in marcas if m != "extra"),
        "posibles": len(pasados) * 5,
        "dias_con_registro": len({f for f, _ in marcas}),
        "grupos": grupos,
    }


def ultimos(con: sqlite3.Connection, desde: str) -> list[dict]:
    """Para el resumen de IA: lo registrado desde una fecha, tal como lo escribió."""
    salida = []
    for r in con.execute("SELECT * FROM comidas_registro WHERE fecha >= ? ORDER BY fecha, momento", (desde,)):
        salida.append({"fecha": r["fecha"], "momento": r["momento"], "hora": r["hora"], "texto": r["texto"],
                       "intercambios": json.loads(r["intercambios"] or "{}"), "segun_plan": bool(r["segun_plan"])})
    return salida
