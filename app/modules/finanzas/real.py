"""Datos de v2: lo real (pagos y gastos), fondos, eventos, escenario, indicadores y revisión."""

import sqlite3
from datetime import date

from app.core.dinero import a_cop, div_redondeo, ea_a_mensual_ppm, mensual_a_ea_ppm, porcentaje

from . import consultas as q
from . import futuro as fu
from . import logica
from .consultas import ErrorDatos
from .logica import Linea


def _f(t: str | None) -> date | None:
    return date.fromisoformat(t) if t else None


def _fecha_valida(fecha: str) -> str:
    try:
        date.fromisoformat(fecha)
    except (TypeError, ValueError):
        raise ErrorDatos("La fecha no es válida.") from None
    return fecha


# ---------- Pagos reales de líneas ----------

def marcar_pago(con: sqlite3.Connection, linea_id: int, fecha: str, monto: int | None = None) -> None:
    linea = con.execute("SELECT * FROM quincena_lineas WHERE id = ?", (linea_id,)).fetchone()
    if not linea:
        raise ErrorDatos("Esa línea no existe.")
    monto = linea["monto"] if monto is None else monto
    if monto < 0:
        raise ErrorDatos("El monto no puede ser negativo.")
    with con:
        con.execute("INSERT INTO pagos (linea_id, fecha, monto) VALUES (?, ?, ?)"
                    " ON CONFLICT(linea_id) DO UPDATE SET fecha = excluded.fecha, monto = excluded.monto",
                    (linea_id, _fecha_valida(fecha), monto))


def quitar_pago(con: sqlite3.Connection, linea_id: int) -> None:
    with con:
        con.execute("DELETE FROM pagos WHERE linea_id = ?", (linea_id,))


def linea(con: sqlite3.Connection, linea_id: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT l.*, b.nombre AS bolsillo, b.tipo AS tipo, d.nombre AS deuda, f.nombre AS fondo,"
        " p.monto AS real, p.fecha AS pagada FROM quincena_lineas l"
        " JOIN bolsillos b ON b.id = l.bolsillo_id LEFT JOIN deudas d ON d.id = l.deuda_id"
        " LEFT JOIN fondos f ON f.id = l.fondo_id LEFT JOIN pagos p ON p.linea_id = l.id WHERE l.id = ?",
        (linea_id,)).fetchone()


# ---------- Gasto rápido ----------

def categorias(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM categorias ORDER BY orden, id").fetchall()


def crear_gasto(con: sqlite3.Connection, fecha: str, monto: int, bolsillo_id: int,
                categoria_id: int | None, nota: str = "") -> int:
    if monto <= 0:
        raise ErrorDatos("El monto debe ser mayor que cero.")
    if not con.execute("SELECT 1 FROM bolsillos WHERE id = ?", (bolsillo_id,)).fetchone():
        raise ErrorDatos("Elige un bolsillo.")
    if categoria_id and not con.execute("SELECT 1 FROM categorias WHERE id = ?", (categoria_id,)).fetchone():
        raise ErrorDatos("Elige una categoría.")
    with con:
        return con.execute(
            "INSERT INTO gastos (fecha, monto, bolsillo_id, categoria_id, nota) VALUES (?, ?, ?, ?, ?)",
            (_fecha_valida(fecha), monto, bolsillo_id, categoria_id, nota.strip())).lastrowid


def borrar_gasto(con: sqlite3.Connection, gasto_id: int) -> None:
    with con:
        con.execute("DELETE FROM gastos WHERE id = ?", (gasto_id,))


def gastos(con: sqlite3.Connection, desde: str, hasta: str) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT g.*, b.nombre AS bolsillo, b.tipo AS tipo, c.nombre AS categoria FROM gastos g"
        " JOIN bolsillos b ON b.id = g.bolsillo_id LEFT JOIN categorias c ON c.id = g.categoria_id"
        " WHERE g.fecha BETWEEN ? AND ? ORDER BY g.fecha DESC, g.id DESC", (desde, hasta)).fetchall()


