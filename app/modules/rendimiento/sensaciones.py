"""Cómo me sentí: un registro por día (escalas de 1 a 5, síntomas, dolor y día sin entrenar), por voz o a mano.

Describe y no diagnostica: el aviso de Hoy y el historial ponen lo reportado junto al reloj, sin conclusiones.
Las funciones con guion bajo no confirman la transacción, para que la voz guarde todo junto.
"""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import vault

DIAS_ATRAS = 7
FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
DIAS_HISTORIAL = 14

# (clave, nombre, nombre corto, de 1 a 5)
ESCALAS = (
    ("energia", "Energía", "energía", "de 1, muy baja, a 5, muy alta"),
    ("animo", "Ánimo", "ánimo", "de 1, muy bajo, a 5, muy alto"),
    ("estres", "Estrés", "estrés", "de 1, nada, a 5, mucho"),
    ("sueno", "Sueño percibido", "sueño", "de 1, muy mal, a 5, muy bien"),
    ("motivacion", "Motivación", "motivación", "de 1, muy baja, a 5, muy alta"),
    ("hambre", "Hambre", "hambre", "de 1, nada, a 5, mucha"),
)
CLAVES_ESCALA = tuple(e[0] for e in ESCALAS)
NOMBRE_ESCALA = {e[0]: e[1] for e in ESCALAS}
CORTO_ESCALA = {e[0]: e[2] for e in ESCALAS}

SINTOMAS = {
    "diarrea": "Diarrea", "nauseas_vomito": "Náuseas o vómito", "fiebre": "Fiebre", "gripa": "Gripa o congestión",
    "tos": "Tos", "garganta": "Dolor de garganta", "cabeza": "Dolor de cabeza", "mareo": "Mareo",
    "malestar_general": "Malestar general",
}
# Normalizados (voz.normalizar). "indispuesto" y "muy malo" no van a propósito: esas frases pasan por "entendí".
SINONIMOS_SINTOMA = {
    "diarrea": ("diarrea", "suelto del estomago", "soltura"),
    "nauseas_vomito": ("nauseas", "vomito", "vomite", "ganas de vomitar", "mareado del estomago"),
    "fiebre": ("fiebre", "febril", "calentura"),
    "gripa": ("gripa", "gripe", "congestion", "congestionado", "moqueando", "resfriado"),
    "tos": ("tos", "tosiendo"),
    "garganta": ("garganta",),
    "cabeza": ("dolor de cabeza", "cefalea", "migrana", "me duele la cabeza"),
    "mareo": ("mareo", "mareado"),
    "malestar_general": ("malestar", "maluco", "enfermo"),
}
SIN_ENTRENO = {"descanso": "Descansé", "enfermedad": "No: enfermedad", "lesion": "No: lesión", "otro": "No: otro motivo"}
SIN_ENTRENO_TXT = {"descanso": "descansaste", "enfermedad": "no entrenaste (enfermedad)", "lesion": "no entrenaste (lesión)",
                   "otro": "no entrenaste (otro motivo)"}
MAX = {"sintomas_otros": 200, "dolor": 300, "relato": 2000, "notas": 500}
TEXTOS = ("sintomas_otros", "dolor", "relato", "notas")
CAMPOS = (*CLAVES_ESCALA, "sintomas", *TEXTOS[:2], "sin_entreno", *TEXTOS[2:])
NOMBRE_TEXTO = {"sintomas_otros": "Otros síntomas", "dolor": "El dolor", "relato": "El relato", "notas": "Las notas"}

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


class SensacionInvalida(ValueError):
    pass


# Fechas ---------------------------------------------------------------------

def rango(hoy: date) -> tuple[date, date]:
    return hoy - timedelta(days=DIAS_ATRAS), hoy


def en_rango(fecha: str | date, hoy: date) -> bool:
    d = date.fromisoformat(fecha) if isinstance(fecha, str) else fecha
    desde, hasta = rango(hoy)
    return desde <= d <= hasta


def fecha_editable(texto: str | None, hoy: date) -> str:
    """La fecha del formulario dentro del rango editable; si no, el mensaje de 422."""
    try:
        if not FECHA.fullmatch(str(texto or "")):
            raise ValueError
        d = date.fromisoformat(str(texto))
    except ValueError:
        raise SensacionInvalida("Fecha no válida") from None
    if not en_rango(d, hoy):
        raise SensacionInvalida("Solo se pueden registrar los últimos 7 días")
    return d.isoformat()


def nombre_dia(d: date, hoy: date) -> str:
    """"hoy", "ayer" o "lunes 19"."""
    if d == hoy:
        return "hoy"
    if d == hoy - timedelta(days=1):
        return "ayer"
    return f"{DIAS[d.weekday()]} {d.day}"


# Lectura y escritura --------------------------------------------------------

