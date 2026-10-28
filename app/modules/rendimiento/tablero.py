"""Datos del tablero Hoy: semana actual frente a la anterior, esenciales, en foco, calendario, año, hitos y ayer."""

import json
import sqlite3
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from . import actividades as act
from . import competencia, logica, semanas, trabajos, vault
from . import sensaciones as sen

META_SUENO_S = 8 * 3600
META_COMBATE = 2           # objetivos-deportivos.md: retomar Muay Thai y/o BJJ, 2 veces por semana
COMBATE = {"judo", "bjj", "judo_bjj", "muaythai"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


@dataclass
class Anillo:
    frac: float | None         # 0 a 1; None = sin dato (anillo punteado)
    cifra: str
    contar: int | None         # milésimas para la animación de conteo
    decimales: int
    unidad: str
    etiqueta: str


def _frac(valor, meta) -> float | None:
    if valor is None or not meta:
        return None
    return max(0.0, min(valor / meta, 1.0))


def _molestias_por_dia(entrenos: list[semanas.Entreno]) -> dict[str, float]:
    dias: dict[str, list[int]] = defaultdict(list)
    for e in entrenos:
        if e.molestia is not None:
            dias[e.fecha].append(e.molestia)
    return {d: sum(v) / len(v) for d, v in dias.items()}


def construir(con: sqlite3.Connection, boveda: Path, hoy: date) -> dict:
    todas_act = act.todas(con, boveda)
    imp = vault.importar(boveda)
    actual = logica.semana_iso(hoy)
    anterior = logica.semana_anterior(actual)
    sa = semanas.resumen(con, boveda, actual, todas_act, imp)
    sp = semanas.resumen(con, boveda, anterior, todas_act, imp)

    # De un vistazo
    minutos = Anillo(_frac(sa.minutos_s, sp.minutos_s) if sp.minutos_s else (1.0 if sa.minutos_s else 0.0),
                     str(sa.minutos_s // 60), sa.minutos_s // 60 * 1000, 0,
                     f"de {sp.minutos_s // 60}" if sp.minutos_s else "min",
                     f"{sa.minutos_s // 60} minutos esta semana, {sp.minutos_s // 60} la anterior")
    combate_a = [e for e in sa.entrenos if e.disciplina in COMBATE]
    combate = Anillo(_frac(len(combate_a), META_COMBATE), str(len(combate_a)), len(combate_a) * 1000, 0,
                     "sesiones" if len(combate_a) != 1 else "sesión",
                     f"{len(combate_a)} sesiones de combate de {META_COMBATE} por semana")
    por_disc_combate: dict[str, int] = defaultdict(int)
    for e in combate_a:
        por_disc_combate[e.grupo] += 1

    # Hombro: promedio de la semana y tendencia de todos los registros en orden
    hist = semanas.entrenos(con, boveda, "2000-01-01", hoy.isoformat(), todas_act)
    valores = [e.molestia for e in hist if e.molestia is not None]
    hombro = {
        "promedio_mil": sa.molestia_mil, "al_alza": logica.molestia_al_alza(valores),
        "delta": logica.delta(sp.molestia_mil, sa.molestia_mil, "menos"), "aviso": logica.AVISO_MOLESTIA,
    }

    # Esenciales
    salud_60 = [imp.salud[d] for d in (str(hoy - timedelta(days=i)) for i in range(60)) if d in imp.salud]
    # Últimos 7 días con datos (la sincronización llega hasta ayer, así que un lunes la semana aún no tiene datos)
    ult7 = salud_60[:7]
    def prom(campo):
        v = [getattr(d, campo) for d in ult7 if getattr(d, campo) is not None and getattr(d, campo) != 0]
        return round(sum(v) / len(v)) if v else None
    e_sueno, e_hrv, e_fc = prom("sueno_s"), prom("hrv_ms"), prom("fc_reposo")
    v_pasos = [d.pasos for d in ult7 if d.pasos is not None]
    e_pasos = round(sum(v_pasos) / len(v_pasos)) if v_pasos else None
    ventana = (ult7[-1].fecha, ult7[0].fecha) if ult7 else None
    hrv_max = max((d.hrv_ms for d in salud_60 if d.hrv_ms), default=None)
    fc_min = min((d.fc_reposo for d in salud_60 if d.fc_reposo), default=None)
    meta_pasos = vault.meta_pasos(boveda) or 8000
    esenciales = [
        ("Sueño", "--r-bjj", Anillo(_frac(e_sueno, META_SUENO_S), logica.fmt_decimal(round((e_sueno or 0) / 3.6), 1) if e_sueno else "",
                                    round((e_sueno or 0) / 3.6) or None, 1, "h", "Sueño promedio de los últimos 7 días")),
        ("HRV", "--r-judo", Anillo(_frac(e_hrv, hrv_max), str(e_hrv or ""), (e_hrv or 0) * 1000 or None, 0, "ms",
                                   "HRV promedio de los últimos 7 días")),
        ("FC reposo", "--r-cardio", Anillo(_frac(fc_min, e_fc) if e_fc else None, str(e_fc or ""),
                                           (e_fc or 0) * 1000 or None, 0, "lpm", "FC en reposo promedio de los últimos 7 días")),
        ("Mil pasos", "--r-fuerza", Anillo(_frac(e_pasos, meta_pasos), logica.fmt_decimal(e_pasos or 0, 1) if e_pasos is not None else "",
                                           e_pasos if e_pasos is not None else None, 1, "mil pasos",
                                           f"Pasos promedio por día, meta {meta_pasos}")),
    ]

    # En foco: zonas de la semana y molestia de los últimos 30 días
    mol_dia = _molestias_por_dia(hist)
    dias30 = [str(hoy - timedelta(days=i)) for i in range(29, -1, -1)]
    serie_hombro = [{"fecha": d, "precision": "dia", "aprox": False, "v": round(mol_dia[d] * 1000)} for d in dias30 if d in mol_dia]

    # Calendario del mes y año de calor
    minutos_dia: dict[str, int] = defaultdict(int)
    for e in semanas.entrenos(con, boveda, f"{hoy.year}-01-01", f"{hoy.year}-12-31", todas_act):
        minutos_dia[e.fecha] += (e.duracion_s or 0) // 60
    cal = calendario(con, boveda, hoy, hoy.replace(day=1), todas_act, hist)
    anio = _anio(hoy, minutos_dia)

    # Hitos
    hitos = hitos_con_texto(boveda, hoy)

    # Ayer
    ayer = hoy - timedelta(days=1)
    entrenos_ayer = [e for e in hist if e.fecha == ayer.isoformat()]
    salud_ayer = imp.salud.get(ayer.isoformat())

    return {
        "sa": sa, "sp": sp, "minutos": minutos, "combate": combate, "por_disc_combate": dict(por_disc_combate),
        "carga": {"g": sa.carga_g, "antes": sp.carga_g, "delta": logica.delta(sp.carga_g, sa.carga_g, "neutra"),
                  "sesiones": sum(1 for e in sa.entrenos if e.disciplina == "fuerza"), "series": sum(sa.series_grupo.values()),
                  "frac": _frac(sa.carga_g, max(sa.carga_g or 0, sp.carga_g or 0))},
        "delta_minutos": logica.delta(sp.minutos_s, sa.minutos_s, "neutra"),
        "hombro": hombro, "esenciales": esenciales, "ventana_salud": ventana,
        "por_confirmar": sum(1 for a in todas_act if not a.confirmada),
        "vinculos": act.pendientes_vinculo(con, todas_act, hoy),
        "graficas": {"zonas": sa.zonas_s, "zonas_estimadas": sa.zonas_estimadas, "hombro": serie_hombro},
        "cal": cal, "anio": anio, "hitos": hitos,
        "ayer": ayer, "entrenos_ayer": entrenos_ayer, "salud_ayer": salud_ayer,
        "recomendacion": _recomendacion(con), "competencia": _competencia(con, boveda, hoy),
        "sentir": sen.aviso_hoy(con, imp, hoy),
    }


def _competencia(con: sqlite3.Connection, boveda: Path, hoy: date) -> dict | None:
    """El aviso de la competencia en Hoy, hasta el día del torneo, con los textos de la cuenta regresiva."""
    competencia.borrar_marcas_pasadas(con, hoy)
    c = competencia.vigente(boveda, hoy).competencia
    if not competencia.activa(c, hoy):
        return None
    pesaje, torneo = competencia.cuentas(c, competencia.ahora())
    return {"nombre": c.nombre, "pesaje": pesaje["texto"], "torneo": torneo["texto"]}


def _mes_siguiente(m: date) -> date:
    return date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def _mes_anterior(m: date) -> date:
    return date(m.year - (m.month == 1), (m.month - 2) % 12 + 1, 1)


def calendario(con: sqlite3.Connection, boveda: Path, hoy: date, mes: date,
               todas_act: list[vault.Actividad] | None = None, hist: list[semanas.Entreno] | None = None) -> dict:
    """Mes con las sesiones de cada día (lunes primero). Se navega desde el primer mes con datos hasta el actual."""
    todas_act = todas_act if todas_act is not None else act.todas(con, boveda)
    hist = hist if hist is not None else semanas.entrenos(con, boveda, "2000-01-01", hoy.isoformat(), todas_act)
    actual = hoy.replace(day=1)
    primero_datos = date.fromisoformat(hist[0].fecha).replace(day=1) if hist else actual
    mes = min(max(mes.replace(day=1), primero_datos), actual)
    ndias = monthrange(mes.year, mes.month)[1]
    ultimo = date(mes.year, mes.month, ndias)
    por_dia: dict[str, list[str]] = defaultdict(list)
    for e in hist:
        if mes.isoformat() <= e.fecha <= ultimo.isoformat():
            por_dia[e.fecha].append(e.disciplina)
    celdas = [{"fuera": True, "n": (mes - timedelta(days=i)).day} for i in range(mes.weekday(), 0, -1)]
    for d in range(1, ndias + 1):
        f = date(mes.year, mes.month, d)
        celdas.append({"fuera": False, "n": d, "fecha": f.isoformat(), "semana": logica.semana_iso(f), "hoy": f == hoy,
                       "futuro": f > hoy, "sesiones": por_dia.get(f.isoformat(), []),
                       "nombre": f"{sen.DIAS[f.weekday()]} {d}"})
    celdas += [{"fuera": True, "n": i} for i in range(1, 7 - ultimo.weekday())]
    anterior = _mes_anterior(mes)
    siguiente = _mes_siguiente(mes)
    return {
        "titulo": f"{MESES[mes.month - 1].capitalize()} {mes.year}", "celdas": celdas, "mes": mes.strftime("%Y-%m"),
        "anterior": anterior.strftime("%Y-%m") if anterior >= primero_datos else None,
        "siguiente": siguiente.strftime("%Y-%m") if siguiente <= actual else None,
        "sesiones": sum(len(v) for v in por_dia.values()),
    }


def _rango(a: date, b: date) -> str:
    if a == b:
        return f"{a.day} de {MESES[a.month - 1]}"
    if a.month == b.month and a.year == b.year:
        return f"{a.day} al {b.day} de {MESES[b.month - 1]}"
    return f"{a.day} de {MESES[a.month - 1]} al {b.day} de {MESES[b.month - 1]}"


def _anio(hoy: date, minutos_dia: dict[str, int]) -> dict:
    """Cuadrícula de 53 semanas x 7 días del año en curso, con intensidad 0 a 5 por minutos."""
    inicio = date(hoy.year, 1, 1)
    inicio -= timedelta(days=inicio.weekday())
    celdas = []
    for i in range(53 * 7):
        d = inicio + timedelta(days=i)
        if d.year > hoy.year:
            break
        m = minutos_dia.get(d.isoformat(), 0)
        nivel = 0 if m == 0 else 1 if m < 30 else 2 if m < 60 else 3 if m < 90 else 4 if m < 120 else 5
        celdas.append({"x": (i // 7) * 15, "y": (i % 7) * 15 + 16, "nivel": nivel, "fecha": d.isoformat(), "min": m,
                       "fuera": d.year < hoy.year or d > hoy})
    meses = [{"x": ((date(hoy.year, m, 1) - inicio).days // 7) * 15, "t": MESES[m - 1][:3]} for m in range(1, 13)]
    return {"celdas": celdas, "meses": meses, "total_min": sum(v for k, v in minutos_dia.items() if k.startswith(str(hoy.year)))}


def _recomendacion(con: sqlite3.Connection) -> dict | None:
    """El último "Analiza mi semana" terminado, con su texto, para la tarjeta del tablero."""
    t = trabajos.ultimo(con, "analisis_semana", "listo")
    if t is None:
        return None
    try:
        res = json.loads(t["resultado"] or "{}")
    except ValueError:
        res = {"texto": t["resultado"]}
    from .analisis import resumen_parametros
    return {"id": t["id"], "fin": t["fin"], "texto": res.get("texto", ""),
            "que": resumen_parametros(t["tipo"], json.loads(t["parametros"] or "{}"))}


def hitos_con_texto(boveda: Path, hoy: date) -> list[dict]:
    """Hitos de objetivos-deportivos.md con el conteo regresivo en palabras."""
    hitos = []
    lista = list(vault.hitos(boveda))
    c = competencia.vigente(boveda, hoy).competencia
    if not competencia.activa(c, hoy):
        c = None
    if c:
        lista.append(vault.Hito(c.nombre, c.torneo.date(), c.torneo.date(), False, ""))
    for h in sorted(lista, key=lambda h: h.inicio):
        dias = (h.inicio - hoy).days
        if hoy < h.inicio:
            texto = f"en unos {dias} días" if h.aproximado else (f"faltan {dias} días" if dias != 1 else "mañana")
        elif hoy <= h.fin:
            texto = "en curso"
        else:
            texto = "ya pasó"
        detalle = h.texto if h.aproximado else _rango(h.inicio, h.fin)
        hitos.append({"nombre": h.nombre, "texto": texto, "detalle": detalle, "pasado": hoy > h.fin, "dias": dias,
                      "aproximado": h.aproximado, "inicio": h.inicio.isoformat(),
                      "enlace": "/rendimiento/competencia" if c and h.nombre == c.nombre else None})
    return hitos