# ---------- Plan vs real ----------

def periodo_de(fecha: date) -> tuple[date, date]:
    """Desde la fecha de la quincena hasta el día antes del siguiente día de pago."""
    siguiente = logica.proximo_dia_pago(fecha, incluir_hoy=False)
    return fecha, date.fromordinal(siguiente.toordinal() - 1)


def plan_vs_real(con: sqlite3.Connection, qid: int) -> list[dict]:
    """Por bolsillo: planeado, real (pagos + gastos rápidos del periodo) y diferencia.
    Real None = sin registrar. Los gastos rápidos solo se cuentan en quincenas regulares.
    Diferencia: si hay gastos rápidos, todo lo planeado menos lo real (los gastos consumen el
    bolsillo); si solo hay líneas marcadas, la suma de (planeado menos real) de esas líneas."""
    qu = q.quincena(con, qid)
    lineas = q.lineas_quincena(con, qid)
    desde, hasta = periodo_de(date.fromisoformat(qu["fecha"]))
    gasto_por_b: dict[int, int] = {}
    if qu["tipo"] == "quincena":
        for g in gastos(con, desde.isoformat(), hasta.isoformat()):
            gasto_por_b[g["bolsillo_id"]] = gasto_por_b.get(g["bolsillo_id"], 0) + g["monto"]
    salida: dict[int, dict] = {}
    for l in lineas:
        b = salida.setdefault(l["bolsillo_id"], {"id": l["bolsillo_id"], "nombre": l["bolsillo"], "tipo": l["tipo"],
                                                 "planeado": 0, "real": None, "lineas": 0, "marcadas": 0,
                                                 "dif_marcadas": 0})
        b["planeado"] += l["monto"]
        b["lineas"] += 1
        if l["real"] is not None:
            b["real"] = (b["real"] or 0) + l["real"]
            b["marcadas"] += 1
            b["dif_marcadas"] += l["monto"] - l["real"]
    for bid, monto in gasto_por_b.items():
        if bid not in salida:
            fila = con.execute("SELECT nombre, tipo FROM bolsillos WHERE id = ?", (bid,)).fetchone()
            salida[bid] = {"id": bid, "nombre": fila["nombre"], "tipo": fila["tipo"], "planeado": 0, "real": None,
                           "lineas": 0, "marcadas": 0, "dif_marcadas": 0}
        salida[bid]["real"] = (salida[bid]["real"] or 0) + monto
    for b in salida.values():
        b["gastos"] = gasto_por_b.get(b["id"], 0)
        if b["real"] is None:
            b["diferencia"] = None
        elif b["gastos"]:
            b["diferencia"] = b["planeado"] - b["real"]
        else:
            b["diferencia"] = b["dif_marcadas"]
    return list(salida.values())


# ---------- Fondos de previsión ----------

def fondos(con: sqlite3.Connection, hoy: date) -> list[dict]:
    salida = []
    for f in con.execute(
        "SELECT f.*, b.nombre AS bolsillo, b.tipo AS tipo_bolsillo,"
        " COALESCE((SELECT SUM(CASE tipo WHEN 'aporte' THEN monto ELSE -monto END)"
        "           FROM fondo_movimientos WHERE fondo_id = f.id), 0) AS acumulado"
        " FROM fondos f JOIN bolsillos b ON b.id = f.bolsillo_id ORDER BY f.orden, f.id"
    ):
        est = fu.EstadoFondo(f["objetivo"], f["acumulado"], _f(f["fecha_objetivo"]))
        fijo = f["aporte_mensual"] > 0
        salida.append({"f": f, "estado": est, "aporte_fijo": fijo,
                       "provision": 0 if fijo else est.provision(hoy), "quincenas": est.quincenas(hoy),
                       "pct": min(100, porcentaje(max(0, f["acumulado"]), f["objetivo"])) if f["objetivo"] else 0})
    return salida