def _dict(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    try:
        d["sintomas"] = [s for s in json.loads(d["sintomas"] or "[]") if s in SINTOMAS]
    except ValueError:
        d["sintomas"] = []
    return d


def leer(con: sqlite3.Connection, fecha: str) -> dict | None:
    return _dict(con.execute("SELECT * FROM sensaciones_dia WHERE fecha = ?", (fecha,)).fetchone())


def leer_varias(con: sqlite3.Connection, fechas: list[str]) -> dict[str, dict]:
    if not fechas:
        return {}
    filas = con.execute(f"SELECT * FROM sensaciones_dia WHERE fecha IN ({','.join('?' * len(fechas))})", fechas)
    return {r["fecha"]: _dict(r) for r in filas}


def leer_entre(con: sqlite3.Connection, desde: str, hasta: str) -> dict[str, dict]:
    return {r["fecha"]: _dict(r) for r in
            con.execute("SELECT * FROM sensaciones_dia WHERE fecha BETWEEN ? AND ?", (desde, hasta))}


def tiene_dato(d: dict | None) -> bool:
    if not d:
        return False
    return any(d.get(k) is not None for k in CLAVES_ESCALA) or bool(d.get("sintomas")) or \
        any((d.get(k) or "").strip() for k in TEXTOS) or bool(d.get("sin_entreno"))


def validar(campos: dict) -> None:
    for k in CLAVES_ESCALA:
        v = campos.get(k)
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5):
            raise SensacionInvalida("Las escalas van de 1 a 5")
    if any(s not in SINTOMAS for s in campos.get("sintomas") or []):
        raise SensacionInvalida("Ese síntoma no está en la lista")
    if campos.get("sin_entreno") not in (None, *SIN_ENTRENO):
        raise SensacionInvalida("Elige si entrenaste")
    for k in TEXTOS:
        if len(campos.get(k) or "") > MAX[k]:
            raise SensacionInvalida(f"{NOMBRE_TEXTO[k]} admite hasta {MAX[k]} caracteres")


def _upsert_sensaciones(con: sqlite3.Connection, fecha: str, **cambios) -> dict | None:
    """Sin commit. Combina con la fila existente: solo cambian los campos dados. Si la fila queda sin ningún
    dato, se borra. Devuelve la fila resultante (o None si se borró)."""
    actual = leer(con, fecha) or {k: None for k in CAMPOS} | {"sintomas": []}
    nueva = {k: actual.get(k) for k in CAMPOS}
    for k, v in cambios.items():
        if k not in CAMPOS:
            raise KeyError(k)
        if k in TEXTOS:
            texto = "" if v is None else str(v)
            v = "\n".join(l.strip() for l in texto.splitlines() if l.strip()) if k == "relato" else " ".join(texto.split())
            v = v or None
        if k == "sintomas":
            v = list(dict.fromkeys(v or []))
        nueva[k] = v
    validar(nueva)
    if not tiene_dato(nueva):
        con.execute("DELETE FROM sensaciones_dia WHERE fecha = ?", (fecha,))
        return None
    con.execute(
        f"INSERT INTO sensaciones_dia (fecha, {', '.join(CAMPOS)}, actualizada) VALUES (?, {', '.join('?' * len(CAMPOS))},"
        " datetime('now', 'localtime')) ON CONFLICT (fecha) DO UPDATE SET "
        + ", ".join(f"{k} = excluded.{k}" for k in CAMPOS) + ", actualizada = excluded.actualizada",
        (fecha, *[json.dumps(nueva[k]) if k == "sintomas" else nueva[k] for k in CAMPOS]))
    return {"fecha": fecha, **nueva}


def guardar(con: sqlite3.Connection, fecha: str, **cambios) -> dict | None:
    with con:
        return _upsert_sensaciones(con, fecha, **cambios)


# Zona baja y textos -----------------------------------------------------------

def zona_baja(d: dict | None) -> list[tuple[str, int]]:
    """Energía, ánimo, sueño o motivación en 2 o menos, o estrés en 4 o más. El hambre nunca cuenta."""
    if not d:
        return []
    salida = []
    for k in ("energia", "animo", "estres", "sueno", "motivacion"):
        v = d.get(k)
        if v is None:
            continue
        if (k == "estres" and v >= 4) or (k != "estres" and v <= 2):
            salida.append((k, v))
    return salida


def es_bajo(k: str, v: int | None) -> bool:
    return v is not None and k != "hambre" and ((k == "estres" and v >= 4) or (k != "estres" and v <= 2))


def avisa(d: dict | None) -> bool:
    return bool(d) and bool(d.get("sintomas") or (d.get("dolor") or "").strip()
                            or d.get("sin_entreno") in ("enfermedad", "lesion") or zona_baja(d))


def texto_aviso(d: dict) -> str:
    """"diarrea, malestar general, dolor: cuello, no entrenaste (enfermedad), energía 2/5"."""
    partes = [SINTOMAS[s].lower() for s in d.get("sintomas") or []]
    if (d.get("dolor") or "").strip():
        partes.append(f"dolor: {d['dolor']}")
    if d.get("sin_entreno") in ("enfermedad", "lesion"):
        partes.append(SIN_ENTRENO_TXT[d["sin_entreno"]])
    partes += [f"{CORTO_ESCALA[k]} {v}/5" for k, v in zona_baja(d)]
    return ", ".join(partes)


