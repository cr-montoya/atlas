"""Imagen proyectada (openspec/changes/v1-imagen-proyectada): una ilustración de cada pose para una fecha
objetivo, en dos pasos con Codex.

Paso 1 (análisis): Codex recibe hechos con fecha y fuente (peso, composición, nutrición, entrenamiento),
las fotos base y las de calibración, y devuelve por zona una magnitud en escala cerrada, sin cifras. La app
valida el JSON, rechaza cualquier dígito y baja todo lo que pase del techo por horizonte (regla de la app,
no una proyección). Paso 2 (una llamada por pose): solo la foto base y ese análisis en palabras.

Nada de esto escribe en el vault. Las ilustraciones van a data/fotos/generadas/ (600, PNG sin metadatos) y
no entran en el resumen para IA.
"""

import io
import json
import os
import re
import shutil
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.core.config import Config
from app.core.db import conectar
from app.core.plantillas import MESES

from . import actividades as act
from . import codex, competencia, logica, nutricion, semanas, trabajos, vault
from . import evaluaciones as ev
from . import fotos as fx

MIN_DIAS, MAX_DIAS = 42, 182
FOTO_VIEJA_DIAS = 14
GENERADAS = "generadas"
MAGNITUDES = ("sin_cambio", "muy_leve", "leve", "moderado")
DIRECCIONES = ("ninguna", "menos_grasa", "mas_musculo", "menos_musculo", "mas_grasa")
ZONAS = ("abdomen", "pecho", "hombros", "brazos", "espalda", "piernas")
PALABRA = {"sin_cambio": "sin cambio", "muy_leve": "muy leve, casi imperceptible", "leve": "leve", "moderado": "moderado",
           "ninguna": "ninguna", "menos_grasa": "menos grasa", "mas_musculo": "más músculo",
           "menos_musculo": "menos músculo", "mas_grasa": "más grasa"}
OBJETIVO = ('"marcarse" (estar definido, sin meta numérica) y "ponerse muy fuerte", según objetivos-deportivos.md. '
            "Es contexto, no resultado; no lo uses para decidir la magnitud.")
ESCENARIOS = {
    "como_vas": ("Siguiendo como vas", "mantiene la frecuencia de entrenamiento de las últimas 4 semanas (según Garmin y "
                 "Polar) y la alimentación que muestran los datos"),
    "plan": ("Cumpliendo el plan", "entrena con esa misma frecuencia y sigue el plan de la nutricionista tal como está "
             "escrito"),
}
ESCENARIO_DEFECTO = "como_vas"
CANCELADOS: set[int] = set()
PROGRESO: dict[int, str] = {}   # trabajo -> "Análisis, 1 de 3" (mismo proceso que la app)

ESQUEMA = {
    "type": "object", "additionalProperties": False, "required": ["zonas", "supuestos", "faltantes", "confianza"],
    "properties": {
        "zonas": {"type": "object", "additionalProperties": False, "required": list(ZONAS), "properties": {
            z: {"type": "object", "additionalProperties": False, "required": ["magnitud", "direccion", "nota"],
                "properties": {"magnitud": {"type": "string", "enum": list(MAGNITUDES)},
                               "direccion": {"type": "string", "enum": list(DIRECCIONES)},
                               "nota": {"type": "string", "pattern": "^[^0-9]*$"}}} for z in ZONAS}},
        "supuestos": {"type": "array", "items": {"type": "string", "pattern": "^[^0-9]*$"}},
        "faltantes": {"type": "array", "items": {"type": "string", "pattern": "^[^0-9]*$"}},
        "confianza": {"type": "string", "enum": ["baja", "media", "alta"]},
    },
}


class ImagenInvalida(ValueError):
    """La solicitud no se puede lanzar; el mensaje dice por qué."""


class AnalisisInvalido(RuntimeError):
    pass


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c)).lower()


def fecha_corta(d: date, hoy: date | None = None) -> str:
    texto = f"{d.day} {MESES[d.month - 1][:3]}"
    return texto if hoy is not None and d.year == hoy.year else f"{texto} {d.year}"


# Fecha y horizonte ----------------------------------------------------------

def rango(hoy: date) -> tuple[date, date]:
    return hoy + timedelta(days=MIN_DIAS), hoy + timedelta(days=MAX_DIAS)


def validar_fecha(texto: str, hoy: date) -> date:
    lo, hi = rango(hoy)
    try:
        d = date.fromisoformat((texto or "").strip())
    except ValueError:
        d = None
    if d is None or not lo <= d <= hi:
        raise ImagenInvalida(f"Elige una fecha entre el {fecha_corta(lo)} y el {fecha_corta(hi)}")
    return d


def cirugia(boveda: Path) -> vault.Hito | None:
    return next((h for h in vault.hitos(boveda) if _norm(h.nombre).startswith("cirugia")), None)


def atajos(boveda: Path, hoy: date) -> list[tuple[str, date]]:
    lo, hi = rango(hoy)
    salida = []
    for h in vault.hitos(boveda):
        if _norm(h.nombre).startswith("cirugia"):
            if lo <= h.inicio <= hi:
                salida.append((f"Antes de la cirugía ({fecha_corta(h.inicio)})", h.inicio))
            continue
        nombre = h.nombre[0].lower() + h.nombre[1:]
        if h.inicio == h.fin:
            if lo <= h.inicio <= hi:
                salida.append((f"{h.nombre} ({fecha_corta(h.inicio, hoy)})", h.inicio))
            continue
        for etq, d in ((f"Inicio del {nombre}", h.inicio), (f"Fin del {nombre}", h.fin)):
            if lo <= d <= hi:
                salida.append((f"{etq} ({fecha_corta(d, hoy)})", d))
    return sorted(salida, key=lambda x: x[1])


@dataclass(frozen=True)
class Horizonte:
    objetivo: date
    efectivo: date
    dias: int
    cortado: bool
    aviso: str = ""

    @property
    def semanas(self) -> float:
        return self.dias / 7