def fondo(con: sqlite3.Connection, fondo_id: int) -> sqlite3.Row:
    fila = con.execute("SELECT * FROM fondos WHERE id = ?", (fondo_id,)).fetchone()
    if not fila:
        raise ErrorDatos("Ese fondo no existe.")
    return fila


def guardar_fondo(con: sqlite3.Connection, nombre: str, objetivo: int, fecha_objetivo: str | None,
                  cada_meses: int | None, bolsillo_id: int, estimado: bool, fondo_id: int | None = None,
                  aporte_mensual: int = 0, aporte_proximo: int | None = None) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ErrorDatos("Escribe un nombre para el fondo.")
    if objetivo < 0 or aporte_mensual < 0:
        raise ErrorDatos("Los montos no pueden ser negativos.")
    if fecha_objetivo:
        _fecha_valida(fecha_objetivo)
    if cada_meses is not None and cada_meses <= 0:
        raise ErrorDatos("Cada cuántos meses debe ser mayor que cero.")
    if not con.execute("SELECT 1 FROM bolsillos WHERE id = ?", (bolsillo_id,)).fetchone():
        raise ErrorDatos("Elige un bolsillo.")
    otro = con.execute("SELECT id FROM fondos WHERE nombre = ?", (nombre,)).fetchone()
    if otro and otro["id"] != fondo_id:
        raise ErrorDatos(f"Ya existe un fondo llamado «{nombre}».")
    vals = (nombre, objetivo, fecha_objetivo or None, cada_meses, bolsillo_id, int(estimado), aporte_mensual,
            aporte_proximo)
    with con:
        if fondo_id:
            con.execute("UPDATE fondos SET nombre = ?, objetivo = ?, fecha_objetivo = ?, cada_meses = ?,"
                        " bolsillo_id = ?, estimado = ?, aporte_mensual = ?, aporte_proximo = ? WHERE id = ?",
                        (*vals, fondo_id))
            return fondo_id
        orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM fondos").fetchone()[0]
        return con.execute("INSERT INTO fondos (nombre, objetivo, fecha_objetivo, cada_meses, bolsillo_id, estimado,"
                           " aporte_mensual, aporte_proximo, orden) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (*vals, orden)).lastrowid


def usar_fondo(con: sqlite3.Connection, fondo_id: int, fecha: str, monto: int, nota: str = "") -> None:
    """Registra el uso; si el fondo se repite, su fecha objetivo pasa al siguiente ciclo."""
    f = fondo(con, fondo_id)
    if monto <= 0:
        raise ErrorDatos("El monto debe ser mayor que cero.")
    _fecha_valida(fecha)
    with con:
        con.execute("INSERT INTO fondo_movimientos (fondo_id, fecha, tipo, monto, nota) VALUES (?, ?, 'uso', ?, ?)",
                    (fondo_id, fecha, monto, nota))
        if f["cada_meses"] and f["fecha_objetivo"]:
            nueva = fu.sumar_meses(date.fromisoformat(f["fecha_objetivo"]), f["cada_meses"])
            con.execute("UPDATE fondos SET fecha_objetivo = ? WHERE id = ?", (nueva.isoformat(), fondo_id))
        if f["aporte_mensual"] and f["aporte_proximo"] is not None:
            # Natillera: al devolverse, el nuevo ciclo arranca con el aporte nuevo.
            con.execute("UPDATE fondos SET aporte_mensual = aporte_proximo, aporte_proximo = NULL WHERE id = ?",
                        (fondo_id,))


def lineas_fondo(con: sqlite3.Connection, fecha: date) -> list[Linea]:
    """Líneas automáticas de provisión para una quincena en esa fecha."""
    salida = []
    for x in fondos(con, fecha):
        if x["f"]["aporte_mensual"]:
            continue  # aporte fijo: lo pone su línea de plantilla
        p = x["estado"].provision(fecha)
        if p > 0:
            salida.append(Linea(f"Fondo {x['f']['nombre']}", x["f"]["bolsillo_id"], p, "fondo", fondo_id=x["f"]["id"]))
    return salida


# ---------- Eventos y escenario ----------

def eventos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT e.*, d.nombre AS deuda, f.nombre AS fondo FROM eventos e LEFT JOIN deudas d ON d.id = e.deuda_id"
        " LEFT JOIN fondos f ON f.id = e.fondo_id ORDER BY e.fecha, e.id").fetchall()


