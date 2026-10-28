"""Resumen mensual en Markdown con las reglas del vault: prefijo [M], fuente con fecha,
sin raya larga y sin números de cuenta."""

import re
import sqlite3
from datetime import date

from app.core.dinero import fmt_cop, fmt_moneda, fmt_trm

from . import consultas as q

_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def resumen_mes(con: sqlite3.Connection, mes: str, hoy: date) -> str:
    if not _MES.match(mes):
        raise ValueError("El mes debe tener la forma AAAA-MM, por ejemplo 2026-10.")
    fuente = f"[app finanzas {hoy.isoformat()} | alta]"
    anio, m = int(mes[:4]), int(mes[5:])
    lineas = [
        "---",
        "type: finance",
        f"updated: {hoy.isoformat()}",
        "sources: [app finanzas]",
        "---",
        "",
        f"# Resumen de finanzas, {MESES[m - 1]} de {anio}",
        "",
        "Generado por la app de finanzas personales. Montos en COP salvo que se indique.",
        "",
        "## Quincenas",
        "",
    ]
    quincenas = con.execute(
        "SELECT q.*, p.nombre AS plantilla FROM quincenas q LEFT JOIN plantillas p ON p.id = q.plantilla_id"
        " WHERE substr(q.fecha, 1, 7) = ? ORDER BY q.fecha, q.id", (mes,)
    ).fetchall()
    if not quincenas:
        lineas.append(f"- [M] Sin quincenas registradas en {mes} · {fuente}")
    for qu in quincenas:
        tot = q.tira(con, [(l["bolsillo_id"], l["monto"]) for l in q.lineas_quincena(con, qu["id"])])
        reparto = "; ".join(f"{t['nombre']} {fmt_cop(t['monto'])}" for t in tot)
        plantilla = f" (plantilla {qu['plantilla']})" if qu["plantilla"] else ""
        lineas.append(f"- [M] Quincena {qu['fecha']}{plantilla}: neto {fmt_cop(qu['neto'])}. Reparto: {reparto} · {fuente}")

    lineas += ["", "## Abonos y ajustes de deudas", ""]
    movs = con.execute(
        "SELECT m.*, d.nombre, d.moneda FROM movimientos_deuda m JOIN deudas d ON d.id = m.deuda_id"
        " WHERE substr(m.fecha, 1, 7) = ? ORDER BY m.fecha, m.id", (mes,)
    ).fetchall()
    if not movs:
        lineas.append(f"- [M] Sin abonos ni ajustes en {mes} · {fuente}")
    for mv in movs:
        monto = f"{fmt_moneda(abs(mv['monto']), mv['moneda'])} {mv['moneda']}"
        if mv["tipo"] == "abono":
            extra = ""
            if mv["moneda"] == "USD" and mv["trm"]:
                extra = f" con TRM {fmt_trm(mv['trm'])} (costo {fmt_cop(mv['costo_cop'])} COP)"
            texto = f"Abono a {mv['nombre']} el {mv['fecha']}: {monto}{extra}"
        else:
            sentido = "sube" if mv["monto"] > 0 else "baja"
            texto = f"Ajuste por extracto de {mv['nombre']} el {mv['fecha']}: el saldo {sentido} {monto}"
        nota = f". Nota: {mv['nota']}" if mv["nota"] and mv["tipo"] == "abono" else ""
        lineas.append(f"- [M] {texto}{nota} · {fuente}")

    gastos = con.execute(
        "SELECT g.*, b.nombre AS bolsillo, c.nombre AS categoria FROM gastos g JOIN bolsillos b ON b.id = g.bolsillo_id"
        " LEFT JOIN categorias c ON c.id = g.categoria_id WHERE substr(g.fecha, 1, 7) = ? ORDER BY g.fecha, g.id", (mes,)
    ).fetchall()
    if gastos:
        lineas += ["", "## Gastos rápidos", ""]
        total = sum(g["monto"] for g in gastos)
        lineas.append(f"- [M] {len(gastos)} gastos rápidos por {fmt_cop(total)} en {mes} · {fuente}")
        for g in gastos:
            nota = f", {g['nota']}" if g["nota"] else ""
            lineas.append(f"- [M] {g['fecha']}: {fmt_cop(g['monto'])} en {g['bolsillo']} ({g['categoria'] or 'sin categoría'}){nota} · {fuente}")

    lineas += ["", "## Saldos de deudas", ""]
    for d in q.deudas(con):
        lineas.append(f"- [M] {d['nombre']}: {fmt_moneda(d['saldo'], d['moneda'])} {d['moneda']} al {hoy.isoformat()} · {fuente}")

    lineas += ["", "## Metas", ""]
    metas = q.avance_metas(con)
    if not metas:
        lineas.append(f"- [M] Sin metas registradas · {fuente}")
    for mt in metas:
        a = mt["avance"]
        lineas.append(
            f"- [M] {mt['meta']['nombre']}: {fmt_cop(a.actual)} de {fmt_cop(a.objetivo)} ({a.pct} %), "
            f"faltan {fmt_cop(a.faltan)} · {fuente}"
        )

    lineas += ["", "## Patrimonio neto", ""]
    foto = con.execute(
        "SELECT * FROM fotos WHERE substr(fecha, 1, 7) <= ? ORDER BY fecha DESC LIMIT 1", (mes,)
    ).fetchone()
    if not foto:
        lineas.append(f"- [M] Sin foto mensual hasta {mes} · {fuente}")
    else:
        p = q.patrimonio_foto(con, foto)
        cuentas = "; ".join(f"{r['nombre']} {fmt_cop(r['saldo'])}" for r in q.saldos_foto(con, foto["id"]))
        lineas.append(f"- [M] Foto del {foto['fecha']} (TRM {fmt_trm(foto['trm'])}): cuentas {fmt_cop(p.activos)} ({cuentas}) · {fuente}")
        lineas.append(f"- [M] Deudas en COP a esa TRM: {fmt_cop(p.deudas_cop)} · {fuente}")
        lineas.append(f"- [M] Patrimonio neto: {fmt_cop(p.neto)} · {fuente}")
    rev = con.execute("SELECT * FROM revisiones WHERE mes = ?", (mes,)).fetchone()
    if rev:
        from .real import PREGUNTAS
        lineas += ["", "## Revisión del mes", ""]
        for k, pregunta in PREGUNTAS.items():
            if rev[k] not in (None, ""):
                lineas.append(f"- [M] {pregunta} {rev[k]} · {fuente}")
    texto = "\n".join(lineas) + "\n"
    return texto.replace("\u2014", ",")  # Nunca raya larga.
