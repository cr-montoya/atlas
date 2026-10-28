"""Resumen de una semana ISO y comparación entre dos semanas, con la dirección de cada métrica.

Cada entreno cuenta una vez: una sesión de la app vinculada a una actividad del reloj usa la duración,
la FC y las zonas del reloj; una actividad del reloj sin sesión cuenta sola. Las actividades marcadas
"probablemente no es entrenamiento" no entran. Lo que no tiene dato es None ("sin dato"), nunca 0.
"""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import actividades as act
from . import consultas as q
from . import logica, vault

GRUPO_DISCIPLINA = {
    "fuerza": "Fuerza", "judo": "Judo", "bjj": "BJJ", "muaythai": "Muay Thai",
    "caminata": "Caminata", "caminadora": "Cardio", "carrera": "Cardio", "ciclismo": "Cardio", "cardio": "Cardio",
    "otro": "Otro",
}
ORDEN_DISCIPLINAS = ("Fuerza", "Judo", "BJJ", "Muay Thai", "Cardio", "Caminata", "Otro")


@dataclass
class Entreno:
    fecha: str
    disciplina: str
    duracion_s: int | None
    fc_media: int | None = None
    fc_dudosa: bool = False
    zonas_s: tuple[int, ...] | None = None
    molestia: int | None = None
    sesion_id: int | None = None
    clave: str | None = None

    @property
    def grupo(self) -> str:
        return GRUPO_DISCIPLINA.get(self.disciplina, "Otro")


@dataclass
class Semana:
    semana: str
    lunes: date
    domingo: date
    entrenos: list[Entreno] = field(default_factory=list)
    carga_g: int | None = None
    series_grupo: Counter = field(default_factory=Counter)
    tecnicas: Counter = field(default_factory=Counter)
    situaciones: Counter = field(default_factory=Counter)
    zonas_s: list[int] | None = None
    zonas_estimadas: bool = False
    sueno_s: int | None = None
    hrv_ms: int | None = None
    fc_reposo: int | None = None
    pasos: int | None = None
    molestia_mil: int | None = None
    dias_salud: int = 0

    @property
    def sesiones(self) -> int:
        return len(self.entrenos)

    @property
    def minutos_s(self) -> int:
        return sum(e.duracion_s or 0 for e in self.entrenos)

    def por_disciplina(self) -> dict[str, tuple[int, int]]:
        """{grupo: (sesiones, segundos)}"""
        salida: dict[str, list[int]] = {}
        for e in self.entrenos:
            s = salida.setdefault(e.grupo, [0, 0])
            s[0] += 1
            s[1] += e.duracion_s or 0
        return {k: (v[0], v[1]) for k, v in salida.items()}

    @property
    def etiqueta(self) -> str:
        meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
        a, b = self.lunes, self.domingo
        if a.month == b.month:
            rango = f"{a.day} al {b.day} {meses[b.month - 1]}"
        else:
            rango = f"{a.day} {meses[a.month - 1]} al {b.day} {meses[b.month - 1]}"
        return f"{self.semana[-3:]} · {rango}"


def _promedio(valores: list[int]) -> int | None:
    return round(sum(valores) / len(valores)) if valores else None


def entrenos(con: sqlite3.Connection, boveda: Path, desde: str, hasta: str,
             todas_act: list[vault.Actividad] | None = None) -> list[Entreno]:
    todas_act = todas_act if todas_act is not None else act.todas(con, boveda)
    por_clave = {a.clave: a for a in todas_act}
    notas = q.anotaciones(con)
    salida, usadas = [], set()
    for s in q.sesiones_entre(con, desde, hasta):
        a = por_clave.get(s["clave_importada"]) if s["clave_importada"] else None
        if a:
            usadas.add(a.clave)
        salida.append(Entreno(s["fecha"], s["disciplina"], (a.duracion_s if a else None) or s["duracion_s"],
                              a.fc_media if a else None, a.fc_dudosa if a else False, a.zonas_s if a else None,
                              s["molestia_hombro"], s["id"], a.clave if a else None))
    for a in todas_act:
        if a.clave in usadas or not a.entrenamiento or not desde <= a.fecha <= hasta:
            continue
        n = notas.get(a.clave)
        salida.append(Entreno(a.fecha, a.disciplina, a.duracion_s, a.fc_media, a.fc_dudosa, a.zonas_s,
                              n["molestia_hombro"] if n else None, None, a.clave))
    return sorted(salida, key=lambda e: e.fecha)


