"""Semilla de la demo: base, vault ficticio y fotos de siluetas para "James Restrepo".

Uso (en el worktree de la demo): BRAIN_DEMO=1 uv run python -m app.demo [--fecha AAAA-MM-DD] [--semilla N]

Todo es inventado y reproducible: con la misma fecha y la misma semilla salen los mismos datos y los mismos
archivos. No lee nada fuera del código y de las carpetas de la demo, que se validan antes de borrarlas.
"""

import argparse
import io
import json
import random
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

from app.core.config import Config, es_demo, leer_config, validar_demo
from app.core.db import conectar, migrar
from app.modules.finanzas import consultas as q
from app.modules.finanzas import real
from app.modules.finanzas import seed as semilla_finanzas
from app.modules.finanzas.logica import Linea
from app.modules.rendimiento import carga_tests
from app.modules.rendimiento import fotos as fx

MESES_HISTORIA = 15
DIAS_RELOJ = 120
SEMANAS_COMIDAS = 10
DIAS_SENSACIONES = 21
DIAS_SEMANA = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


# ---------- Utilidades ----------

def _meses_atras(d: date, meses: int) -> date:
    m = d.month - 1 - meses
    return date(d.year + m // 12, m % 12 + 1, 1)


def _fin_de_mes(d: date) -> date:
    siguiente = date(d.year + d.month // 12, d.month % 12 + 1, 1)
    return siguiente - timedelta(days=1)


def _dias(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _coma(x: float, dec: int = 1) -> str:
    return f"{x:.{dec}f}".replace(".", ",")


def _borrar(ruta: Path) -> None:
    if ruta.is_dir() and not ruta.is_symlink():
        shutil.rmtree(ruta)
    elif ruta.exists() or ruta.is_symlink():
        ruta.unlink()


# ---------- Finanzas ----------

NETO_ANTES, NETO_AHORA = 8_400_000, 9_150_000
CUOTA_APTO, ADMINISTRACION = 3_150_000, 420_000
MERCADO, SERVICIOS, GIMNASIO = 900_000, 380_000, 260_000

GASTOS = {  # categoría -> (notas posibles, mínimo, máximo)
    "comida": (["Almuerzo", "Domicilio", "Restaurante", "Café", "Fruver"], 18_000, 160_000),
    "transporte": (["Gasolina carro", "Taxi", "Peajes", "Parqueadero"], 8_000, 180_000),
    "salud": (["Farmacia", "Fisioterapia", "Proteína"], 40_000, 260_000),
    "casa": (["Aseo", "Ferretería", "Decoración"], 30_000, 350_000),
    "regalos": (["Cumpleaños", "Detalle"], 80_000, 300_000),
    "ocio": (["Cine", "Salida con amigos", "Streaming", "Libro", "Concierto"], 30_000, 280_000),
    "otro": (["Varios"], 20_000, 120_000),
}


def _datos_base(inicio: date, hoy: date) -> dict:
    """La parte estática de finanzas, en el formato de app.modules.finanzas.seed."""
    return {
        "bolsillos": [{"nombre": n, "tipo": t} for n, t in
                      (("Casa", "fijo"), ("Tarjeta", "deuda"), ("Ahorro", "ahorro"), ("Libre", "libre"),
                       ("Fondos", "ahorro"))],
        "deudas": [
            {"nombre": "Andino Platino USD", "moneda": "USD", "saldo": "1.800,00", "tasa": "2,05"},
            {"nombre": "Andino Platino COP", "moneda": "COP", "saldo": "3.200.000", "tasa": "2,05"},
            {"nombre": "Crédito apartamento", "moneda": "COP", "saldo": "286.000.000", "tasa": "0,98",
             "cuota": _miles(CUOTA_APTO), "prepagar": False},
        ],
        "cuentas": [
            {"nombre": "Banco Andino nómina"},
            {"nombre": "Banco Andino ahorro", "rendimiento_ea": "9,1", "rendimiento_nota": "Ficticio"},
            {"nombre": "Cooperativa Sol CDT", "rendimiento_ea": "10,4", "rendimiento_nota": "Ficticio"},
            {"nombre": "Kora"},
        ],
        "metas": [{"nombre": "6 meses de básicos", "objetivo": "45.000.000", "cuentas": ["Banco Andino ahorro"]},
                  {"nombre": "Abono a capital del apartamento", "objetivo": "120.000.000",
                   "cuentas": ["Cooperativa Sol CDT"]}],
        "plantillas": [
            {"nombre": "15", "lineas": [
                {"concepto": "Cuota apartamento", "bolsillo": "Casa", "monto": _miles(CUOTA_APTO),
                 "deuda": "Crédito apartamento"},
                {"concepto": "Administración", "bolsillo": "Casa", "monto": _miles(ADMINISTRACION)},
                {"concepto": "Mitad del mercado", "bolsillo": "Casa", "monto": _miles(MERCADO)},
                {"concepto": "Ahorro", "bolsillo": "Ahorro", "monto": "1.800.000"},
                {"concepto": "Libre", "bolsillo": "Libre", "monto": "resto"},
            ]},
            {"nombre": "30", "lineas": [
                {"concepto": "Mitad del mercado", "bolsillo": "Casa", "monto": _miles(MERCADO)},
                {"concepto": "Servicios", "bolsillo": "Casa", "monto": _miles(SERVICIOS)},
                {"concepto": "Gimnasio y academia", "bolsillo": "Casa", "monto": _miles(GIMNASIO)},
                {"concepto": "Tarjeta USD", "bolsillo": "Tarjeta", "monto": "pedir", "deuda": "Andino Platino USD"},
                {"concepto": "Tarjeta COP", "bolsillo": "Tarjeta", "monto": "pedir", "deuda": "Andino Platino COP"},
                {"concepto": "Ahorro", "bolsillo": "Ahorro", "monto": "2.200.000"},
                {"concepto": "Libre", "bolsillo": "Libre", "monto": "resto"},
            ]},
        ],
        "escenario": {"neto_quincena": _miles(NETO_AHORA), "gasto_basico": "7.400.000", "tarjeta_mes": "1.100.000",
                      "libre": "1.800.000", "meta_m4": "180.000.000"},
        "fondos": [
            {"nombre": "SOAT y revisión del carro", "objetivo": "1.400.000",
             "fecha_objetivo": date(hoy.year + 1, 3, 10).isoformat(), "cada_meses": 12, "bolsillo": "Fondos"},
            {"nombre": "Viaje a Japón", "objetivo": "14.000.000",
             "fecha_objetivo": date(hoy.year + 1, 6, 20).isoformat(), "bolsillo": "Fondos"},
        ],
        "eventos": [
            {"nombre": "Prima de diciembre", "fecha": date(hoy.year, 12, 15).isoformat(), "tipo": "ingreso",
             "monto": "8.200.000", "estimado": True},
            {"nombre": "Intereses de cesantías", "fecha": date(hoy.year + 1, 1, 31).isoformat(), "tipo": "ingreso",
             "monto": "1.900.000", "estimado": True},
            {"nombre": "Cesantías", "fecha": date(hoy.year + 1, 2, 15).isoformat(), "tipo": "ingreso",
             "monto": "15.800.000", "estimado": True, "deuda": "Crédito apartamento"},
            {"nombre": "Prima de junio", "fecha": date(hoy.year + 1, 6, 15).isoformat(), "tipo": "ingreso",
             "monto": "8.200.000", "estimado": True},
            {"nombre": "Regalos de diciembre", "fecha": date(hoy.year, 12, 20).isoformat(), "tipo": "gasto",
             "monto": "1.800.000", "estimado": True},
        ],
    }


def _finanzas(con: sqlite3.Connection, r: random.Random, hoy: date) -> dict:
    inicio = _meses_atras(hoy, MESES_HISTORIA)
    semilla_finanzas.cargar(con, _datos_base(inicio, hoy))
    b = {x["nombre"]: x["id"] for x in q.bolsillos(con)}
    d = {x["nombre"]: x["id"] for x in q.deudas(con)}
    c = {x["nombre"]: x["id"] for x in q.cuentas(con)}
    cat = {x["nombre"]: x["id"] for x in real.categorias(con)}
    plant = {p["nombre"]: p["id"] for p in q.plantillas(con)}
    aumento = _meses_atras(hoy, 3)
    ahorro, cdt, nomina, kora = 21_000_000, 38_000_000, 2_000_000, 400_000
    trm = 412_000  # centavos
    n_quincenas = n_gastos = 0
    mes = inicio
    while mes <= hoy:
        for dia in (15, _fin_de_mes(mes).day):
            fecha = date(mes.year, mes.month, dia)
            if fecha > hoy:
                continue
            trm = max(365_000, min(430_000, trm + r.randint(-6_000, 5_500)))
            neto = NETO_AHORA if fecha >= aumento else NETO_ANTES
            pid = plant["15" if dia == 15 else "30"]
            lineas = []
            for l in q.lineas_plantilla(con, pid):
                monto = l.monto
                if l.deuda_id:
                    saldo = q.deuda(con, l.deuda_id)
                    if saldo["moneda"] == "USD":
                        usd = min(saldo["saldo"], r.choice((9_000, 10_000, 11_000)))  # centavos de USD
                        monto = usd * trm // 10_000 if usd else 0
                    else:
                        monto = min(saldo["saldo"], monto if monto is not None else r.choice((600_000, 720_000, 850_000)))
                lineas.append(Linea(l.concepto, l.bolsillo_id, monto, l.modo, l.deuda_id, l.plantilla_linea_id,
                                    fondo_id=l.fondo_id))
            fijos = sum(x.monto for x in lineas if x.modo != "resto")
            lineas = [Linea(x.concepto, x.bolsillo_id, neto - fijos if x.modo == "resto" else x.monto, x.modo,
                            x.deuda_id, x.plantilla_linea_id, fondo_id=x.fondo_id) for x in lineas if x.monto != 0]
            qid = q.confirmar_quincena(con, fecha.isoformat(), neto, pid, lineas, trm=trm)
            n_quincenas += 1
            for fila in q.lineas_quincena(con, qid):
                if fecha < hoy - timedelta(days=3) or fila["concepto"] in ("Cuota apartamento", "Ahorro"):
                    real.marcar_pago(con, fila["id"], fecha.isoformat())
            ahorro += next((x.monto for x in lineas if x.concepto == "Ahorro"), 0)
        # Gastos del mes: más en diciembre
        fin = min(_fin_de_mes(mes), hoy)
        cuantos = r.randint(25, 40) + (8 if mes.month == 12 else 0)
        for _ in range(cuantos):
            fecha = mes + timedelta(days=r.randint(0, (fin - mes).days))
            categoria = r.choices(list(GASTOS), weights=(40, 18, 8, 10, 5 if mes.month != 12 else 15, 14, 5))[0]
            notas, minimo, maximo = GASTOS[categoria]
            monto = r.randint(minimo // 1000, maximo // 1000) * 1000
            bolsillo = b["Tarjeta"] if r.random() < 0.25 else b["Libre"]
            real.crear_gasto(con, fecha.isoformat(), monto, bolsillo, cat[categoria], r.choice(notas))
            n_gastos += 1
        # Foto del patrimonio al cierre del mes (o hoy)
        if mes.month in (3, 6, 9, 12) and ahorro > 40_000_000:
            ahorro -= 8_000_000
            cdt += 8_000_000
        cdt += cdt * 8 // 1000
        nomina = r.randint(1_200_000, 3_400_000)
        kora = r.randint(250_000, 700_000)
        cuentas = {c["Banco Andino nómina"]: nomina, c["Banco Andino ahorro"]: ahorro,
                   c["Cooperativa Sol CDT"]: cdt, c["Kora"]: kora}
        deudas = {x["id"]: x["saldo"] for x in q.deudas(con)}
        q.guardar_foto(con, fin.isoformat(), trm, cuentas, deudas)
        mes = _meses_atras(mes, -1)
    real.guardar_revision(con, (hoy.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"), {
        "distinto": "Gasté más en comida por fuera.", "inesperado": "Mantenimiento del carro.",
        "ajustar": "Llevar el almuerzo tres veces por semana.", "plantillas": "", "sensacion": 4})
    return {"quincenas": n_quincenas, "gastos": n_gastos}


# ---------- Rendimiento ----------

FUERZA = [  # (ejercicio, carga inicial g, carga final g, reps)
    ("Sentadilla trasera", 60_000, 90_000, 6), ("Peso muerto", 80_000, 120_000, 5),
    ("Press banca", 50_000, 72_500, 6), ("Dominadas", 0, 10_000, 6), ("Remo con barra", 45_000, 62_500, 8),
    ("Press militar", 30_000, 42_500, 6), ("Hip thrust", 70_000, 110_000, 10), ("Face pull", 15_000, 22_500, 12),
]
COMBATE_TECNICAS = {"bjj": ["Guardia cerrada", "Armbar", "Triángulo", "Raspado de tijera", "Knee slice", "Kimura",
                            "Toma de espalda", "Mata león", "Media guardia", "Pasaje de presión"]}


def _peso_g(dias_desde_inicio: int, total: int, r: random.Random) -> int:
    """Baja de ~81 a ~77,4 kg en la historia, con ruido de ±0,4 kg."""
    base = 81_000 - 3_600 * dias_desde_inicio / max(1, total)
    return int(round((base + r.uniform(-400, 400)) / 100) * 100)


def _rendimiento(con: sqlite3.Connection, r: random.Random, hoy: date, cfg: Config) -> dict:
    inicio = _meses_atras(hoy, MESES_HISTORIA)
    total = (hoy - inicio).days
    ej = {x["nombre"]: x["id"] for x in con.execute("SELECT id, nombre FROM ejercicios")}
    tec = {(x["disciplina"], x["nombre"]): x["id"] for x in con.execute("SELECT id, disciplina, nombre FROM tecnicas")}
    n_ses = 0
    with con:
        for dia in _dias(inicio, hoy):
            avance = (dia - inicio).days / total
            plan = {0: "fuerza", 1: "bjj", 2: "fuerza", 3: "muaythai", 4: "fuerza", 5: "bjj", 6: "carrera"}[dia.weekday()]
            if dia == hoy and plan != "fuerza" or dia < hoy and r.random() < 0.12:
                continue
            if dia == hoy - timedelta(days=1):  # ayer estuvo enfermo (ver sensaciones): no entrenó
                continue
            hora = {"fuerza": "06:30", "bjj": "19:00", "muaythai": "19:30", "carrera": "07:00"}[plan]
            if plan == "carrera":
                km, ritmo = _carrera(avance, r)
                con.execute("INSERT INTO sesiones (fecha, hora, tipo, disciplina, duracion_s, sensaciones, notas,"
                            " guardada) VALUES (?, ?, 'cardio', 'carrera', ?, ?, ?, 1)",
                            (dia.isoformat(), hora, int(km * ritmo), r.randint(3, 5),
                             f"{_coma(km)} km a {int(ritmo) // 60}:{int(ritmo) % 60:02d} min/km"))
            elif plan == "fuerza":
                sid = con.execute("INSERT INTO sesiones (fecha, hora, tipo, disciplina, duracion_s, sensaciones, notas,"
                                  " guardada) VALUES (?, ?, 'fuerza', 'fuerza', ?, ?, ?, 1)",
                                  (dia.isoformat(), hora, r.randint(50, 75) * 60, r.randint(3, 5), None)).lastrowid
                elegidos = r.sample(FUERZA, 4)
                orden = 0
                for nombre, ini, fin, reps in elegidos:
                    carga = int(round((ini + (fin - ini) * avance) / 2500) * 2500)
                    for _ in range(3):
                        orden += 1
                        con.execute("INSERT INTO series (sesion_id, ejercicio_id, orden, reps, carga_g, rpe_x10,"
                                    " peso_corporal_g) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                    (sid, ej[nombre], orden, reps + r.choice((-1, 0, 0, 1)), carga,
                                     r.choice((70, 75, 80, 85)),
                                     _peso_g((dia - inicio).days, total, r) if nombre == "Dominadas" else None))
            else:
                sid = con.execute("INSERT INTO sesiones (fecha, hora, tipo, disciplina, duracion_s, sensaciones, notas,"
                                  " guardada) VALUES (?, ?, 'combate', ?, ?, ?, ?, 1)",
                                  (dia.isoformat(), hora, plan, r.randint(75, 95) * 60, r.randint(2, 5),
                                   r.choice((None, None, "Buen ritmo en los rounds", "Me costó la guardia")))
                                  ).lastrowid
                if r.random() < 0.15:
                    con.execute("UPDATE sesiones SET molestia_hombro = ? WHERE id = ?", (r.randint(1, 3), sid))
                bloques = [("tecnica", 20 * 60, None), ("drill", 15 * 60, None), ("randori", None, r.randint(4, 7))]
                for k, (tipo, dur, rounds) in enumerate(bloques, 1):
                    bid = con.execute("INSERT INTO combate_bloques (sesion_id, orden, tipo, duracion_s, rounds, rival)"
                                      " VALUES (?, ?, ?, ?, ?, ?)",
                                      (sid, k, tipo, dur, rounds,
                                       r.choice(("más pesado", "más liviano", "más técnico")) if tipo == "randori" else None)
                                      ).lastrowid
                    if plan == "bjj":
                        for nombre in r.sample(COMBATE_TECNICAS["bjj"], 2):
                            con.execute("INSERT INTO combate_tecnicas (bloque_id, tecnica_id, situacion, resultado)"
                                        " VALUES (?, ?, ?, ?)",
                                        (bid, tec.get(("bjj", nombre)),
                                         r.choice(("agarre", "entradas", "transiciones", "defensa")) if tipo != "tecnica" else None,
                                         "trabajada" if tipo != "randori" else r.choice(("funciono", "no_funciono"))))
            n_ses += 1
        # Pesajes semanales (lunes)
        for dia in _dias(inicio, hoy):
            if dia.weekday() == 0:
                con.execute("INSERT INTO pesajes (fecha, hora, peso_g, condicion) VALUES (?, '07:00', ?, 'ropa_interior')",
                            (dia.isoformat(), _peso_g((dia - inicio).days, total, r)))
        # Comidas de las últimas semanas
        momentos = [("desayuno", "07:30", ["Huevos con arepa y café", "Avena con fruta y yogur", "Calentado con huevo"]),
                    ("almuerzo", "12:45", ["Arroz, pollo y ensalada", "Frijoles, arroz y carne molida",
                                           "Pasta con atún y verduras"]),
                    ("media_tarde", "16:00", ["Fruta y proteína", "Yogur con granola"]),
                    ("cena", "20:30", ["Arepa con queso y huevo", "Pollo a la plancha con papa", "Wrap de carne"])]
        for dia in _dias(hoy - timedelta(weeks=SEMANAS_COMIDAS), hoy - timedelta(days=1)):
            if r.random() < 0.15:
                continue
            for momento, hora, opciones in momentos:
                if r.random() < 0.85:
                    con.execute("INSERT INTO comidas_registro (fecha, momento, hora, texto, segun_plan) VALUES (?, ?, ?, ?, ?)",
                                (dia.isoformat(), momento, hora, r.choice(opciones), int(r.random() < 0.7)))
            con.execute("INSERT INTO comidas_dia (fecha, agua_vasos) VALUES (?, ?)", (dia.isoformat(), r.randint(8, 15)))
        # Sensaciones de los últimos días, con dos días bajos (ayer y hace 9 días)
        for k in range(DIAS_SENSACIONES, 0, -1):
            dia = hoy - timedelta(days=k)
            bajo = k in (1, 9)
            con.execute("INSERT INTO sensaciones_dia (fecha, energia, animo, estres, sueno, motivacion, hambre, sintomas,"
                        " dolor, sin_entreno, notas) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (dia.isoformat(), 2 if bajo else r.randint(3, 5), r.randint(3, 5) if not bajo else 3,
                         4 if bajo else r.randint(1, 3), 2 if bajo else r.randint(3, 5), r.randint(3, 5),
                         r.randint(2, 4), json.dumps(["gripa"] if k == 1 else []),
                         "rodilla izquierda, 3 de 10" if k == 9 else None,
                         "enfermedad" if k == 1 else None, None))
        # Checklist de la competencia: dos ítems ya marcados
        for item in ("Documento de identidad", "Kimono azul"):
            con.execute("INSERT INTO checklist_competencia (competencia, item) VALUES (?, ?)",
                        (_competencia(hoy)[1].isoformat(), item))
        # Entradas de voz ya guardadas (sin audio)
        for k, texto in ((3, "Almorcé arroz con pollo y llevo ocho vasos de agua"),
                         (6, "Entrené BJJ hora y media, cinco rounds de randori")):
            dia = (hoy - timedelta(days=k)).isoformat()
            con.execute("INSERT INTO voz_entradas (estado, fecha_base, hora_base, rondas, registros, creada, actualizada)"
                        " VALUES ('guardada', ?, '21:00', ?, '[]', ?, ?)",
                        (dia, json.dumps([texto], ensure_ascii=False), f"{dia} 21:00:00", f"{dia} 21:02:00"))
        # Análisis anteriores (texto ficticio)
        for k, (tipo, params, texto) in enumerate(_analisis(hoy)):
            fin = datetime.combine(hoy - timedelta(days=7 * (len(_analisis(hoy)) - k)), datetime.min.time()).replace(hour=21)
            con.execute("INSERT INTO trabajos_ia (tipo, estado, creado, inicio, fin, parametros, resultado)"
                        " VALUES (?, 'listo', ?, ?, ?, ?, ?)",
                        (tipo, fin.isoformat(" ", "seconds"), fin.isoformat(timespec="seconds"),
                         (fin + timedelta(seconds=95)).isoformat(timespec="seconds"),
                         json.dumps(params, ensure_ascii=False), json.dumps({"texto": texto}, ensure_ascii=False)))
    # Tests con varias fechas
    evaluaciones = []
    for k, meses in enumerate((14, 10, 6, 2)):
        f = _meses_atras(hoy, meses) + timedelta(days=9)
        evaluaciones.append({
            "fecha": f.isoformat(), "cmj_cm": _coma(44.0 + 2.1 * k + r.uniform(-0.6, 0.6)),
            "dinamometria_dom_kg": _coma(42.0 + 1.6 * k), "dinamometria_nodom_kg": _coma(39.5 + 1.3 * k),
            "peso_kg": _coma(_peso_g((f - inicio).days, total, r) / 1000), "cintura_cm": str(88 - k),
            "caminata_6min_km": _coma(1.12 + 0.05 * k, 2),
            "vmp_ms": {"20": _coma(1.55 + 0.04 * k, 2), "40": _coma(1.18 + 0.05 * k, 2), "60": _coma(0.82 + 0.04 * k, 2)},
        })
    carga_tests.cargar(con, {"fuente": {"evaluador": "Centro Deportivo Altamira",
                                        "metodo_antropometria": "Antropometría ISAK (ficticia)"},
                             "evaluacion": evaluaciones}, "demo")
    # Fotos del cuerpo: siluetas en tres fechas
    for k, meses in enumerate((9, 5, 1)):
        f = (_meses_atras(hoy, meses) + timedelta(days=4)).isoformat()
        for pose in fx.POSES:
            fx.guardar(con, cfg.fotos_path, f, pose, _silueta(pose, 1.0 - 0.05 * k))
    return {"sesiones": n_ses}


def _carrera(avance: float, r: random.Random) -> tuple[float, float]:
    """Kilómetros y ritmo (s/km) de una carrera de domingo: de ~5 km a 6:20 a ~9 km a 5:35 a lo largo de la historia."""
    avance = min(1.0, max(0.0, avance))
    km = round(5 + 4 * avance + r.uniform(-0.8, 0.8), 1)
    ritmo = 380 - 45 * avance + r.uniform(-8, 8)
    return km, ritmo


def _analisis(hoy: date) -> list[tuple[str, dict, str]]:
    semana = lambda dias: (hoy - timedelta(days=dias)).strftime("%G-W%V")  # noqa: E731
    return [
        ("analisis_semana", {"semana": semana(21)},
         "## Tu semana\n\n- Cuatro sesiones: dos de fuerza, una de BJJ y una de muay thai.\n"
         "- El sueño promedió 6 h 50 min, un poco por debajo de las semanas anteriores.\n\n"
         "## Para la próxima\n\n- [I] Mantener la sentadilla en 85 kg una semana más antes de subir."),
        ("analisis_combate", {"n": 8, "disciplina": "bjj", "referente": ""},
         "## Tus últimos 8 entrenos de BJJ\n\n- La guardia cerrada es donde más funcionan tus técnicas.\n"
         "- El triángulo salió en 5 de 8 randoris.\n\n## Para trabajar\n\n- [I] Pasajes desde media guardia."),
        ("analisis_semana", {"semana": semana(7)},
         "## Tu semana\n\n- Cinco sesiones y 9.200 pasos de promedio.\n- El Body Battery cargó bien casi todas las "
         "noches, salvo el jueves.\n\n## Para la próxima\n\n- [I] Dejar un día completo de descanso antes del torneo."),
    ]


def _silueta(pose: str, ancho_rel: float) -> bytes:
    """Una silueta simple en PNG; ancho_rel < 1 la hace un poco más delgada (fotos más recientes)."""
    img = Image.new("RGB", (600, 900), (232, 226, 216))
    dib = ImageDraw.Draw(img)
    color = (92, 88, 84)
    cx = 300
    dib.ellipse((cx - 55, 70, cx + 55, 190), fill=color)                       # cabeza
    t = int(150 * ancho_rel) if pose != "perfil_derecho" else int(90 * ancho_rel)
    dib.rounded_rectangle((cx - t, 200, cx + t, 520), radius=60, fill=color)    # tronco
    if pose != "perfil_derecho":
        dib.rounded_rectangle((cx - t - 55, 215, cx - t - 5, 500), radius=25, fill=color)
        dib.rounded_rectangle((cx + t + 5, 215, cx + t + 55, 500), radius=25, fill=color)
        dib.rounded_rectangle((cx - t + 10, 510, cx - 10, 860), radius=30, fill=color)
        dib.rounded_rectangle((cx + 10, 510, cx + t - 10, 860), radius=30, fill=color)
    else:
        dib.rounded_rectangle((cx - 30, 215, cx + 25, 500), radius=25, fill=(80, 76, 72))
        dib.rounded_rectangle((cx - 45, 510, cx + 45, 860), radius=30, fill=color)
    salida = io.BytesIO()
    img.save(salida, "PNG")
    return salida.getvalue()


# ---------- Vault ficticio ----------

def _competencia(hoy: date) -> tuple[str, date]:
    torneo = hoy + timedelta(days=26)
    return f"Open de Grappling del Valle ({torneo.isoformat()})", torneo


def _vault(boveda: Path, r: random.Random, hoy: date) -> dict:
    t, n = boveda / "03_Training", boveda / "04_Nutrition"
    for carpeta in (t / "imports" / "garmin", t / "imports" / "polar", n, boveda / "02_Health",
                    boveda / "00_Inbox" / "comidas"):
        carpeta.mkdir(parents=True, exist_ok=True)
    cab = "---\ntype: training\nstatus: active\nconfidence: alta\n---\n\n"
    desde, hasta = hoy - timedelta(days=DIAS_RELOJ), hoy - timedelta(days=1)
    # Salud diaria de Garmin, con las 20 columnas
    filas = ["day,steps,resting_hr,stress_avg,body_battery_high,sleep_h,deep_min,light_min,rem_min,awake_min,"
             "sleep_score,hrv_ms,hrv_status,intensity_min,vigorous_min,body_battery_low,body_battery_charged,"
             "body_battery_drained,hrv_baseline_low,hrv_baseline_high"]
    for dia in _dias(desde, hasta):
        malo = dia == hasta or r.random() < 0.08
        sueno = r.uniform(5.2, 6.4) if malo else r.uniform(6.6, 8.1)
        profundo, rem, despierto = int(sueno * 60 * r.uniform(0.15, 0.22)), int(sueno * 60 * r.uniform(0.18, 0.24)), r.randint(8, 35)
        ligero = int(sueno * 60) - profundo - rem
        hrv = r.randint(52, 60) if malo else r.randint(62, 78)
        bb_max = r.randint(45, 62) if malo else r.randint(72, 96)
        bb_min = r.randint(5, 22)
        filas.append(",".join(str(x) for x in (
            dia.isoformat(), r.randint(5_500, 13_500), r.randint(48, 56), r.randint(22, 48), bb_max, f"{sueno:.2f}",
            profundo, ligero, rem, despierto, r.randint(58, 72) if malo else r.randint(74, 90), hrv,
            "UNBALANCED" if malo else "BALANCED", r.randint(15, 80), r.randint(0, 35), bb_min, bb_max - bb_min + r.randint(-5, 5),
            r.randint(55, 85), 60, 78)))
    (t / "imports" / "garmin" / f"{desde}_{hasta}_salud-diaria-garmin-mcp.csv").write_text("\n".join(filas) + "\n", encoding="utf-8")
    # Actividades de Garmin (fuerza y caminatas) y sesiones de Polar (combate)
    act = [cab + "# Garmin: actividades (ficticias)\n\n| Fecha | Día | Hora | Tipo | Duración (min) | En movimiento (min) |"
           " Distancia | FC media | FC máx | kcal |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    polar = ["date,start,sport_polar,duration_s,distance_m,hr_avg,hr_max,kcal,running_index,note"]
    for dia in _dias(desde, hasta - timedelta(days=1)):  # ayer estuvo enfermo: sin actividades
        dsem = DIAS_SEMANA[dia.weekday()]
        if dia.weekday() in (0, 2, 4):
            dur = r.uniform(52, 72)
            act.append(f"| {dia} | {dsem} | 06:3{r.randint(0, 9)} | Fuerza | {_coma(dur)} | {_coma(dur * 0.4)} | - | "
                       f"{r.randint(98, 118)} | {r.randint(140, 165)} | {r.randint(260, 420)} |")
        if dia.weekday() == 6:
            km, ritmo = _carrera(1 - (hasta - dia).days / (DIAS_RELOJ * 4), r)
            dur = km * ritmo / 60
            act.append(f"| {dia} | {dsem} | 07:0{r.randint(0, 9)} | Carrera | {_coma(dur)} | {_coma(dur * 0.97)} | "
                       f"{_coma(km, 2)} km | {r.randint(148, 162)} | {r.randint(172, 186)} | {int(km * 72)} |")
        elif r.random() < 0.45:
            dur = r.uniform(25, 50)
            act.append(f"| {dia} | {dsem} | 17:{r.randint(10, 59)} | Caminata | {_coma(dur)} | {_coma(dur * 0.95)} | "
                       f"{_coma(dur * 0.085, 2)} km | {r.randint(92, 112)} | {r.randint(115, 135)} | {r.randint(120, 260)} |")
        if dia.weekday() in (1, 5):
            polar.append(f"{dia},19:0{r.randint(0, 9)}:00,Judo,{r.randint(4500, 5600)},,{r.randint(128, 146)},"
                         f"{r.randint(168, 188)},{r.randint(650, 980)},,nota Polar: Bjj")
        if dia.weekday() == 3:
            polar.append(f"{dia},19:3{r.randint(0, 9)}:00,Kickboxing,{r.randint(4500, 5400)},,{r.randint(135, 150)},"
                         f"{r.randint(175, 192)},{r.randint(800, 1100)},,")
    (t / "imports" / "garmin" / f"{desde}_{hasta}_actividades-garmin-mcp.md").write_text("\n".join(act) + "\n", encoding="utf-8")
    (t / "imports" / "polar" / f"{desde}_{hasta}_sesiones-polar-mcp.csv").write_text("\n".join(polar) + "\n", encoding="utf-8")
    nombre, torneo = _competencia(hoy)
    (t / "objetivos-deportivos.md").write_text(
        cab + "# Objetivos deportivos\n\n"
        f"- [O] **Competir bien en el {nombre.split(' (')[0]}: {torneo}** · [U | alta]\n"
        "- [O] **Bajar a 77 kg sin corte de peso** antes del torneo · [U | alta]\n"
        "- [O] Correr 10 km en menos de 55 min antes de fin de año · [U | alta]\n"
        "- [O] Dormir 7 h o más al menos 5 noches por semana · [U | alta]\n"
        "- [O] Mínimo 8.000 pasos al día fuera del entrenamiento · [U | alta]\n", encoding="utf-8")
    (t / "perfil-deportivo.md").write_text(
        cab + "# Perfil deportivo\n\n- [H] James Restrepo, 29 años, 1,76 m. Jiu-jitsu desde hace 3 años (cinturón azul) "
        "y muay thai desde hace 1 año; corre los domingos · [U | alta]\n- [H] Entrena fuerza tres veces por semana con Andrés Pineda · [U | alta]\n",
        encoding="utf-8")
    (t / "cardio-y-zonas.md").write_text(
        cab + "# Cardio, frecuencia cardíaca y zonas\n\n## Zonas y umbrales\n\n"
        "- [M] Zonas de FC: Z1 98-118, Z2 118-137, Z3 137-157, Z4 157-176, Z5 176-194 lpm · [S01 | alta]\n", encoding="utf-8")
    (t / "marcas-y-pruebas.md").write_text(
        cab + "# Marcas y pruebas\n\n## Fuerza · [U | alta]\n\n| Fecha | Prueba | Resultado | Contexto |\n"
        "| --- | --- | --- | --- |\n"
        f"| {_meses_atras(hoy, 2)} | Sentadilla 5RM | 90 kg | Centro Deportivo Altamira |\n"
        f"| {_meses_atras(hoy, 2)} | Peso muerto 5RM | 120 kg | Idem |\n\n## Carrera · [U | alta]\n\n"
        "| Fecha | Prueba | Resultado | Contexto |\n| --- | --- | --- | --- |\n"
        f"| {_meses_atras(hoy, 9)} | 5 km | 29:40 | Carrera de barrio |\n"
        f"| {_meses_atras(hoy, 3)} | 10 km | 58:15 | Carrera 10K del Valle |\n", encoding="utf-8")
    plan = [f"| {torneo - timedelta(days=k)} | {'BJJ gi' if (torneo - timedelta(days=k)).weekday() in (1, 5) else '-'} | "
            f"{'Fuerza ligera' if (torneo - timedelta(days=k)).weekday() in (0, 2) and k > 6 else '-'} | - | "
            f"{'Pesaje en casa en la mañana' if k == 14 else ('Pesaje en casa en la mañana: meta 77,5 kg o menos' if k == 2 else ('Pesaje oficial 17:00 a 18:00' if k == 1 else '-'))} |"
            for k in range((torneo - hoy).days, 0, -1)]
    (t / "planificacion-semanal.md").write_text(
        cab + "# Planificación semanal\n\n"
        f"## Hacia el torneo {nombre} · [U | alta]\n\n"
        f"- [M] Torneo: {torneo} 08:00 · Coliseo del Valle · [S02 | alta]\n"
        f"- [H] Pesaje: {torneo - timedelta(days=1)} 17:00 a 18:00 · ropa interior · [S02 | alta]\n"
        "- [M] Límite: 77 kg · [S02 | alta]\n\n"
        "### Plan día por día\n\n| Fecha | Judo y BJJ | Fuerza | Cardio | Notas |\n| --- | --- | --- | --- | --- |\n"
        + "\n".join(plan) + f"\n| {torneo} | Torneo, 08:00 | - | - | - |\n\n"
        "### Guion de combate\n\n- [O] **Primer agarre:** cuello y manga, y buscar la guardia cerrada · [U | alta]\n"
        "- [O] **Antes de cada combate:** tres respiraciones largas · [U | alta]\n\n"
        "### Checklist del día\n\n- [O] Documento de identidad\n- [O] Kimono azul\n- [O] Rashguard\n"
        "- [O] Protector bucal\n- [O] Botella de agua y banano\n\n## Vigente\n\n- [H] Semana de carga normal\n",
        encoding="utf-8")
    nutri = "---\ntype: nutrition\nstatus: active\nconfidence: alta\n---\n\n"
    (n / f"plan-nutricional-{_meses_atras(hoy, 2):%Y-%m}.md").write_text(
        nutri + f"# Plan nutricional, {_meses_atras(hoy, 2):%Y-%m}\n\n"
        "- Profesional: Laura Méndez, nutricionista dietista · [S03 p.1]\n"
        f"- Evaluación: {_meses_atras(hoy, 2) + timedelta(days=9)} · Próximo control: en 4 semanas\n\n"
        "## Minuta patrón (intercambios, no gramos) · [S03 p.4]\n\n| Momento | Distribución |\n| --- | --- |\n"
        "| Desayuno | 2 carbohidrato, 3 proteína, 1 grasa, 1 fruta |\n| Media mañana | 1 fruta |\n"
        "| Almuerzo | 2 carbohidrato, 1 carne, 1 grasa, 2 verdura |\n| Media tarde | 1 fruta, 1 proteína |\n"
        "| Cena | 1 carbohidrato, 1 carne, 1 grasa, 1 verdura |\n\n"
        "## Opciones por comida · [S03 p.5]\n\n- **Desayuno:** 3 huevos y 1 arepa mediana.\n"
        "- **Almuerzo:** arroz, 150 g de pollo en crudo y ensalada.\n\n"
        "## Actividad e hidratación · [S03 p.3]\n\n- 8.000 pasos mínimo al día sin contar el entrenamiento\n"
        "- 3,0 L mínimo de líquidos al día\n", encoding="utf-8")
    f_antro = _meses_atras(hoy, 2) + timedelta(days=9)
    (n / "composicion-corporal.md").write_text(
        nutri + "# Composición corporal\n\n## Peso y composición\n\n"
        "| Fecha | Peso | IMC | % graso | Otros | Método / origen | Fuente | Conf. |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        f"| {_meses_atras(hoy, 14) + timedelta(days=9)} | 80,8 kg | 26,08 | 15,9 % | - | Antropometría ISAK, Centro Deportivo Altamira | S01 | alta |\n"
        f"| {f_antro} | 78,1 kg | 25,21 | 13,4 % | Masa muscular 44,9 % | Antropometría ISAK, Centro Deportivo Altamira | S01 | alta |\n\n"
        f"## Antropometría del {f_antro} · [S01 | alta]\n\nTotales: **suma 6 pliegues 72,0 mm · suma 8 pliegues 98,0 mm**\n\n"
        "Perímetros:\n\n| Medida | cm |\n| --- | --- |\n| Cintura | 84 |\n| Brazo relajado | 33,5 |\n", encoding="utf-8")
    (boveda / "02_Health" / "sueno-y-recuperacion.md").write_text(
        "---\ntype: health\n---\n\n# Sueño y recuperación\n\n- [H] Duerme mejor sin pantallas después de las 22:00 · [U | media]\n",
        encoding="utf-8")
    (boveda / "02_Health" / "rodilla-izquierda.md").write_text(
        "---\ntype: health\n---\n\n# Rodilla izquierda\n\n- [H] Molestia leve al girar en la guardia; la revisa Camilo Duarte,"
        " fisioterapeuta · [U | media]\n", encoding="utf-8")
    (boveda / "00_Inbox" / "comidas" / "plantilla-dia.md").write_text(
        "# Comidas AAAA-MM-DD\n\n| Hora | Momento | Qué comí y cuánto |\n| --- | --- | --- |\n| | Desayuno | |\n",
        encoding="utf-8")
    return {"dias_reloj": DIAS_RELOJ}


# ---------- Entrada ----------

def generar(cfg: Config, hoy: date, semilla: int = 2026) -> dict:
    """Borra y recrea la base, el vault, las fotos y los exports de la demo. Exige una configuración de demo válida."""
    if not cfg.demo:
        raise RuntimeError("La semilla de la demo solo corre en modo demo (BRAIN_DEMO=1).")
    validar_demo(cfg)
    for ruta in (cfg.vault_path, cfg.fotos_path, cfg.exports_path):
        _borrar(ruta)
        ruta.mkdir(parents=True)
    for sufijo in ("", "-wal", "-shm"):
        _borrar(Path(str(cfg.db_path) + sufijo))
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.codex_home).mkdir(parents=True, exist_ok=True)
    r = random.Random(semilla)
    con = conectar(cfg.db_path)
    try:
        migrar(con)
        resumen = {"fecha": hoy.isoformat(), "semilla": semilla}
        resumen |= _finanzas(con, random.Random(r.random()), hoy)
        resumen |= _rendimiento(con, random.Random(r.random()), hoy, cfg)
        resumen |= _vault(cfg.vault_path, random.Random(r.random()), hoy)
    finally:
        con.close()
    return resumen


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m app.demo", description="Regenera la demo con datos ficticios.")
    p.add_argument("--fecha", help="AAAA-MM-DD; por defecto hoy en America/Bogota")
    p.add_argument("--semilla", type=int, default=2026)
    args = p.parse_args(argv)
    if not es_demo():
        print("La semilla de la demo solo corre con BRAIN_DEMO=1, desde el worktree de la demo.")
        return 2
    hoy = date.fromisoformat(args.fecha) if args.fecha else datetime.now(ZoneInfo("America/Bogota")).date()
    resumen = generar(leer_config(), hoy, args.semilla)
    print("Demo regenerada: " + ", ".join(f"{k} {v}" for k, v in resumen.items()))
    return 0