# El reloj al lado -------------------------------------------------------------

@dataclass
class Promedios:
    hrv: int | None = None
    fc: int | None = None


def promedios(imp: vault.Importacion, hoy: date) -> Promedios:
    """Como tablero.py: los últimos 7 días con datos dentro de los últimos 60."""
    ult7 = [imp.salud[d] for d in (str(hoy - timedelta(days=i)) for i in range(60)) if d in imp.salud][:7]

    def prom(campo):
        v = [getattr(d, campo) for d in ult7 if getattr(d, campo)]
        return round(sum(v) / len(v)) if v else None
    return Promedios(prom("hrv_ms"), prom("fc_reposo"))


def fmt_sueno(s: int | None) -> str:
    if not s:
        return ""
    m = round(s / 60)
    return f"{m // 60} h {m % 60} min" if m % 60 else f"{m // 60} h"


def lineas_reloj(s: vault.DiaSalud, p: Promedios) -> list[str]:
    """"Sueño 6 h 2 min · puntaje 73", "HRV 94 ms (tu rango: 76 a 110)", "Body Battery: cargó 76, mínimo 5"..."""
    lineas = []
    if s.sueno_s:
        lineas.append(f"Sueño {fmt_sueno(s.sueno_s)}" + (f" · puntaje {s.sueno_puntaje}" if s.sueno_puntaje else ""))
    if s.hrv_ms:
        if s.hrv_base_baja and s.hrv_base_alta:
            hrv = f"HRV {s.hrv_ms} ms (tu rango: {s.hrv_base_baja} a {s.hrv_base_alta})"
        else:
            hrv = f"HRV {s.hrv_ms} ms" + (f" (tu promedio: {p.hrv})" if p.hrv else "")
        if s.hrv_estado:
            hrv += f", {vault.HRV_ESTADOS[s.hrv_estado]}"
        lineas.append(hrv)
    bb = []
    if s.bb_cargado is not None:
        bb.append(f"cargó {s.bb_cargado}")
    if s.bb_min is not None:
        bb.append(f"mínimo {s.bb_min}")
    if bb:
        lineas.append("Body Battery: " + ", ".join(bb))
    if s.fc_reposo:
        lineas.append(f"FC en reposo {s.fc_reposo}" + (f" (tu promedio: {p.fc})" if p.fc else ""))
    return lineas


SIN_SINCRONIZAR = "Reloj de anoche: aún sin sincronizar (Garmin trae hasta ayer)"


@dataclass
class LineaAviso:
    fecha: str
    cuando: str          # Hoy | Ayer
    texto: str
    reloj: list[str] = field(default_factory=list)


def aviso_hoy(con: sqlite3.Connection, imp: vault.Importacion, hoy: date) -> dict:
    """Una sola consulta a sensaciones_dia. Devuelve las líneas del aviso (empezando por hoy), el día del enlace
    "Ver o editar" y si hay fila hoy (para el acceso "¿Cómo te sientes hoy?")."""
    ayer = hoy - timedelta(days=1)
    filas = leer_varias(con, [hoy.isoformat(), ayer.isoformat()])
    p = promedios(imp, hoy)
    lineas = []
    for d, cuando in ((hoy, "Hoy"), (ayer, "Ayer")):
        fila = filas.get(d.isoformat())
        if not avisa(fila):
            continue
        s = imp.salud.get(d.isoformat())
        reloj = lineas_reloj(s, p) if s else ([SIN_SINCRONIZAR] if d == hoy else [])
        lineas.append(LineaAviso(d.isoformat(), cuando, texto_aviso(fila), reloj))
    return {"lineas": lineas, "enlace": lineas[0].fecha if lineas else None, "hay_hoy": hoy.isoformat() in filas}


def historial(con: sqlite3.Connection, imp: vault.Importacion, hoy: date, sesiones: list[sqlite3.Row],
              dias: int = DIAS_HISTORIAL) -> list[dict]:
    """Los últimos 14 días, de hoy hacia atrás. Se omiten los días sin fila y sin reloj. Sin correlaciones."""
    desde = hoy - timedelta(days=dias - 1)
    filas = leer_entre(con, desde.isoformat(), hoy.isoformat())
    por_dia: dict[str, list] = {}
    for s in sesiones:
        por_dia.setdefault(s["fecha"], []).append(s)
    salida = []
    for i in range(dias):
        d = hoy - timedelta(days=i)
        f = d.isoformat()
        fila, s = filas.get(f), imp.salud.get(f)
        if fila is None and s is None:
            continue
        salida.append({"fecha": f, "d": d, "fila": fila, "salud": s, "sesiones": por_dia.get(f, []),
                       "editable": en_rango(d, hoy), "nombre": nombre_dia(d, hoy)})
    return salida
