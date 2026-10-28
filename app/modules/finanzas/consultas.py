"""Acceso a datos con SQL a mano. Las operaciones que mueven plata van en una transacción."""

import sqlite3
from datetime import date

from app.core.dinero import cop_a_usd, usd_a_cop

from . import logica
from .logica import Linea, RepartoInvalido


class ErrorDatos(ValueError):
    pass


def _f(texto: str) -> date:
    return date.fromisoformat(texto)


# ---------- Bolsillos ----------

def bolsillos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM bolsillos ORDER BY orden, id").fetchall()


def crear_bolsillo(con: sqlite3.Connection, nombre: str, tipo: str) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ErrorDatos("Escribe un nombre para el bolsillo.")
    if tipo not in logica.TIPOS_BOLSILLO:
        raise ErrorDatos("Elige un tipo de bolsillo.")
    if con.execute("SELECT 1 FROM bolsillos WHERE nombre = ?", (nombre,)).fetchone():
        raise ErrorDatos(f"Ya existe un bolsillo llamado «{nombre}».")
    orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM bolsillos").fetchone()[0]
    with con:
        cur = con.execute(
            "INSERT INTO bolsillos (nombre, tipo, orden) VALUES (?, ?, ?)", (nombre, tipo, orden)
        )
    return cur.lastrowid


# ---------- Deudas ----------

def deudas(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM deudas ORDER BY orden, id").fetchall()


def deuda(con: sqlite3.Connection, deuda_id: int) -> sqlite3.Row:
    fila = con.execute("SELECT * FROM deudas WHERE id = ?", (deuda_id,)).fetchone()
    if not fila:
        raise ErrorDatos("Esa deuda no existe.")
    return fila


def crear_deuda(con: sqlite3.Connection, nombre: str, moneda: str, saldo: int) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ErrorDatos("Escribe un nombre para la deuda.")
    if moneda not in ("COP", "USD"):
        raise ErrorDatos("La moneda debe ser COP o USD.")
    if saldo < 0:
        raise ErrorDatos("El saldo no puede ser negativo.")
    if con.execute("SELECT 1 FROM deudas WHERE nombre = ?", (nombre,)).fetchone():
        raise ErrorDatos(f"Ya existe una deuda llamada «{nombre}».")
    orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM deudas").fetchone()[0]
    with con:
        cur = con.execute(
            "INSERT INTO deudas (nombre, moneda, saldo, orden) VALUES (?, ?, ?, ?)",
            (nombre, moneda, saldo, orden),
        )
    return cur.lastrowid


def _insertar_abono(con, d, fecha: str, monto: int, trm: int | None, costo_cop: int | None,
                    quincena_id: int | None, nota: str, afecta_saldo: bool = True) -> int:
    if monto <= 0:
        raise ErrorDatos("El abono debe ser mayor que cero.")
    if afecta_saldo and monto > d["saldo"]:
        raise ErrorDatos("El abono supera el saldo de la deuda. Ajusta el saldo por extracto primero.")
    if d["moneda"] == "USD":
        if not trm:
            raise ErrorDatos("Para un abono en USD escribe la TRM.")
        if costo_cop is None:
            costo_cop = usd_a_cop(monto, trm)
    else:
        trm, costo_cop = None, None
    cur = con.execute(
        "INSERT INTO movimientos_deuda (deuda_id, fecha, tipo, monto, trm, costo_cop, quincena_id, nota)"
        " VALUES (?, ?, 'abono', ?, ?, ?, ?, ?)",
        (d["id"], fecha, monto, trm, costo_cop, quincena_id, nota),
    )
    if afecta_saldo:
        con.execute("UPDATE deudas SET saldo = saldo - ? WHERE id = ?", (monto, d["id"]))
    return cur.lastrowid


def abonar(con: sqlite3.Connection, deuda_id: int, fecha: str, monto: int,
           trm: int | None = None, nota: str = "", costo_cop: int | None = None,
           afecta_saldo: bool = True) -> int:
    """Abono en la moneda de la deuda. En USD guarda la TRM y el costo en COP."""
    d = deuda(con, deuda_id)
    with con:
        return _insertar_abono(con, d, fecha, monto, trm, costo_cop, None, nota, afecta_saldo)


def ajustar_saldo(con: sqlite3.Connection, deuda_id: int, fecha: str, saldo_nuevo: int,
                  nota: str = "") -> int:
    """Reemplaza el saldo por el del extracto y deja un movimiento 'ajuste' con la diferencia."""
    if saldo_nuevo < 0:
        raise ErrorDatos("El saldo no puede ser negativo.")
    d = deuda(con, deuda_id)
    diferencia = saldo_nuevo - d["saldo"]
    with con:
        cur = con.execute(
            "INSERT INTO movimientos_deuda (deuda_id, fecha, tipo, monto, nota) VALUES (?, ?, 'ajuste', ?, ?)",
            (deuda_id, fecha, diferencia, nota or "Ajuste por extracto"),
        )
        con.execute("UPDATE deudas SET saldo = ? WHERE id = ?", (saldo_nuevo, deuda_id))
    return cur.lastrowid


def movimientos(con: sqlite3.Connection, deuda_id: int, limite: int = 50) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM movimientos_deuda WHERE deuda_id = ? ORDER BY fecha DESC, id DESC LIMIT ?",
        (deuda_id, limite),
    ).fetchall()


