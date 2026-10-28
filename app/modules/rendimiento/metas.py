"""Metas con anillos y conteos regresivos (fase 4).

Solo metas con cifra en el vault: pasos y líquidos (plan de la nutricionista) y Muay Thai o BJJ 2 veces por
semana (objetivos-deportivos.md). "Marcarse" no tiene meta numérica: el peso se muestra como tendencia, sin
meta inventada. Las velocidades de caminadora no van: son exploratorias y la distancia del reloj en
caminadora no es fiable (el 2026-10-19 Garmin dio 1,56 km donde la banda marcó 1,3).
"""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import actividades as act
from . import evaluaciones as ev
from . import logica, nutricion, semanas, tablero, vault
from .tablero import Anillo, _frac

META_MT_BJJ = 2


def construir(con: sqlite3.Connection, boveda: Path, hoy: date) -> dict:
    imp = vault.importar(boveda)
    plan = nutricion.plan_vigente(boveda)

    # Pasos: últimos 7 días con dato (Garmin cuenta también los del entrenamiento)
    meta_pasos = (plan.pasos if plan and plan.pasos else None) or vault.meta_pasos(boveda) or 8000
    dias7 = [(hoy - timedelta(days=i)).isoformat() for i in range(1, 8)]
    pasos7 = [imp.salud[d].pasos for d in dias7 if d in imp.salud and imp.salud[d].pasos is not None]
    prom = round(sum(pasos7) / len(pasos7)) if pasos7 else None
    cumplidos = sum(1 for p in pasos7 if p >= meta_pasos)
    pasos = {"anillo": Anillo(_frac(prom, meta_pasos), logica.fmt_decimal(prom or 0, 1) if prom is not None else "",
                              prom, 1, "mil", f"Pasos promedio de los últimos 7 días, meta {meta_pasos}"),
             "meta": meta_pasos, "dias": len(pasos7), "cumplidos": cumplidos}

    # Líquidos: hoy y promedio de la semana, solo con lo registrado
    meta_ml = (plan.liquidos_ml if plan else None) or 3000
    lunes, _ = logica.rango_semana(logica.semana_iso(hoy))
    filas = con.execute("SELECT fecha, agua_vasos FROM comidas_dia WHERE fecha BETWEEN ? AND ? AND agua_vasos IS NOT NULL",
                        (lunes.isoformat(), hoy.isoformat())).fetchall()
    agua = {r["fecha"]: r["agua_vasos"] * nutricion.VASO_ML for r in filas}
    hoy_ml = agua.get(hoy.isoformat())
    liquidos = {"anillo": Anillo(_frac(hoy_ml, meta_ml), logica.fmt_decimal(hoy_ml, 1) if hoy_ml is not None else "",
                                 hoy_ml, 1, "L", f"Líquidos registrados hoy, meta {meta_ml // 1000} L"),
                "meta_ml": meta_ml, "dias": len(agua), "cumplidos": sum(1 for v in agua.values() if v >= meta_ml)}

    # Muay Thai o BJJ esta semana
    sa = semanas.resumen(con, boveda, logica.semana_iso(hoy), act.todas(con, boveda), imp)
    mt_bjj = [e for e in sa.entrenos if e.disciplina in ("muaythai", "bjj")]
    combate = {"anillo": Anillo(_frac(len(mt_bjj), META_MT_BJJ), str(len(mt_bjj)), len(mt_bjj) * 1000, 0, "sesiones",
                                f"{len(mt_bjj)} sesiones de Muay Thai o BJJ de {META_MT_BJJ} esta semana"),
               "meta": META_MT_BJJ}

    # Comidas registradas esta semana (registro, no adherencia)
    sem = nutricion.semana(con, plan, lunes, hoy)
    comidas = {"anillo": Anillo(_frac(sem["registrados"], sem["posibles"]), str(sem["registrados"]),
                                sem["registrados"] * 1000, 0, f"de {sem['posibles']}",
                                f"{sem['registrados']} comidas registradas de {sem['posibles']} posibles esta semana"),
               "posibles": sem["posibles"]}

    # Peso: tendencia de la serie más reciente (mismo método), sin meta
    meds = ev.todas(con, boveda)
    peso = None
    con_peso = [m for m in meds if m.tipo == "antropometria" and "Peso" in m.valores]
    if con_peso:
        metodo = max(con_peso, key=lambda m: m.fecha).metodo
        puntos = ev.serie(meds, "antropometria", "Peso", metodo)
        if puntos:
            ult, prev = puntos[-1], (puntos[-2] if len(puntos) > 1 else None)
            peso = {"fecha": ult[0].fecha, "valor_mil": ult[1].valor_mil, "metodo": metodo,
                    "delta": logica.delta(prev[1].valor_mil, ult[1].valor_mil, "neutra") if prev else None,
                    "fecha_prev": prev[0].fecha if prev else None}

    return {"pasos": pasos, "liquidos": liquidos, "combate": combate, "comidas": comidas,
            "peso": peso, "hitos": tablero.hitos_con_texto(boveda, hoy), "plan": plan}