def horizonte(hoy: date, objetivo: date, boveda: Path) -> Horizonte:
    c = cirugia(boveda)
    if c and objetivo > c.inicio:
        aviso = (f"La ilustración extiende tus últimas 4 semanas solo hasta el {fecha_corta(c.inicio)}; en el "
                 f"{c.texto or 'periodo de la cirugía'} está la cirugía (fecha exacta sin definir) y la "
                 "ilustración no supone cambios en ese tramo.")
        return Horizonte(objetivo, c.inicio, (c.inicio - hoy).days, True, aviso)
    return Horizonte(objetivo, objetivo, (objetivo - hoy).days, False)


# Poses y foto base ----------------------------------------------------------

def estado_poses(con: sqlite3.Connection, hoy: date) -> list[dict]:
    salida = []
    for pose, nombre in fx.POSES.items():
        base = fx.ultima(con, pose)
        dias = (hoy - date.fromisoformat(base.fecha)).days if base else None
        salida.append({"pose": pose, "nombre": nombre, "base": base, "dias": dias,
                       "vieja": dias is not None and dias > FOTO_VIEJA_DIAS})
    return salida


# Tendencia y calibración ----------------------------------------------------

def _d(f: str) -> date:
    return date.fromisoformat(f)


def _pesos(meds: list[ev.Medicion]) -> list[ev.Medicion]:
    return sorted((m for m in meds if m.tipo == "antropometria" and "Peso" in m.valores and m.precision == "dia"),
                  key=lambda m: m.fecha)


def tendencia(meds: list[ev.Medicion], hoy: date) -> tuple[dict | None, str]:
    """Tendencia observada de peso solo con mismo método y evaluador, la última de 60 días o menos y 28 días o
    más entre las dos. Si no se puede, el motivo va a Faltantes."""
    pesos = _pesos(meds)
    if not pesos:
        return None, "sin tendencia de peso válida: no hay mediciones de peso"
    metodo = pesos[-1].metodo or "sin método"
    misma = [m for m in pesos if (m.metodo or "sin método") == metodo]
    if len(misma) < 2:
        return None, f"sin tendencia de peso válida: solo hay una medición de {metodo}"
    a, b = misma[-2], misma[-1]
    if not a.evaluador or a.evaluador != b.evaluador:
        return None, f"sin tendencia de peso válida: las dos últimas mediciones de {metodo} son de evaluadores distintos"
    if (hoy - _d(b.fecha)).days > 60:
        return None, f"sin tendencia de peso válida: la última medición de {metodo} tiene más de sesenta días"
    dias = (_d(b.fecha) - _d(a.fecha)).days
    if dias < 28:
        return None, f"sin tendencia de peso válida: las dos últimas mediciones de {metodo} están a menos de cuatro semanas"
    g_semana = round((b.valores["Peso"].valor_mil - a.valores["Peso"].valor_mil) * 7 / dias)
    return {"desde": a.fecha, "hasta": b.fecha, "metodo": metodo, "evaluador": b.evaluador, "g_semana": g_semana}, ""


def _peso_cerca(pesos: list[ev.Medicion], fecha: str) -> ev.Medicion | None:
    cerca = [m for m in pesos if abs((_d(m.fecha) - _d(fecha)).days) <= 14]
    return min(cerca, key=lambda m: abs((_d(m.fecha) - _d(fecha)).days)) if cerca else None


def _sentido(par: tuple[fx.Foto, fx.Foto], pesos: list[ev.Medicion]) -> int | None:
    a, b = (_peso_cerca(pesos, f.fecha) for f in par)
    if not a or not b or a is b or a.metodo != b.metodo:
        return None
    dif = b.valores["Peso"].valor_mil - a.valores["Peso"].valor_mil
    return (dif > 0) - (dif < 0)


@dataclass
class Calibracion:
    par: tuple[fx.Foto, fx.Foto] | None
    ruido: tuple[fx.Foto, fx.Foto] | None
    filtrado: bool
    motivo: str = ""


def calibracion(fotos: list[fx.Foto], base: fx.Foto, dias_horizonte: int, meds: list[ev.Medicion],
                tend: dict | None) -> Calibracion:
    otras = sorted((f for f in fotos if f.id != base.id), key=lambda f: f.fecha)
    lo, hi = 0.75 * dias_horizonte, 1.5 * dias_horizonte
    pares = [(a, b) for i, a in enumerate(otras) for b in otras[i + 1:]]
    sep = lambda p: (_d(p[1].fecha) - _d(p[0].fecha)).days  # noqa: E731
    candidatos = [p for p in pares if lo <= sep(p) <= hi]
    filtrado = False
    if tend and tend["g_semana"] and candidatos:
        signo = 1 if tend["g_semana"] > 0 else -1
        pref = [p for p in candidatos if _sentido(p, _pesos(meds)) == signo]
        if pref:
            candidatos, filtrado = pref, True
    clave = lambda p: (p[1].fecha, p[0].fecha)  # noqa: E731
    par = max(candidatos, key=clave) if candidatos else None
    ruidos = [p for p in pares if sep(p) <= 7]
    ruido = max(ruidos, key=clave) if ruidos else None
    motivo = "" if par else (f"sin calibración (no hay dos fotos de {fx.POSES[base.pose].lower()} separadas de "
                             f"{int(lo + 0.999)} a {int(hi)} días)")
    return Calibracion(par, ruido, filtrado, motivo)


# Datos del paso 1 -----------------------------------------------------------

def escenario_valido(clave: str | None) -> str:
    return clave if clave in ESCENARIOS else ESCENARIO_DEFECTO


