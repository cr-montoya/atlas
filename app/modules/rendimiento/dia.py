"""La vista de un día: lo que hay de esa fecha (entrenos, reloj, comidas, sensaciones, peso, fotos, tests y voz).

Se arma con las funciones existentes y una consulta por sección, nunca una por fila. No edita nada: cada sección
enlaza a la pantalla que ya edita ese dato.
"""

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import actividades as act
from . import consultas as q
from . import evaluaciones as ev
from . import fotos as fx
from . import logica, semanas, vault
from . import nutricion as nu
from . import sensaciones as sen


class FechaFuera(LookupError):
    """La fecha está fuera de lo que navega el calendario: 404."""


def primer_dia(con: sqlite3.Connection, boveda: Path, hoy: date, todas_act: list[vault.Actividad]) -> date:
    """El día 1 del primer mes que navega el calendario de Hoy (el primer mes con entrenos, o el actual)."""
    hist = semanas.entrenos(con, boveda, "2000-01-01", hoy.isoformat(), todas_act)
    return date.fromisoformat(hist[0].fecha).replace(day=1) if hist else hoy.replace(day=1)


def _resumenes(con: sqlite3.Connection, ids: list[int]) -> dict[int, str]:
    """"3 ejercicios, 12 series" o "2 bloques", con dos consultas agrupadas."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    salida: dict[int, str] = {}
    for r in con.execute(f"SELECT sesion_id, COUNT(DISTINCT ejercicio_id) e, COUNT(*) n FROM series"
                         f" WHERE sesion_id IN ({marcas}) GROUP BY sesion_id", ids):
        salida[r["sesion_id"]] = f"{r['e']} ejercicio{'s' if r['e'] != 1 else ''}, {r['n']} serie{'s' if r['n'] != 1 else ''}"
    for r in con.execute(f"SELECT sesion_id, COUNT(*) n FROM combate_bloques WHERE sesion_id IN ({marcas}) GROUP BY sesion_id",
                         ids):
        salida[r["sesion_id"]] = f"{r['n']} bloque{'s' if r['n'] != 1 else ''}"
    return salida


def voz_del_dia(con: sqlite3.Connection, fecha: str) -> list[dict]:
    """Relatos guardados con algún registro de esa fecha, en una sola consulta con json_each."""
    filas = con.execute(
        "SELECT DISTINCT v.id, v.rondas, v.creada FROM voz_entradas v, json_each(v.registros) j"
        " WHERE v.estado = 'guardada' AND v.registros IS NOT NULL AND json_valid(v.registros)"
        " AND json_extract(j.value, '$.fecha') = ? ORDER BY v.id", (fecha,)).fetchall()
    salida = []
    for r in filas:
        rondas = json.loads(r["rondas"] or "[]")
        texto = " ".join(rondas)
        salida.append({"id": r["id"], "creada": r["creada"],
                       "fragmento": (texto[:140] + ("…" if len(texto) > 140 else "")) if texto else ""})
    return salida


def construir(con: sqlite3.Connection, boveda: Path, fecha: str, hoy: date) -> dict:
    d = date.fromisoformat(fecha)
    todas_act = act.todas(con, boveda)
    desde = primer_dia(con, boveda, hoy, todas_act)
    if d > hoy or d < desde:
        raise FechaFuera(fecha)
    imp = vault.importar(boveda)
    editable = sen.en_rango(d, hoy)

    # Cómo me sentí
    fila = sen.leer(con, fecha)

    # Entrenamiento: sesiones del día, su vínculo con el reloj y las actividades sin sesión
    sesiones = q.sesiones_entre(con, fecha, fecha)
    por_clave = {a.clave: a for a in todas_act}
    resumen = _resumenes(con, [s["id"] for s in sesiones])
    entrenos = [{"s": s, "resumen": resumen.get(s["id"], ""), "reloj": por_clave.get(s["clave_importada"])}
                for s in sesiones]
    vinculadas = q.claves_vinculadas(con)
    sueltas = [a for a in todas_act if a.fecha == fecha and a.clave not in vinculadas]

    # Comidas frente al plan vigente
    comidas = nu.dia(con, fecha)
    plan = nu.plan_vigente(boveda)
    hay_comidas = bool(comidas.comidas or comidas.agua_vasos is not None or comidas.suplementos or comidas.notas)

    # Peso y cuerpo
    pesaje = con.execute("SELECT * FROM pesajes WHERE fecha = ?", (fecha,)).fetchone()
    peso_vault = [(t, v) for t in vault.tests(boveda) if t.fecha == fecha and t.fecha_precision == "dia"
                  for v in t.valores if v.medida == "Peso" and v.unidad == "kg"]
    fotos = [fx._fila(r) for r in con.execute("SELECT * FROM fotos_cuerpo WHERE fecha = ? ORDER BY pose", (fecha,))]

    # Tests del día (de la app y del vault, con fecha exacta)
    tests = [m for m in ev.todas(con, boveda) if m.fecha == fecha and m.precision == "dia"]

    anterior = d - timedelta(days=1)
    siguiente = d + timedelta(days=1)
    return {
        "d": d, "fecha": fecha, "hoy": hoy, "editable": editable,
        "cuando": "hoy" if d == hoy else "ayer" if d == hoy - timedelta(days=1) else "",
        "anterior": anterior.isoformat() if anterior >= desde else None,
        "siguiente": siguiente.isoformat() if siguiente <= hoy else None,
        "semana": logica.semana_iso(d),
        "fila": fila, "entrenos": entrenos, "sueltas": sueltas,
        "salud": imp.salud.get(fecha), "comidas": comidas if hay_comidas else None, "plan": plan,
        "pesaje": pesaje, "peso_vault": peso_vault, "fotos": fotos, "tests": tests,
        "voz": voz_del_dia(con, fecha),
    }
