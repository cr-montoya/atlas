"""Actividades de los sensores con las correcciones del usuario aplicadas (las correcciones viven en SQLite)."""

import sqlite3
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from . import consultas as q
from . import vault


AVISO_SIN_CONFIRMAR = "sin confirmar si fue judo o BJJ"
# Disciplinas de actividades del reloj que pueden ser una sesión registrada de cada tipo ("judo_bjj" ya no llega:
# aplicar() lo resuelve a judo o BJJ).
DISCIPLINAS_VINCULO = {"fuerza": {"fuerza"}, "combate": {"judo", "bjj", "muaythai"}}
DIAS_PENDIENTES = 14


def aplicar(a: vault.Actividad, nota: sqlite3.Row | None) -> vault.Actividad:
    """Correcciones del usuario. Un "Judo" de Polar sin confirmar se cuenta y se muestra como la disciplina
    sugerida (solo existen judo y BJJ), marcado como sin confirmar hasta que el usuario lo confirme."""
    if a.disciplina == "judo_bjj" and not (nota and nota["disciplina"]):
        avisos = tuple(AVISO_SIN_CONFIRMAR if x == vault.AVISO_JUDO_BJJ else x for x in a.avisos)
        a = replace(a, disciplina=a.sugerencia or "judo", confirmada=False, avisos=avisos)
    if nota is None:
        return a
    cambios: dict = {}
    if nota["disciplina"]:
        avisos = tuple(x for x in a.avisos if x != vault.AVISO_JUDO_BJJ)
        cambios.update(disciplina=nota["disciplina"], sugerencia=None, avisos=avisos)
        if nota["disciplina"] not in vault.COMBATE and a.fc_dudosa:
            cambios.update(fc_dudosa=False, avisos=tuple(x for x in avisos if x != vault.AVISO_FC_DUDOSA))
    if nota["es_entrenamiento"] is not None:
        cambios["entrenamiento"] = bool(nota["es_entrenamiento"])
    return replace(a, **cambios) if cambios else a


def todas(con: sqlite3.Connection, boveda: Path) -> list[vault.Actividad]:
    notas = q.anotaciones(con)
    return [aplicar(a, notas.get(a.clave)) for a in vault.importar(boveda).actividades]


def por_clave(con: sqlite3.Connection, boveda: Path, clave: str | None) -> vault.Actividad | None:
    if not clave:
        return None
    return next((a for a in todas(con, boveda) if a.clave == clave), None)


def sin_confirmar(con: sqlite3.Connection, boveda: Path) -> list[vault.Actividad]:
    """Sesiones de Polar que falta confirmar como judo o BJJ, de la más reciente a la más vieja."""
    return sorted((a for a in todas(con, boveda) if not a.confirmada), key=lambda a: (a.fecha, a.hora), reverse=True)


def candidatas_vinculo(con: sqlite3.Connection, boveda: Path, fecha: str, disciplinas: set[str],
                       sesion_id: int | None = None) -> list[vault.Actividad]:
    """Actividades del mismo día y tipo que todavía no están vinculadas a otra sesión ni descartadas para esta."""
    ocupadas = {r[0] for r in con.execute(
        "SELECT clave_importada FROM sesiones WHERE clave_importada IS NOT NULL AND id != ?", (sesion_id or 0,))}
    ocupadas |= {r[0] for r in con.execute("SELECT clave FROM vinculos_descartados WHERE sesion_id = ?", (sesion_id or 0,))}
    return [a for a in todas(con, boveda)
            if a.fecha == fecha and a.disciplina in disciplinas and a.clave not in ocupadas]


def descartar_vinculos(con: sqlite3.Connection, sesion_id: int, claves: list[str]) -> None:
    with con:
        con.executemany("INSERT OR IGNORE INTO vinculos_descartados (sesion_id, clave) VALUES (?, ?)",
                        [(sesion_id, c) for c in claves])


def vincular(con: sqlite3.Connection, boveda: Path, sesion_id: int, clave: str) -> vault.Actividad:
    """Vincula una sesión guardada con una actividad del reloj. Si la sesión no tenía duración, toma la del reloj.
    Un "Judo o BJJ" de Polar sin confirmar queda anotado con la disciplina de la sesión."""
    s = q.sesion(con, sesion_id)
    a = next((x for x in candidatas_vinculo(con, boveda, s["fecha"], DISCIPLINAS_VINCULO[s["tipo"]], sesion_id)
              if x.clave == clave), None)
    if a is None or s["tipo"] not in DISCIPLINAS_VINCULO:
        raise q.ErrorDatos("Esa actividad ya no se puede vincular con esta sesión.")
    with con:
        con.execute("UPDATE sesiones SET clave_importada = ?, duracion_s = COALESCE(duracion_s, ?) WHERE id = ?",
                    (clave, a.duracion_s, sesion_id))
        if not a.confirmada and s["disciplina"] in ("judo", "bjj"):
            q._anotar(con, clave, disciplina=s["disciplina"])
    return a


def pendientes_vinculo(con: sqlite3.Connection, todas_act: list[vault.Actividad], hoy: date) -> list[dict]:
    """Sesiones guardadas de los últimos 14 días sin vínculo vigente (sin clave, o con una que ya no existe porque
    deduplicar se quedó con la otra fuente) que tienen actividades candidatas no descartadas. Usa las actividades
    ya cargadas y dos consultas, no una por sesión."""
    desde = (hoy - timedelta(days=DIAS_PENDIENTES)).isoformat()
    existentes = {a.clave for a in todas_act}
    sesiones = con.execute("SELECT * FROM sesiones WHERE guardada = 1 AND fecha BETWEEN ? AND ? AND tipo IN ('fuerza', 'combate')"
                           " ORDER BY fecha, hora, id", (desde, hoy.isoformat())).fetchall()
    ocupadas = {r[0] for r in con.execute("SELECT clave_importada FROM sesiones WHERE clave_importada IS NOT NULL")} & existentes
    descartes: dict[int, set[str]] = {}
    for r in con.execute("SELECT sesion_id, clave FROM vinculos_descartados"):
        descartes.setdefault(r[0], set()).add(r[1])
    por_fecha: dict[str, list[vault.Actividad]] = {}
    for a in todas_act:
        if a.fecha >= desde:
            por_fecha.setdefault(a.fecha, []).append(a)
    salida = []
    for s in sesiones:
        if s["clave_importada"] and s["clave_importada"] in existentes:
            continue
        cands = [a for a in por_fecha.get(s["fecha"], []) if a.disciplina in DISCIPLINAS_VINCULO[s["tipo"]]
                 and a.clave not in ocupadas and a.clave not in descartes.get(s["id"], set())]
        if cands:
            salida.append({"sesion": s, "candidatas": cands, "texto": _texto_pendiente(s, len(cands), hoy)})
    return salida


DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _texto_pendiente(s: sqlite3.Row, n: int, hoy: date) -> str:
    d = date.fromisoformat(s["fecha"])
    cuando = "de hoy" if d == hoy else "de ayer" if d == hoy - timedelta(days=1) else \
        f"del {DIAS[d.weekday()]}" if (hoy - d).days < 7 else f"del {d.day}/{d.month}"
    nombre = "fuerza" if s["tipo"] == "fuerza" else vault.NOMBRES.get(s["disciplina"], s["disciplina"])
    if n == 1:
        return f"Tu reloj registró una sesión que puede ser la de {nombre} {cuando}"
    return f"Tu reloj registró {n} sesiones que pueden ser la de {nombre} {cuando}"