def indicio(meds: list[ev.Medicion]) -> str:
    """Sin tendencia válida: la dirección del peso entre las dos últimas mediciones del mismo método separadas por 28
    días o más, aunque sean de evaluadores distintos o viejas. Dice hacia dónde va, no cuánto."""
    pesos = _pesos(meds)
    if not pesos:
        return ""
    metodo = pesos[-1].metodo or "sin método"
    misma = [m for m in pesos if (m.metodo or "sin método") == metodo]
    b = misma[-1]
    a = next((m for m in reversed(misma[:-1]) if (_d(b.fecha) - _d(m.fecha)).days >= 28), None)
    if a is None:
        return ""
    ga, gb = a.valores["Peso"].valor_mil, b.valores["Peso"].valor_mil
    verbo = "bajó" if gb < ga else ("subió" if gb > ga else "se mantuvo")
    motivo = "evaluadores distintos" if a.evaluador != b.evaluador else "fuera de la ventana de la tendencia"
    return (f"indicativo ({motivo}): {verbo} de {logica.fmt_decimal(ga, 2)} kg el {a.fecha} a "
            f"{logica.fmt_decimal(gb, 2)} kg el {b.fecha}, {metodo}")


@dataclass
class Preparacion:
    hoy: date
    horizonte: Horizonte
    poses: list[str]
    bases: dict[str, fx.Foto]
    calibraciones: dict[str, Calibracion]
    secciones: list[tuple[str, list[str]]]
    faltantes: list[str]
    tendencia: dict | None
    techo: str
    fotos_paso1: list[tuple[fx.Foto, str]] = field(default_factory=list)
    escenario: str = ESCENARIO_DEFECTO

    @property
    def ids(self) -> dict:
        return {p: {"base": self.bases[p].id,
                    "par": [f.id for f in self.calibraciones[p].par] if self.calibraciones[p].par else None,
                    "ruido": [f.id for f in self.calibraciones[p].ruido] if self.calibraciones[p].ruido else None}
                for p in self.poses}


def _kg(g: int) -> str:
    return f"{logica.fmt_decimal(g, 2)} kg"


def _techo(h: Horizonte, tend: dict | None, cals: dict[str, Calibracion]) -> str:
    if tend is None and not any(c.par for c in cals.values()):
        return "muy_leve"
    return "leve" if h.semanas < 8 else "moderado"