def guardar_evento(con: sqlite3.Connection, nombre: str, fecha: str, tipo: str, monto: int | None,
                   estimado: bool, deuda_id: int | None, fondo_id: int | None, escenario: str = "",
                   nota: str = "", evento_id: int | None = None) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ErrorDatos("Escribe un nombre para el evento.")
    if tipo not in ("ingreso", "gasto", "traslado"):
        raise ErrorDatos("Elige si es ingreso, gasto o traslado a un fondo.")
    if tipo == "traslado" and not fondo_id:
        raise ErrorDatos("Un traslado necesita el fondo de destino.")
    if monto is not None and monto < 0:
        raise ErrorDatos("El monto no puede ser negativo.")
    if deuda_id and fondo_id:
        raise ErrorDatos("Elige un solo destino: una deuda o un fondo.")
    vals = (nombre, _fecha_valida(fecha), tipo, monto, int(estimado), deuda_id, fondo_id, escenario, nota)
    with con:
        if evento_id:
            con.execute("UPDATE eventos SET nombre = ?, fecha = ?, tipo = ?, monto = ?, estimado = ?, deuda_id = ?,"
                        " fondo_id = ?, escenario = ?, nota = ? WHERE id = ?", (*vals, evento_id))
            return evento_id
        return con.execute("INSERT INTO eventos (nombre, fecha, tipo, monto, estimado, deuda_id, fondo_id, escenario, nota)"
                           " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", vals).lastrowid


def borrar_evento(con: sqlite3.Connection, evento_id: int) -> None:
    with con:
        con.execute("DELETE FROM eventos WHERE id = ?", (evento_id,))


CAMPOS_ESCENARIO = ("neto_quincena", "gasto_basico", "tarjeta_mes", "libre", "ahorro_mensual", "incluir_extra",
                    "estrategia", "meses", "meta_m4", "incapacidad_activa", "incapacidad_inicio",
                    "incapacidad_meses", "incapacidad_pct_ppm", "sobrante_a_ahorro", "retencion_ppm",
                    "topar_en_m4", "inversion_ea_ppm")


def escenario(con: sqlite3.Connection) -> dict:
    return dict(con.execute("SELECT * FROM escenario WHERE id = 1").fetchone())


def guardar_escenario(con: sqlite3.Connection, valores: dict) -> None:
    e = escenario(con)
    e.update({k: v for k, v in valores.items() if k in CAMPOS_ESCENARIO})
    if e["estrategia"] not in ("avalancha", "bola"):
        raise ErrorDatos("Elige avalancha o bola de nieve.")
    if e["meses"] not in (12, 24):
        raise ErrorDatos("La proyección es a 12 o 24 meses.")
    if any(e[k] < 0 for k in ("neto_quincena", "gasto_basico", "tarjeta_mes", "libre", "ahorro_mensual", "meta_m4")):
        raise ErrorDatos("Los montos no pueden ser negativos.")
    if e["incapacidad_activa"] and len(e["incapacidad_inicio"]) != 7:
        raise ErrorDatos("Elige el mes de inicio de la incapacidad.")
    with con:
        con.execute("UPDATE escenario SET " + ", ".join(f"{k} = ?" for k in CAMPOS_ESCENARIO) + " WHERE id = 1",
                    [e[k] for k in CAMPOS_ESCENARIO])