def ultima_trm(con: sqlite3.Connection, deuda_id: int | None = None) -> int | None:
    """La TRM más reciente: de los abonos de la deuda o, si no hay, de la última foto."""
    if deuda_id is not None:
        fila = con.execute(
            "SELECT trm FROM movimientos_deuda WHERE deuda_id = ? AND trm IS NOT NULL"
            " ORDER BY fecha DESC, id DESC LIMIT 1", (deuda_id,)
        ).fetchone()
        if fila:
            return fila["trm"]
    fila = con.execute(
        "SELECT trm, fecha FROM ("
        " SELECT trm, fecha FROM movimientos_deuda WHERE trm IS NOT NULL"
        " UNION ALL SELECT trm, fecha FROM fotos) ORDER BY fecha DESC LIMIT 1"
    ).fetchone()
    return fila["trm"] if fila else None


def estado_deudas(con: sqlite3.Connection, hoy: date) -> list[dict]:
    salida = []
    for d in deudas(con):
        abonos = [
            (_f(r["fecha"]), r["monto"])
            for r in con.execute(
                "SELECT fecha, monto FROM movimientos_deuda WHERE deuda_id = ? AND tipo = 'abono'",
                (d["id"],),
            )
        ]
        est = logica.fecha_estimada_cero(d["saldo"], abonos, hoy)
        trm = ultima_trm(con, d["id"]) if d["moneda"] == "USD" else None
        promedio_cop = None
        saldo_cop = d["saldo"]
        if d["moneda"] == "USD":
            saldo_cop = usd_a_cop(d["saldo"], trm) if trm else None
            if est and trm:
                promedio_cop = usd_a_cop(est.promedio, trm)
        elif est:
            promedio_cop = est.promedio
        salida.append({"deuda": d, "estimado": est, "trm": trm, "saldo_cop": saldo_cop,
                       "promedio_cop": promedio_cop})
    return salida


# ---------- Plantillas ----------