def preparar(con: sqlite3.Connection, boveda: Path, hoy: date, objetivo: date, poses: list[str],
             fijas: dict | None = None, escenario: str = ESCENARIO_DEFECTO) -> Preparacion:
    """Arma todo lo que se envía. Con `fijas` (ids guardados al confirmar) usa exactamente esas fotos."""
    poses = [p for p in fx.POSES if p in poses]
    if not poses:
        raise ImagenInvalida("Elige al menos una pose con foto.")
    h = horizonte(hoy, objetivo, boveda)
    meds = ev.todas(con, boveda)
    tend, motivo_tend = tendencia(meds, hoy)
    faltantes = [motivo_tend] if motivo_tend else []

    bases, cals = {}, {}
    for p in poses:
        lista = fx.de_pose(con, p)
        if fijas:
            ids = fijas.get(p) or {}
            por_id = {f.id: f for f in lista}
            base = por_id.get(ids.get("base"))
            if base is None:
                raise ImagenInvalida(f"La foto base de {fx.POSES[p].lower()} se borró.")
            par = tuple(por_id[i] for i in ids["par"]) if ids.get("par") and all(i in por_id for i in ids["par"]) else None
            ruido = tuple(por_id[i] for i in ids["ruido"]) if ids.get("ruido") and all(i in por_id for i in ids["ruido"]) else None
            cal = calibracion(lista, base, h.dias, meds, tend)
            cals[p] = Calibracion(par, ruido, cal.filtrado, "" if par else cal.motivo)
        else:
            base = lista[-1] if lista else None
            if base is None:
                raise ImagenInvalida(f"Toma una foto de {fx.POSES[p].lower()}")
            cals[p] = calibracion(lista, base, h.dias, meds, tend)
        bases[p] = base
        if not cals[p].par:
            faltantes.append(f"{fx.POSES[p].lower()}: {cals[p].motivo}")

    escenario = escenario_valido(escenario)
    nombre_esc, desc_esc = ESCENARIOS[escenario]
    secciones: list[tuple[str, list[str]]] = [("Escenario", [f"Escenario: {nombre_esc.lower()}: {desc_esc}."])]
    # Horizonte
    lineas = [f"Fecha objetivo: {objetivo.isoformat()}. Horizonte efectivo: {h.dias} días "
              f"({logica.fmt_decimal(round(h.semanas * 1000), 1)} semanas) desde hoy, {hoy.isoformat()}."]
    if h.cortado:
        lineas += [h.aviso, "No comentes la cirugía ni la recuperación."]
    secciones.append(("Horizonte", lineas))

    # Peso
    pesos = _pesos(meds)
    lineas = []
    ultimos: dict[str, ev.Medicion] = {}
    for m in pesos:
        ultimos[m.metodo or "sin método"] = m
    for metodo, m in sorted(ultimos.items(), key=lambda x: x[1].fecha, reverse=True):
        lineas.append(f"{m.fecha}: {_kg(m.valores['Peso'].valor_mil)} ({metodo}"
                      + (f", {m.evaluador}" if m.evaluador else "") + ")")
    if not tend and indicio(meds):
        lineas.append(indicio(meds))
    if tend:
        lineas.append(f"observado: {logica.fmt_decimal(tend['g_semana'], 2)} kg/semana entre {tend['desde']} y "
                      f"{tend['hasta']} ({tend['metodo']}, {tend['evaluador']})")
    c = competencia.vigente(boveda, hoy).competencia
    if c:
        desde = (c.torneo.date() - timedelta(days=56)).isoformat()
        corte = [x for x in competencia.pesajes(con, desde) if x.fecha <= c.torneo.date().isoformat()]
        if corte:
            lineas.append(f"Pesajes de control para el torneo del {c.clave} (sin corte de peso); no son tendencia: "
                          + "; ".join(f"{x.fecha} {_kg(x.peso_g)}" for x in corte))
    secciones.append(("Peso", lineas or ["sin mediciones de peso"]))

    # Composición
    lineas = []
    grasa = [m for m in meds if m.tipo == "antropometria" and "% graso" in m.valores]
    if grasa:
        m = max(grasa, key=lambda x: x.fecha)
        lineas.append(f"Último % graso: {logica.fmt_decimal(m.valores['% graso'].valor_mil, 2)} % el {m.fecha} ({m.metodo})")
    else:
        faltantes.append("sin porcentaje graso medido")
    cintura = sorted((m for m in meds if m.tipo == "antropometria" and "Perímetro cintura" in m.valores), key=lambda x: x.fecha)
    if cintura:
        m = cintura[-1]
        per = [f"{k.removeprefix('Perímetro ')} {logica.fmt_decimal(v.valor_mil, 1)} cm" for k, v in m.valores.items()
               if k.startswith("Perímetro")]
        texto = f"Perímetros el {m.fecha} ({m.metodo}): " + ", ".join(per)
        if len(cintura) > 1 and cintura[-2].evaluador != m.evaluador:
            texto += "; evaluadores distintos; comparar con cautela"
        lineas.append(texto)
    secciones.append(("Composición", lineas or ["sin mediciones de composición"]))

    # Nutrición
    lineas = []
    plan = nutricion.plan_vigente(boveda)
    if plan:
        lineas.append(f"Plan vigente ({plan.archivo}, {plan.profesional or 'profesional sin nombre'}"
                      + (f", próximo control {plan.control}" if plan.control else "") + "): "
                      + "; ".join(f"{m.nombre}: {m.texto or 'sin intercambios'}" for m in plan.momentos))
        if plan.liquidos_ml:
            lineas.append(f"Líquidos mínimos del plan: {logica.fmt_decimal(plan.liquidos_ml, 1)} L")
        if plan.pasos:
            lineas.append(f"Pasos mínimos del plan: {plan.pasos} fuera del entrenamiento")
    else:
        faltantes.append("sin plan nutricional vigente en el vault")
    primero = con.execute("SELECT MIN(fecha) FROM comidas_registro").fetchone()[0]
    if primero:
        n = con.execute("SELECT COUNT(*) FROM comidas_registro WHERE momento != 'extra' AND fecha <= ?",
                        (hoy.isoformat(),)).fetchone()[0]
        posibles = ((hoy - _d(primero)).days + 1) * 5
        lineas.append(f"{n} de {posibles} comidas registradas desde {primero} (registro, no adherencia; no cuenta lo "
                      "anotado a mano en el vault)")
    else:
        faltantes.append("sin comidas registradas en la app")
    desde28 = (hoy - timedelta(days=28)).isoformat()
    agua = [r[0] for r in con.execute("SELECT agua_vasos FROM comidas_dia WHERE fecha >= ? AND fecha < ? AND agua_vasos "
                                      "IS NOT NULL", (desde28, hoy.isoformat()))]
    if agua:
        lineas.append(f"Agua: promedio de {logica.fmt_decimal(round(sum(agua) * nutricion.VASO_ML / len(agua)), 1)} L en "
                      f"{len(agua)} días con registro de 28")
    imp = vault.importar(boveda)
    pasos = [s.pasos for d, s in imp.salud.items() if desde28 <= d < hoy.isoformat() and s.pasos and s.pasos >= 1500]
    if pasos:
        lineas.append(f"Pasos de Garmin: promedio de {round(sum(pasos) / len(pasos))} en {len(pasos)} días con dato de los "
                      "últimos 28 (Garmin incluye los del entrenamiento; la meta del plan es sin ellos)")
    secciones.append(("Nutrición", lineas or ["sin datos de nutrición"]))

    # Entrenamiento
    lineas = []
    todas = act.todas(con, boveda)
    semana = logica.semana_iso(hoy)
    lista_sem = [semana]
    for _ in range(3):
        lista_sem.append(logica.semana_anterior(lista_sem[-1]))
    total: dict[str, list[int]] = {}
    con_carga = False
    for s in lista_sem:
        r = semanas.resumen(con, boveda, s, todas, imp)
        con_carga = con_carga or bool(r.carga_g)
        for g, (n, seg) in r.por_disciplina().items():
            t = total.setdefault(g, [0, 0])
            t[0] += n
            t[1] += seg
    if total:
        lineas.append(f"Últimas 4 semanas ({lista_sem[-1]} a {semana}): " + "; ".join(
            f"{g}: {n} sesiones, {logica.fmt_duracion(seg)}" for g, (n, seg) in sorted(total.items())))
    if not con_carga:
        lineas.append("Fuerza: sin registro de cargas en la app")
    if c and -28 <= (c.torneo.date() - hoy).days <= 56:
        inicio = c.plan[0].fecha.isoformat() if c.plan else hoy.isoformat()
        lineas.append(f"Del {inicio} al {c.clave} la rutina es la preparación del torneo, con descarga al final y sin corte "
                      "de peso; no es la rutina habitual")
    secciones.append(("Entrenamiento", lineas or ["sin entrenamientos en las últimas 4 semanas"]))

    secciones.append(("Objetivo", [OBJETIVO]))

    # Calibración y fotos del paso 1
    fotos_paso1: list[tuple[fx.Foto, str]] = []
    lineas = []
    for p in poses:
        fotos_paso1.append((bases[p], f"foto base de {fx.POSES[p].lower()}, {bases[p].fecha}"))
    for p in poses:
        cal = cals[p]
        nombre = fx.POSES[p].lower()
        if cal.par:
            a, b = cal.par
            fotos_paso1 += [(a, f"calibración de {nombre}, antes, {a.fecha}"), (b, f"calibración de {nombre}, después, {b.fecha}")]
            lineas.append(f"{nombre}: par de calibración {a.fecha} y {b.fecha} ({(_d(b.fecha) - _d(a.fecha)).days} días). "
                          "Es un techo: el cambio de la ilustración no puede ser mayor que el que se ve entre esas dos fotos."
                          + ("" if cal.filtrado else " No hay tendencia válida para elegir un par en el mismo sentido."))
        else:
            lineas.append(f"{nombre}: {cal.motivo}")
        if cal.ruido:
            a, b = cal.ruido
            fotos_paso1 += [(a, f"par de ruido de {nombre}, {a.fecha}"), (b, f"par de ruido de {nombre}, {b.fecha}")]
            lineas.append(f"{nombre}: par de ruido {a.fecha} y {b.fecha}: esto es lo que cambian solo la luz y la pose; "
                          "un cambio de este tamaño no cuenta.")
    secciones.append(("Calibración", lineas))
    vistos, unicas = set(), []
    for f, rol in fotos_paso1:
        if f.id not in vistos:
            vistos.add(f.id)
            unicas.append((f, rol))
    techo = _techo(h, tend, cals)
    if faltantes:
        secciones.append(("Faltantes", faltantes))
    return Preparacion(hoy, h, poses, bases, cals, secciones, faltantes, tend, techo, unicas, escenario)