def resumen(con: sqlite3.Connection, boveda: Path, semana: str, todas_act: list[vault.Actividad] | None = None,
            imp: vault.Importacion | None = None) -> Semana:
    lunes, domingo = logica.rango_semana(semana)
    desde, hasta = lunes.isoformat(), domingo.isoformat()
    sem = Semana(semana, lunes, domingo, entrenos(con, boveda, desde, hasta, todas_act))

    # Fuerza: carga total y series por grupo muscular
    pc = q.peso_corporal_g(con, boveda)
    cargas = []
    for e in sem.entrenos:
        if e.sesion_id is None or e.disciplina != "fuerza":
            continue
        cargas.append(q.carga_total_sesion(con, e.sesion_id, pc))
        for r in con.execute("SELECT e.grupo, COUNT(*) FROM series s JOIN ejercicios e ON e.id = s.ejercicio_id"
                             " WHERE s.sesion_id = ? GROUP BY e.grupo", (e.sesion_id,)):
            sem.series_grupo[r[0]] += r[1]
    if cargas:
        sem.carga_g = None if any(c is None for c in cargas) else sum(cargas)

    # Combate: técnicas y situaciones trabajadas
    ids = [e.sesion_id for e in sem.entrenos if e.sesion_id]
    if ids:
        marcas = ",".join("?" * len(ids))
        for r in con.execute(
                "SELECT t.nombre, ct.situacion FROM combate_tecnicas ct JOIN combate_bloques b ON b.id = ct.bloque_id"
                f" LEFT JOIN tecnicas t ON t.id = ct.tecnica_id WHERE b.sesion_id IN ({marcas})", ids):
            if r[0]:
                sem.tecnicas[r[0]] += 1
            if r[1]:
                sem.situaciones[q.SITUACIONES[r[1]]] += 1

    # Tiempo por zona: del reloj si lo trajo la sincronización; si no, toda la sesión en la zona de su FC media
    tabla = vault.zonas(boveda)
    zonas = [0, 0, 0, 0, 0]
    alguna = False
    for e in sem.entrenos:
        if e.fc_dudosa:
            continue
        if e.zonas_s:
            zonas = [a + b for a, b in zip(zonas, e.zonas_s)]
            alguna = True
        elif e.fc_media and e.duracion_s and tabla:
            z = vault.zona_de(e.fc_media, tabla)
            if z:
                zonas[z - 1] += e.duracion_s
                alguna = sem.zonas_estimadas = True
    sem.zonas_s = zonas if alguna else None

    # Salud diaria (la noche cuenta para el día en que termina, como la registra Garmin)
    imp = imp or vault.importar(boveda)
    dias = [imp.salud[d] for d in (str(lunes + timedelta(days=i)) for i in range(7)) if d in imp.salud]
    sem.dias_salud = len(dias)
    sem.sueno_s = _promedio([d.sueno_s for d in dias if d.sueno_s])
    sem.hrv_ms = _promedio([d.hrv_ms for d in dias if d.hrv_ms])
    sem.fc_reposo = _promedio([d.fc_reposo for d in dias if d.fc_reposo])
    sem.pasos = _promedio([d.pasos for d in dias if d.pasos is not None])

    molestias = [e.molestia for e in sem.entrenos if e.molestia is not None]
    sem.molestia_mil = round(sum(molestias) * 1000 / len(molestias)) if molestias else None
    return sem


@dataclass
class Metrica:
    grupo: str
    nombre: str
    a: int | None
    b: int | None
    escala: str              # conteo | s | g | mil | lpm | ms
    unidad: str
    direccion: str
    nota: str = ""

    @property
    def delta(self) -> logica.Delta | None:
        return logica.delta(self.a, self.b, self.direccion)


def comparar(a: Semana, b: Semana) -> list[Metrica]:
    m: list[Metrica] = [
        Metrica("Volumen", "Sesiones", a.sesiones, b.sesiones, "conteo", "sesiones", "neutra"),
        Metrica("Volumen", "Minutos", a.minutos_s, b.minutos_s, "s", "", "neutra"),
    ]
    da, db = a.por_disciplina(), b.por_disciplina()
    for g in ORDEN_DISCIPLINAS:
        if g in da or g in db:
            m.append(Metrica("Por disciplina", f"{g}: sesiones", da.get(g, (0, 0))[0], db.get(g, (0, 0))[0], "conteo", "", "neutra"))
            m.append(Metrica("Por disciplina", f"{g}: minutos", da.get(g, (0, 0))[1], db.get(g, (0, 0))[1], "s", "", "neutra"))
    for i in range(5):
        za = a.zonas_s[i] if a.zonas_s else None
        zb = b.zonas_s[i] if b.zonas_s else None
        m.append(Metrica("Tiempo por zona", f"Z{i + 1}", za, zb, "s", "", "neutra",
                         "estimado" if a.zonas_estimadas or b.zonas_estimadas else ""))
    m.append(Metrica("Fuerza", "Carga total", a.carga_g, b.carga_g, "g", "kg", "neutra"))
    for g in sorted(set(a.series_grupo) | set(b.series_grupo)):
        m.append(Metrica("Fuerza", f"Series de {g}", a.series_grupo.get(g, 0), b.series_grupo.get(g, 0), "conteo", "", "neutra"))
    m += [
        Metrica("Recuperación", "Sueño promedio", a.sueno_s, b.sueno_s, "s", "", "mas"),
        Metrica("Recuperación", "HRV promedio", a.hrv_ms, b.hrv_ms, "conteo", "ms", "mas"),
        Metrica("Recuperación", "FC en reposo promedio", a.fc_reposo, b.fc_reposo, "conteo", "lpm", "menos"),
        Metrica("Recuperación", "Pasos promedio", a.pasos, b.pasos, "conteo", "", "mas"),
        Metrica("Hombro", "Molestia promedio", a.molestia_mil, b.molestia_mil, "mil", "de 10", "menos"),
    ]
    return m


def semanas_recientes(hoy: date, n: int = 26) -> list[str]:
    return [logica.semana_iso(hoy - timedelta(weeks=i)) for i in range(n)]