def actualizar_deuda(con: sqlite3.Connection, deuda_id: int, tasa_ppm: int | None, cuota: int,
                     prepagar: bool | None = None) -> None:
    d = q.deuda(con, deuda_id)
    if (tasa_ppm is not None and tasa_ppm < 0) or cuota < 0:
        raise ErrorDatos("La tasa y la cuota no pueden ser negativas.")
    prepagar = bool(d["prepagar"]) if prepagar is None else prepagar
    with con:
        con.execute("UPDATE deudas SET tasa_mensual_ppm = ?, cuota_mensual = ?, prepagar = ? WHERE id = ?",
                    (tasa_ppm, cuota, int(prepagar), deuda_id))


# ---------- Proyección desde la base ----------

def entrada_proyeccion(con: sqlite3.Connection, hoy: date, cambios: dict | None = None) -> tuple[fu.Entrada, dict, list[str]]:
    esc = escenario(con)
    if cambios:
        esc.update({k: v for k, v in cambios.items() if k in CAMPOS_ESCENARIO})
    avisos = []
    trm = q.ultima_trm(con)
    deudas = []
    for d in q.deudas(con):
        if d["saldo"] <= 0:
            continue
        if d["moneda"] == "USD" and not trm:
            avisos.append(f"{d['nombre']}: falta una TRM para convertirla a COP.")
            continue
        deudas.append(fu.DeudaSim(d["nombre"], a_cop(d["saldo"], d["moneda"], trm), d["tasa_mensual_ppm"],
                                  d["cuota_mensual"], prepagar=bool(d["prepagar"])))
    fondos_sim = [fu.FondoSim(x["f"]["nombre"], x["f"]["objetivo"], max(0, x["f"]["acumulado"]),
                              _f(x["f"]["fecha_objetivo"]), x["f"]["cada_meses"], x["f"]["aporte_mensual"],
                              x["f"]["aporte_proximo"])
                  for x in fondos(con, hoy)]
    evs = [fu.EventoSim(e["nombre"], date.fromisoformat(e["fecha"]), e["tipo"], e["monto"], bool(e["estimado"]),
                        e["deuda"], e["fondo"])
           for e in eventos(con) if date.fromisoformat(e["fecha"]) >= date(hoy.year, hoy.month, 1)
           and (e["escenario"] != "extra" or esc["incluir_extra"])]
    metas = q.avance_metas(con)
    emergencia = metas[0]["avance"].actual if metas else 0
    foto = q.ultima_foto(con)
    activos = q.patrimonio_foto(con, foto).activos if foto else 0
    rend_em, rend_ot = rendimientos_proyeccion(con, foto, metas)
    neto = esc["neto_quincena"]
    if not neto:
        ult = con.execute("SELECT neto FROM quincenas WHERE tipo = 'quincena' ORDER BY fecha DESC LIMIT 1").fetchone()
        neto = ult["neto"] if ult else 0
        if not neto:
            avisos.append("Falta el neto por quincena en el escenario.")
    if not esc["gasto_basico"]:
        avisos.append("Falta el gasto básico mensual en el escenario.")
    inc = (esc["incapacidad_inicio"], esc["incapacidad_meses"], esc["incapacidad_pct_ppm"]) if esc["incapacidad_activa"] else None
    entrada = fu.Entrada(
        hoy=hoy, meses=esc["meses"], neto_quincena=neto, gasto_basico=esc["gasto_basico"], tarjeta_mes=esc["tarjeta_mes"],
        libre=esc["libre"], ahorro_mensual=esc["ahorro_mensual"], estrategia=esc["estrategia"], deudas=deudas,
        fondos=fondos_sim, eventos=evs, emergencia=emergencia, otros_activos=activos - emergencia,
        meta1=metas[0]["meta"]["objetivo"] if metas else 0, meta_m4=esc["meta_m4"], incapacidad=inc,
        sobrante_a_ahorro=bool(esc["sobrante_a_ahorro"]),
        rend_emergencia_ppm=rend_em, rend_otros_ppm=rend_ot, retencion_ppm=esc["retencion_ppm"],
        tope_emergencia=esc["meta_m4"] if esc["topar_en_m4"] else 0,
        rend_inversion_ppm=ea_a_mensual_ppm(esc["inversion_ea_ppm"]) if esc["inversion_ea_ppm"] else 0,
    )
    return entrada, esc, avisos