# Prompts --------------------------------------------------------------------

def _texto_secciones(secciones: list[tuple[str, list[str]]]) -> str:
    return "\n\n".join(f"### {t}\n" + "\n".join(f"- {l}" for l in ls) for t, ls in secciones)


def prompt_paso1(prep: Preparacion) -> str:
    imagenes = "\n".join(f"- Imagen {i}: {rol}" for i, (_, rol) in enumerate(prep.fotos_paso1, 1))
    return f"""## Rol y tarea
Eres analista de composición corporal. Con las fotos adjuntas y los datos de abajo, responde, zona por zona: qué
cambio visible es esperable en el cuerpo de esta persona si se cumple el escenario durante el horizonte efectivo.
Estima con lo fisiológicamente esperable para una persona entrenada con estos datos, de forma realista: esto
alimenta una ilustración que no debe exagerar ni inventar resultados.

## Imágenes adjuntas, en orden
{imagenes}

## Datos (hechos con fecha y fuente; no hay cifras para la fecha objetivo y no debes inventarlas)
{_texto_secciones(prep.secciones)}

## Cómo decidir
- Escala por zona: sin_cambio, muy_leve (casi imperceptible), leve, moderado. Dirección: ninguna, menos_grasa,
  mas_musculo, menos_musculo o mas_grasa.
- Responde la pregunta del escenario: la magnitud es la esperable si el escenario se cumple, proporcional al
  horizonte efectivo. La falta de datos baja la confianza; no obliga a poner sin_cambio. Usa sin_cambio solo en
  una zona donde el escenario no hace esperable ningún cambio visible.
- Un indicio de dirección del peso dice hacia dónde va, no cuánto.
- El par de calibración es un techo; el par de ruido muestra lo que cambian solo la luz y la pose.
- El objetivo es contexto, no resultado.
- Ningún texto lleva cifras: ni kilos, ni porcentajes, ni semanas, ni fechas. Solo palabras.

## Reglas
{trabajos.REGLAS_CONTENIDO}
No ejecutes comandos ni leas archivos; usa solo lo que está en este mensaje y las imágenes adjuntas.

## Salida
Solo el JSON del esquema: zonas (abdomen, pecho, hombros, brazos, espalda, piernas con magnitud, direccion y
nota), supuestos, faltantes y confianza (baja, media o alta).
"""


def validar_analisis(texto: str, techo: str) -> tuple[dict, list[str]]:
    """Valida el JSON del paso 1, rechaza dígitos y baja al techo. Devuelve (análisis, ajustes)."""
    try:
        a = json.loads(texto)
        assert isinstance(a, dict) and set(a) == {"zonas", "supuestos", "faltantes", "confianza"}
        assert a["confianza"] in ("baja", "media", "alta")
        assert isinstance(a["zonas"], dict) and set(a["zonas"]) == set(ZONAS)
        for z in a["zonas"].values():
            assert isinstance(z, dict) and set(z) == {"magnitud", "direccion", "nota"}
            assert z["magnitud"] in MAGNITUDES and z["direccion"] in DIRECCIONES and isinstance(z["nota"], str)
        for k in ("supuestos", "faltantes"):
            assert isinstance(a[k], list) and all(isinstance(x, str) for x in a[k])
    except (ValueError, AssertionError, TypeError, KeyError):
        raise AnalisisInvalido("Codex no devolvió el análisis en el formato pedido") from None
    textos = [z["nota"] for z in a["zonas"].values()] + a["supuestos"] + a["faltantes"]
    if any(re.search(r"\d", t) for t in textos):
        raise AnalisisInvalido("El análisis trajo cifras; no se generó ninguna imagen")
    ajustes = []
    tope = MAGNITUDES.index(techo)
    for nombre, z in a["zonas"].items():
        if MAGNITUDES.index(z["magnitud"]) > tope:
            ajustes.append(f"{nombre}: {z['magnitud']} bajado a {techo} por el techo")
            z["magnitud"] = techo
        if z["magnitud"] == "sin_cambio":
            z["direccion"] = "ninguna"
    return a, ajustes


LIMITES = {
    "sin_cambio": "queda igual que en la foto",
    "muy_leve": "casi idéntica a la foto; no debería notarse sin comparar lado a lado",
    "leve": ("algo menos de volumen o un contorno un poco más nítido; no aparecen músculos, líneas ni separaciones que "
             "no se vean ya en la foto"),
    "moderado": ("se acentúa lo que ya se ve en la foto, de forma notoria pero creíble; no aparecen músculos ni líneas "
                 "nuevas con relieve marcado"),
}