def plantillas(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM plantillas ORDER BY nombre").fetchall()


def plantilla_por_nombre(con: sqlite3.Connection, nombre: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM plantillas WHERE nombre = ?", (nombre,)).fetchone()


def lineas_plantilla(con: sqlite3.Connection, plantilla_id: int) -> list[Linea]:
    filas = con.execute(
        "SELECT * FROM plantilla_lineas WHERE plantilla_id = ? ORDER BY orden, id", (plantilla_id,)
    ).fetchall()
    return [
        Linea(r["concepto"], r["bolsillo_id"], r["monto"], r["modo"], r["deuda_id"], r["id"], fondo_id=r["fondo_id"])
        for r in filas
    ]


def guardar_lineas_plantilla(con: sqlite3.Connection, plantilla_id: int, lineas: list[Linea]) -> None:
    logica.validar_plantilla(lineas)
    with con:
        con.execute("DELETE FROM plantilla_lineas WHERE plantilla_id = ?", (plantilla_id,))
        for i, l in enumerate(lineas):
            con.execute(
                "INSERT INTO plantilla_lineas (plantilla_id, orden, concepto, bolsillo_id, modo, monto, deuda_id, fondo_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (plantilla_id, i, l.concepto, l.bolsillo_id, l.modo,
                 l.monto if l.modo == "fijo" else None, l.deuda_id, l.fondo_id),
            )


# ---------- Quincenas ----------

def confirmar_quincena(con: sqlite3.Connection, fecha: str, neto: int, plantilla_id: int | None,
                       lineas: list[Linea], trm: int | None = None, tipo: str = "quincena") -> int:
    """Guarda la quincena (o ingreso extra) y sus líneas. Las líneas que apuntan a una deuda crean
    su abono; las que apuntan a un fondo, su aporte. Para deudas en USD el monto de la línea (COP)
    se convierte con la TRM dada."""
    if tipo not in logica.TIPOS_INGRESO:
        raise RepartoInvalido("Elige el tipo de ingreso.")
    ok, motivo = logica.puede_confirmar(neto, [l.monto for l in lineas])
    if not ok:
        raise RepartoInvalido(motivo)
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise RepartoInvalido("La fecha no es válida.") from None
    with con:
        cur = con.execute(
            "INSERT INTO quincenas (fecha, neto, plantilla_id, trm, tipo) VALUES (?, ?, ?, ?, ?)",
            (fecha, neto, plantilla_id, trm, tipo),
        )
        qid = cur.lastrowid
        for i, l in enumerate(lineas):
            con.execute(
                "INSERT INTO quincena_lineas (quincena_id, orden, concepto, bolsillo_id, monto, deuda_id, fondo_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (qid, i, l.concepto, l.bolsillo_id, l.monto, l.deuda_id, l.fondo_id),
            )
            if l.fondo_id and l.monto > 0:
                con.execute(
                    "INSERT INTO fondo_movimientos (fondo_id, fecha, tipo, monto, quincena_id, nota)"
                    " VALUES (?, ?, 'aporte', ?, ?, ?)", (l.fondo_id, fecha, l.monto, qid, l.concepto),
                )
            if l.deuda_id and l.monto > 0:
                d = deuda(con, l.deuda_id)
                if d["moneda"] == "USD":
                    if not trm:
                        raise RepartoInvalido("Escribe la TRM para el abono en USD.")
                    monto = cop_a_usd(l.monto, trm)
                    _insertar_abono(con, d, fecha, monto, trm, l.monto, qid, f"Quincena {fecha}: {l.concepto}")
                else:
                    _insertar_abono(con, d, fecha, l.monto, None, None, qid, f"Quincena {fecha}: {l.concepto}")
    return qid


def quincenas(con: sqlite3.Connection, limite: int = 24) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT q.*, p.nombre AS plantilla FROM quincenas q LEFT JOIN plantillas p ON p.id = q.plantilla_id"
        " ORDER BY q.fecha DESC, q.id DESC LIMIT ?", (limite,)
    ).fetchall()


def quincena(con: sqlite3.Connection, qid: int) -> sqlite3.Row | None:
    return con.execute(
        "SELECT q.*, p.nombre AS plantilla FROM quincenas q LEFT JOIN plantillas p ON p.id = q.plantilla_id"
        " WHERE q.id = ?", (qid,)
    ).fetchone()


def lineas_quincena(con: sqlite3.Connection, qid: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT l.*, b.nombre AS bolsillo, b.tipo AS tipo, d.nombre AS deuda, f.nombre AS fondo,"
        " p.monto AS real, p.fecha AS pagada FROM quincena_lineas l"
        " JOIN bolsillos b ON b.id = l.bolsillo_id LEFT JOIN deudas d ON d.id = l.deuda_id"
        " LEFT JOIN fondos f ON f.id = l.fondo_id LEFT JOIN pagos p ON p.linea_id = l.id"
        " WHERE l.quincena_id = ? ORDER BY l.orden, l.id", (qid,)
    ).fetchall()


def tira(con: sqlite3.Connection, pares: list[tuple[int, int]]) -> list[dict]:
    """Segmentos de la tira del reparto: total por bolsillo con nombre y tipo."""
    info = {b["id"]: b for b in bolsillos(con)}
    tot = logica.totales_por_bolsillo(pares)
    return [
        {"id": b, "nombre": info[b]["nombre"], "tipo": info[b]["tipo"], "monto": m}
        for b, m in tot.items() if b in info
    ]


# ---------- Cuentas, fotos, metas ----------