# ---------- Rendimiento de cuentas ----------

def guardar_rendimiento(con: sqlite3.Connection, cuenta_id: int, ea_ppm: int | None, nota: str) -> None:
    if not con.execute("SELECT 1 FROM cuentas WHERE id = ?", (cuenta_id,)).fetchone():
        raise ErrorDatos("Esa cuenta no existe.")
    if ea_ppm is not None and ea_ppm < 0:
        raise ErrorDatos("El rendimiento no puede ser negativo.")
    with con:
        con.execute("UPDATE cuentas SET rendimiento_ea_ppm = ?, rendimiento_nota = ? WHERE id = ?",
                    (ea_ppm, nota.strip(), cuenta_id))


def _ponderado(saldos: dict[int, int], tasas: dict[int, int | None], ids: set[int]) -> int:
    """Rendimiento mensual (ppm) promedio ponderado por saldo; las cuentas sin dato cuentan como 0."""
    total = sum(max(0, saldos.get(i, 0)) for i in ids)
    if total <= 0:
        return 0
    suma = sum(max(0, saldos.get(i, 0)) * ea_a_mensual_ppm(tasas[i]) for i in ids if tasas.get(i))
    return suma // total


def rendimientos_proyeccion(con: sqlite3.Connection, foto, metas) -> tuple[int, int]:
    if not foto:
        return 0, 0
    saldos = {r["id"]: r["saldo"] for r in q.saldos_foto(con, foto["id"])}
    tasas = {c["id"]: c["rendimiento_ea_ppm"] for c in q.cuentas(con)}
    ids_meta = {r[0] for r in con.execute("SELECT cuenta_id FROM meta_cuentas WHERE meta_id = ?",
                                          (metas[0]["meta"]["id"],))} if metas else set()
    return _ponderado(saldos, tasas, ids_meta), _ponderado(saldos, tasas, set(saldos) - ids_meta)


def comparacion_rendimiento(con: sqlite3.Connection) -> dict:
    """Rendimiento E.A. de cada cuenta (bruto y neto de retención) frente al costo E.A. de cada deuda.
    La comparación usa el neto."""
    ret = escenario(con)["retencion_ppm"]
    cuentas = [{"nombre": c["nombre"], "ea_bruto_ppm": c["rendimiento_ea_ppm"], "nota": c["rendimiento_nota"],
                "ea_ppm": (c["rendimiento_ea_ppm"] - div_redondeo(c["rendimiento_ea_ppm"] * ret, 1_000_000))
                if c["rendimiento_ea_ppm"] else c["rendimiento_ea_ppm"]}
               for c in q.cuentas(con)]
    # La E.A. que sale de una tasa mensual guardada se redondea a centésimas de punto (7,2004 % -> 7,2 %).
    deudas = [{"nombre": d["nombre"],
               "ea_ppm": div_redondeo(mensual_a_ea_ppm(d["tasa_mensual_ppm"]), 100) * 100 if d["tasa_mensual_ppm"] else None,
               "prepagar": bool(d["prepagar"])}
              for d in q.deudas(con) if d["saldo"] > 0]
    frases = []
    con_tasa = [c for c in cuentas if c["ea_ppm"]]
    mejor = max(con_tasa, key=lambda c: c["ea_ppm"]) if con_tasa else None
    for c in [mejor] if mejor else []:
        for d in deudas:
            if d["ea_ppm"] is None:
                continue
            dif = c["ea_ppm"] - d["ea_ppm"]
            if dif > 0:
                frases.append({"cuenta": c["nombre"], "deuda": d["nombre"], "dif_ppm": dif,
                               "texto": f"Ahorrar en {c['nombre']} rinde más de lo que cuesta {d['nombre']}"})
            else:
                frases.append({"cuenta": c["nombre"], "deuda": d["nombre"], "dif_ppm": dif,
                               "texto": f"Prepagar {d['nombre']} ahorra más de lo que rinde {c['nombre']}"})
    return {"cuentas": cuentas, "deudas": deudas, "frases": frases, "retencion_ppm": ret}