def prompt_paso2(pose: str, analisis: dict, excedidas: list[str] | None = None, luz: bool = False) -> str:
    zonas = "\n".join(
        f"- {z}: {PALABRA[d['magnitud']]}" + (f", {PALABRA[d['direccion']]}" if d["direccion"] != "ninguna" else "")
        + f". Límite: {LIMITES[d['magnitud']]}." + (f" {d['nota']}" if d["nota"] else "")
        for z, d in analisis["zonas"].items())
    reintento = ""
    if excedidas or luz:
        partes = ([f"se pasó en {', '.join(excedidas)}"] if excedidas else []) + (["cambió la luz o el contraste"] if luz else [])
        reintento = (f"\n## Intento anterior\nLa ilustración anterior {' y '.join(partes)}. Esta vez quédate claramente por "
                     "debajo del límite de cada zona: en esas zonas el cambio debe ser menor que antes y sin líneas nuevas, y "
                     "la luz debe quedar igual a la de la foto.\n")
    return f"""Imagen adjunta: edit target, identity-preserve. Es una foto real de {fx.POSES[pose].lower()}.

## Tarea
Edita la imagen adjunta para ilustrar, de forma realista y conservadora, el cambio de composición corporal descrito
en el análisis. Es una ilustración, no una predicción.

## Invariantes
Misma persona. No cambies la cara, la piel ni su tono, los tatuajes, los lunares, el cabello, la ropa, la pose, el
encuadre, la proporción de la imagen, la cámara, el lente, la iluminación ni el fondo.

## Qué puede cambiar
Solo la composición corporal visible, y solo en las zonas y la magnitud del análisis, sin pasar el límite de cada zona.

## Análisis
{zonas}
{reintento}
## Reglas de realismo
- Si una zona dice sin cambio, no la toques.
- No cambies el contraste, las sombras, la exposición ni el tono de la piel: el relieve no puede venir de la luz.
- Ante la duda, quédate por debajo del límite: es mejor un cambio menor que uno exagerado.
- Sin idealizar, sin "pump", sin bronceado ni aceite, sin retoque de piel ni de cara.
- Sin texto ni marcas de agua.

## Salida
Llama a image_gen una sola vez. No copies ni muevas archivos y no ejecutes comandos.
"""


ESQUEMA_VERIF = {
    "type": "object", "additionalProperties": False, "required": ["zonas_excedidas", "luz_cambio", "nota"],
    "properties": {"zonas_excedidas": {"type": "array", "items": {"type": "string", "enum": list(ZONAS)}},
                   "luz_cambio": {"type": "boolean"}, "nota": {"type": "string", "pattern": "^[^0-9]*$"}},
}


def prompt_verificacion(pose: str, analisis: dict) -> str:
    zonas = "\n".join(f"- {z}: {PALABRA[d['magnitud']]}. Límite: {LIMITES[d['magnitud']]}." for z, d in analisis["zonas"].items())
    return f"""## Tarea
Eres revisor. La Imagen 1 es una foto real de {fx.POSES[pose].lower()}; la Imagen 2 es una ilustración hecha a partir de ella.
Compara las dos y di si la ilustración se pasó del análisis.

## Análisis permitido, zona por zona
{zonas}

## Cómo juzgar
- Una zona se excede si su cambio es mayor que su límite, o si aparecen líneas, separaciones o relieve que no estaban
  en la foto y la zona no es moderado.
- luz_cambio es verdadero si cambiaron el contraste, las sombras, la exposición o el tono de la piel.
- Sé estricto: ante la duda, marca la zona.

## Reglas
{trabajos.REGLAS_CONTENIDO}
No ejecutes comandos ni leas archivos; usa solo este mensaje y las dos imágenes. La nota va sin cifras.

## Salida
Solo el JSON del esquema: zonas_excedidas, luz_cambio y nota.
"""


def validar_verificacion(texto: str) -> dict:
    try:
        v = json.loads(texto)
        assert isinstance(v, dict) and set(v) == {"zonas_excedidas", "luz_cambio", "nota"}
        assert isinstance(v["zonas_excedidas"], list) and all(z in ZONAS for z in v["zonas_excedidas"])
        assert isinstance(v["luz_cambio"], bool) and isinstance(v["nota"], str) and not re.search(r"\d", v["nota"])
    except (ValueError, AssertionError, TypeError):
        raise AnalisisInvalido("La verificación no vino en el formato pedido") from None
    return v


# Ejecución ------------------------------------------------------------------

def carpeta_generadas(cfg: Config) -> Path:
    p = cfg.fotos_path / GENERADAS
    p.mkdir(parents=True, exist_ok=True)
    os.chmod(p, 0o700)
    return p


def _registrar_limpieza(cfg: Config, trabajo_id: int, tipo: str, valor: str) -> None:
    con = conectar(cfg.db_path)
    try:
        with con:
            con.execute("INSERT OR IGNORE INTO imagen_limpieza (trabajo_id, tipo, valor) VALUES (?, ?, ?)",
                        (trabajo_id, tipo, valor))
    finally:
        con.close()


def _limpiar(cfg: Config, tipo: str, valor: str) -> None:
    if tipo == "hilo":
        codex.limpiar_hilo(cfg.codex_home, valor)
    else:
        p = Path(valor)
        if p.parent == cfg.fotos_path and p.name.startswith("tmp-codex-"):
            shutil.rmtree(p, ignore_errors=True)
    con = conectar(cfg.db_path)
    try:
        with con:
            con.execute("DELETE FROM imagen_limpieza WHERE tipo = ? AND valor = ?", (tipo, valor))
    finally:
        con.close()


def limpiar_interrumpidos(cfg: Config) -> None:
    """Al arrancar: borra hilos y carpetas temporales que quedaron, y marca fallidas las poses pendientes."""
    con = conectar(cfg.db_path)
    try:
        pendientes = con.execute("SELECT tipo, valor FROM imagen_limpieza").fetchall()
        with con:
            con.execute("UPDATE imagenes_proyectadas SET estado = 'fallida', error = 'Se interrumpió porque la app se "
                        "reinició.' WHERE estado = 'pendiente'")
    finally:
        con.close()
    for r in pendientes:
        _limpiar(cfg, r["tipo"], r["valor"])