def cuentas(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM cuentas ORDER BY orden, id").fetchall()


def crear_cuenta(con: sqlite3.Connection, nombre: str) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ErrorDatos("Escribe un nombre para la cuenta.")
    if con.execute("SELECT 1 FROM cuentas WHERE nombre = ?", (nombre,)).fetchone():
        raise ErrorDatos(f"Ya existe una cuenta llamada «{nombre}».")
    orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM cuentas").fetchone()[0]
    with con:
        return con.execute("INSERT INTO cuentas (nombre, orden) VALUES (?, ?)", (nombre, orden)).lastrowid


def guardar_foto(con: sqlite3.Connection, fecha: str, trm: int, saldos: dict[int, int],
                 saldos_deudas: dict[int, int]) -> int:
    """Guarda (o reemplaza) la foto de esa fecha."""
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise ErrorDatos("La fecha no es válida.") from None
    if trm <= 0:
        raise ErrorDatos("Escribe la TRM del día.")
    if any(s < 0 for s in saldos_deudas.values()):
        raise ErrorDatos("El saldo de una deuda no puede ser negativo.")
    with con:
        con.execute("DELETE FROM fotos WHERE fecha = ?", (fecha,))
        fid = con.execute("INSERT INTO fotos (fecha, trm) VALUES (?, ?)", (fecha, trm)).lastrowid
        con.executemany("INSERT INTO foto_saldos (foto_id, cuenta_id, saldo) VALUES (?, ?, ?)",
                        [(fid, c, s) for c, s in saldos.items()])
        con.executemany("INSERT INTO foto_deudas (foto_id, deuda_id, saldo) VALUES (?, ?, ?)",
                        [(fid, d, s) for d, s in saldos_deudas.items()])
    return fid


def fotos(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM fotos ORDER BY fecha").fetchall()


def ultima_foto(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM fotos ORDER BY fecha DESC LIMIT 1").fetchone()


def saldos_foto(con: sqlite3.Connection, foto_id: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT c.id, c.nombre, s.saldo FROM foto_saldos s JOIN cuentas c ON c.id = s.cuenta_id"
        " WHERE s.foto_id = ? ORDER BY c.orden, c.id", (foto_id,)
    ).fetchall()


def deudas_foto(con: sqlite3.Connection, foto_id: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT d.id, d.nombre, d.moneda, f.saldo FROM foto_deudas f JOIN deudas d ON d.id = f.deuda_id"
        " WHERE f.foto_id = ? ORDER BY d.orden, d.id", (foto_id,)
    ).fetchall()


def patrimonio_foto(con: sqlite3.Connection, foto: sqlite3.Row) -> logica.Patrimonio:
    return logica.patrimonio(
        [r["saldo"] for r in saldos_foto(con, foto["id"])],
        [(r["saldo"], r["moneda"]) for r in deudas_foto(con, foto["id"])],
        foto["trm"],
    )


def serie_patrimonio(con: sqlite3.Connection) -> list[dict]:
    salida = []
    for f in fotos(con):
        p = patrimonio_foto(con, f)
        salida.append({"fecha": f["fecha"], "neto": p.neto, "activos": p.activos, "deudas": p.deudas_cop})
    return salida


def metas(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM metas ORDER BY orden, id").fetchall()


def crear_meta(con: sqlite3.Connection, nombre: str, objetivo: int, cuenta_ids: list[int]) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ErrorDatos("Escribe un nombre para la meta.")
    if objetivo <= 0:
        raise ErrorDatos("El objetivo debe ser mayor que cero.")
    if not cuenta_ids:
        raise ErrorDatos("Elige al menos una cuenta que sume a la meta.")
    if con.execute("SELECT 1 FROM metas WHERE nombre = ?", (nombre,)).fetchone():
        raise ErrorDatos(f"Ya existe una meta llamada «{nombre}».")
    orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM metas").fetchone()[0]
    with con:
        mid = con.execute("INSERT INTO metas (nombre, objetivo, orden) VALUES (?, ?, ?)",
                          (nombre, objetivo, orden)).lastrowid
        con.executemany("INSERT INTO meta_cuentas (meta_id, cuenta_id) VALUES (?, ?)",
                        [(mid, c) for c in cuenta_ids])
    return mid


def avance_metas(con: sqlite3.Connection) -> list[dict]:
    """Avance de cada meta según la última foto."""
    foto = ultima_foto(con)
    saldos = {r["id"]: r["saldo"] for r in saldos_foto(con, foto["id"])} if foto else {}
    salida = []
    for m in metas(con):
        ids = [r[0] for r in con.execute("SELECT cuenta_id FROM meta_cuentas WHERE meta_id = ?", (m["id"],))]
        nombres = [r[0] for r in con.execute(
            "SELECT nombre FROM cuentas WHERE id IN (SELECT cuenta_id FROM meta_cuentas WHERE meta_id = ?)"
            " ORDER BY orden, id", (m["id"],))]
        actual = sum(saldos.get(i, 0) for i in ids)
        salida.append({"meta": m, "avance": logica.Avance(actual, m["objetivo"]), "cuentas": nombres})
    return salida