# ---------- Indicadores del mes ----------

def indicadores(con: sqlite3.Connection, hoy: date) -> dict:
    mes = hoy.strftime("%Y-%m")
    esc = escenario(con)
    qs = con.execute("SELECT * FROM quincenas WHERE substr(fecha, 1, 7) = ?", (mes,)).fetchall()
    ingreso = sum(x["neto"] for x in qs)
    ahorro = tope_libre = real_libre = 0
    hay_libre = False
    for x in qs:
        for l in q.lineas_quincena(con, x["id"]):
            if l["tipo"] == "ahorro" or l["fondo_id"]:
                ahorro += l["monto"]
            if l["tipo"] == "libre":
                tope_libre += l["monto"]
                if l["real"] is not None:
                    real_libre += l["real"]
                    hay_libre = True
    for g in gastos(con, f"{mes}-01", f"{mes}-31"):
        if g["tipo"] == "libre":
            real_libre += g["monto"]
            hay_libre = True
    pagos_deuda = sum(
        (m["costo_cop"] if m["costo_cop"] is not None else m["monto"])
        for m in con.execute("SELECT * FROM movimientos_deuda WHERE tipo = 'abono' AND substr(fecha, 1, 7) = ?", (mes,))
    )
    metas = q.avance_metas(con)
    fondo_emergencia = metas[0]["avance"].actual if metas else None
    return {
        "mes": mes,
        "ingreso": ingreso,
        "ahorro": ahorro,
        "tasa_ahorro": porcentaje(ahorro, ingreso) if ingreso else None,
        "fondo_emergencia": fondo_emergencia,
        "gasto_basico": esc["gasto_basico"],
        "colchon_decimas": div_redondeo(fondo_emergencia * 10, esc["gasto_basico"]) if fondo_emergencia is not None and esc["gasto_basico"] else None,
        "pagos_deuda": pagos_deuda,
        "deuda_ingreso": porcentaje(pagos_deuda, ingreso) if ingreso else None,
        "tope_libre": tope_libre,
        "real_libre": real_libre if hay_libre else None,
    }


# ---------- Revisión mensual ----------

PREGUNTAS = {
    "distinto": "¿Qué salió distinto al plan este mes?",
    "inesperado": "¿Qué gasto no esperabas?",
    "ajustar": "¿Qué fondo o meta quieres ajustar?",
    "plantillas": "¿Qué cambiarías en las plantillas?",
    "sensacion": "¿Cómo te sentiste con la plata este mes? (1 mal, 5 muy bien)",
}


def revision(con: sqlite3.Connection, mes: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM revisiones WHERE mes = ?", (mes,)).fetchone()


def guardar_revision(con: sqlite3.Connection, mes: str, respuestas: dict) -> None:
    if len(mes) != 7 or mes[4] != "-":
        raise ErrorDatos("El mes debe tener la forma AAAA-MM.")
    sens = respuestas.get("sensacion")
    if sens is not None and not (1 <= sens <= 5):
        raise ErrorDatos("Elige un valor del 1 al 5.")
    vals = [str(respuestas.get(k, "") or "").strip() for k in ("distinto", "inesperado", "ajustar", "plantillas")]
    with con:
        con.execute(
            "INSERT INTO revisiones (mes, distinto, inesperado, ajustar, plantillas, sensacion, actualizada)"
            " VALUES (?, ?, ?, ?, ?, ?, datetime('now')) ON CONFLICT(mes) DO UPDATE SET distinto = excluded.distinto,"
            " inesperado = excluded.inesperado, ajustar = excluded.ajustar, plantillas = excluded.plantillas,"
            " sensacion = excluded.sensacion, actualizada = excluded.actualizada", (mes, *vals, sens))