def _pose(cfg: Config, trabajo_id: int, pose: str, **campos) -> None:
    con = conectar(cfg.db_path)
    try:
        sets = ", ".join(f"{k} = ?" for k in campos)
        with con:
            con.execute(f"UPDATE imagenes_proyectadas SET {sets} WHERE trabajo_id = ? AND pose = ?",
                        (*campos.values(), trabajo_id, pose))
    finally:
        con.close()


def _guardar_imagen(cfg: Config, origen: Path, nombre: str) -> tuple[int, int]:
    try:
        with Image.open(origen) as im:
            im.load()
            limpia = im.convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise codex.FalloCodex("Codex no generó una imagen válida") from None
    destino = carpeta_generadas(cfg) / nombre
    buf = io.BytesIO()
    limpia.save(buf, "PNG")                          # sin metadatos
    fd = os.open(destino, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(buf.getvalue())
    return limpia.size


def _registro_corrida(registro: list[str], nombre: str, cmd: list[str], carpeta: Path, c: codex.Corrida) -> None:
    visible = [x.replace(str(carpeta), "<carpeta temporal>") for x in cmd]
    registro.append(f"{nombre}: $ " + " ".join(visible) + " < prompt")
    registro.append(f"{nombre}: hilo {c.thread_id or 'sin hilo'}, {c.segundos} s, eventos {json.dumps(c.eventos)}"
                    + (f", errores: {' | '.join(c.errores)}" if c.errores else ""))
    if c.mensajes:
        registro.append(f"{nombre}: Codex dijo: " + " | ".join(c.mensajes))


def _verificar(cfg: Config, pose: str, base: Path, ilustracion: Path, analisis: dict, slug, env, carpeta: Path, restante,
               cancelado, al_hilo, registro: list[str], intento: int) -> dict | None:
    """Paso 3. Devuelve la verificación, o None si no se pudo verificar (la imagen se guarda igual)."""
    esquema, salida = carpeta / "esquema_verif.json", carpeta / f"verif_{pose}_{intento}.json"
    esquema.write_text(json.dumps(ESQUEMA_VERIF), encoding="utf-8")
    prompt = prompt_verificacion(pose, analisis)
    registro.append(f"Prompt de verificación de {fx.POSES[pose].lower()} (intento {intento}):\n" + prompt)
    cmd = codex.comando(cfg.codex_cmd, carpeta, slug, [base, ilustracion], esquema, salida)
    c = None
    try:
        c = codex.correr(cmd, prompt, env, restante(), cancelado, al_hilo)
        _registro_corrida(registro, f"Verificación de {fx.POSES[pose].lower()}", cmd, carpeta, c)
        if c.codigo != 0:
            registro.append(f"Verificación de {fx.POSES[pose].lower()}: {codex.mensaje_error(c)}")
            return None
        v = validar_verificacion(salida.read_text(encoding="utf-8"))
        registro.append(f"Verificación de {fx.POSES[pose].lower()} (intento {intento}): excedidas "
                        f"{v['zonas_excedidas'] or 'ninguna'}, luz {'cambió' if v['luz_cambio'] else 'igual'}")
        return v
    except (OSError, AnalisisInvalido) as err:
        registro.append(f"Verificación de {fx.POSES[pose].lower()}: {err}")
        return None
    finally:
        if c and c.thread_id:
            _limpiar(cfg, "hilo", c.thread_id)


def _generar_pose(cfg: Config, trabajo_id: int, p: str, prep: Preparacion, analisis: dict, objetivo: date, slug, env,
                  carpeta: Path, restante, cancelado, al_hilo, registro: list[str], resultado: dict) -> None:
    base = fx.ruta(cfg.fotos_path, prep.bases[p])
    nombre = f"{objetivo.isoformat()}_{p}_{trabajo_id}.png"
    excedidas, luz, v = None, False, None
    for intento in (1, 2):
        PROGRESO[trabajo_id] = f"{fx.POSES[p]}: imagen, intento {intento}"
        p2 = prompt_paso2(p, analisis, excedidas, luz)
        registro.append(f"Prompt de {fx.POSES[p].lower()} (intento {intento}):\n" + p2)
        cmd = codex.comando(cfg.codex_cmd, carpeta, slug, [base])
        c2 = None
        try:
            c2 = codex.correr(cmd, p2, env, restante(), cancelado, al_hilo)
            _registro_corrida(registro, fx.POSES[p], cmd, carpeta, c2)
            img = codex.imagen_del_hilo(cfg.codex_home, c2.thread_id)
            if img is None:
                # Sin error ni imagen, lo que respondió Codex es lo único que explica por qué no la hizo.
                dijo = f". Respondió: {c2.mensajes[-1][:200]}" if c2.mensajes else ""
                raise codex.FalloCodex(codex.mensaje_error(c2) if c2.errores else "Codex no generó la imagen" + dijo)
            ancho, alto = _guardar_imagen(cfg, img, nombre)
        finally:
            if c2 and c2.thread_id:
                _limpiar(cfg, "hilo", c2.thread_id)
        PROGRESO[trabajo_id] = f"{fx.POSES[p]}: verificación, intento {intento}"
        v = _verificar(cfg, p, base, carpeta_generadas(cfg) / nombre, analisis, slug, env, carpeta, restante, cancelado,
                       al_hilo, registro, intento)
        if v is None:
            estado = "sin_verificar"
            break
        if not v["zonas_excedidas"] and not v["luz_cambio"]:
            estado = "dentro"
            break
        estado = "exagerada"
        excedidas, luz = v["zonas_excedidas"], v["luz_cambio"]
    _pose(cfg, trabajo_id, p, estado="lista", archivo=nombre, ancho=ancho, alto=alto, verificacion=estado,
          verificacion_nota=(v or {}).get("nota") or None, intentos=intento)
    resultado["poses"][p] = {"estado": "lista", "verificacion": estado}


def ejecutar(cfg: Config, trabajo_id: int, params: dict, registro: list[str]) -> dict:
    hoy = date.fromisoformat(params["hoy"])
    objetivo = date.fromisoformat(params["objetivo"])
    con = conectar(cfg.db_path)
    try:
        prep = preparar(con, cfg.vault_path, hoy, objetivo, params["poses"], params["fotos"], params.get("escenario"))
        with con:
            for p in prep.poses:
                con.execute("INSERT OR IGNORE INTO imagenes_proyectadas (trabajo_id, pose, foto_base_id, fecha_base, "
                            "fecha_objetivo) VALUES (?, ?, ?, ?, ?)",
                            (trabajo_id, p, prep.bases[p].id, prep.bases[p].fecha, objetivo.isoformat()))
    finally:
        con.close()
    slug = codex.modelo(cfg.codex_home)
    registro.append(f"Modelo: {slug or 'el predeterminado de Codex (no se pudo leer models_cache.json)'}")
    env = codex.entorno(trabajos.path_extendido(), cfg.codex_home)
    cancelado = lambda: trabajo_id in CANCELADOS  # noqa: E731
    fin_total = time.monotonic() + cfg.tiempo_max_imagen_s
    restante = lambda: max(1.0, min(cfg.tiempo_max_s, fin_total - time.monotonic()))  # noqa: E731

    carpeta = cfg.fotos_path / f"tmp-codex-{trabajo_id}"
    carpeta.mkdir(parents=True, exist_ok=True)
    os.chmod(carpeta, 0o700)
    _registrar_limpieza(cfg, trabajo_id, "carpeta", str(carpeta))
    al_hilo = lambda tid: _registrar_limpieza(cfg, trabajo_id, "hilo", tid)  # noqa: E731
    resultado = {"modelo": slug, "objetivo": objetivo.isoformat(), "escenario": ESCENARIOS[prep.escenario][0], "horizonte_dias": prep.horizonte.dias,
                 "aviso": prep.horizonte.aviso, "techo": prep.techo, "secciones": prep.secciones,
                 "enviado": {"paso1": [[f.fecha, rol] for f, rol in prep.fotos_paso1],
                             "paso2": {p: prep.bases[p].fecha for p in prep.poses}}, "poses": {}}
    try:
        # Paso 1
        esquema = carpeta / "esquema.json"
        esquema.write_text(json.dumps(ESQUEMA), encoding="utf-8")
        salida = carpeta / "analisis.json"
        PROGRESO[trabajo_id] = "Análisis"
        p1 = prompt_paso1(prep)
        registro.append("Prompt del análisis:\n" + p1)
        fotos1 = [fx.ruta(cfg.fotos_path, f) for f, _ in prep.fotos_paso1]
        cmd = codex.comando(cfg.codex_cmd, carpeta, slug, fotos1, esquema, salida)
        c1 = codex.correr(cmd, p1, env, restante(), cancelado, al_hilo)
        _registro_corrida(registro, "Análisis", cmd, carpeta, c1)
        if c1.thread_id:
            _limpiar(cfg, "hilo", c1.thread_id)
        if c1.codigo != 0:
            raise codex.FalloCodex(codex.mensaje_error(c1))
        try:
            texto = salida.read_text(encoding="utf-8")
        except OSError:
            raise AnalisisInvalido("Codex no devolvió el análisis en el formato pedido") from None
        analisis, ajustes = validar_analisis(texto, prep.techo)
        for a in ajustes:
            registro.append(a.replace("por el techo", f"por el techo de {prep.horizonte.dias} días"))
        resultado["analisis"], resultado["ajustes"] = analisis, ajustes

        # Paso 2 (imagen) y paso 3 (verificación) por pose, con un reintento si se pasó
        listas = 0
        for p in prep.poses:
            try:
                _generar_pose(cfg, trabajo_id, p, prep, analisis, objetivo, slug, env, carpeta, restante, cancelado,
                              al_hilo, registro, resultado)
                listas += 1
            except codex.Cancelado:
                raise
            except codex.FalloCodex as err:
                _pose(cfg, trabajo_id, p, estado="fallida", error=str(err))
                resultado["poses"][p] = {"estado": "fallida", "error": str(err)}
        if not listas:
            raise codex.FalloCodex(next(iter(resultado["poses"].values()))["error"])
        return resultado
    except Exception as err:
        con = conectar(cfg.db_path)
        try:
            with con:
                con.execute("UPDATE imagenes_proyectadas SET estado = 'fallida', error = ? WHERE trabajo_id = ? AND "
                            "estado = 'pendiente'", (str(err), trabajo_id))
        finally:
            con.close()
        raise
    finally:
        CANCELADOS.discard(trabajo_id)
        PROGRESO.pop(trabajo_id, None)
        con = conectar(cfg.db_path)
        try:
            hilos = [r[0] for r in con.execute("SELECT valor FROM imagen_limpieza WHERE trabajo_id = ? AND tipo = 'hilo'",
                                               (trabajo_id,))]
        finally:
            con.close()
        for tid in hilos:
            _limpiar(cfg, "hilo", tid)
        _limpiar(cfg, "carpeta", str(carpeta))


# Consultas para las pantallas -----------------------------------------------

def de_trabajo(con: sqlite3.Connection, trabajo_id: int) -> list[sqlite3.Row]:
    orden = {p: i for i, p in enumerate(fx.POSES)}
    filas = con.execute("SELECT * FROM imagenes_proyectadas WHERE trabajo_id = ?", (trabajo_id,)).fetchall()
    return sorted(filas, key=lambda r: orden.get(r["pose"], 9))


def imagen(con: sqlite3.Connection, imagen_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM imagenes_proyectadas WHERE id = ?", (imagen_id,)).fetchone()


def borrar(con: sqlite3.Connection, cfg: Config, imagen_id: int) -> int | None:
    r = imagen(con, imagen_id)
    if r is None:
        return None
    if r["archivo"]:
        (cfg.fotos_path / GENERADAS / r["archivo"]).unlink(missing_ok=True)
    with con:
        con.execute("DELETE FROM imagenes_proyectadas WHERE id = ?", (imagen_id,))
    return r["trabajo_id"]
