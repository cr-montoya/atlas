"""Resumen para que la sesión del Life Brain lea los datos sin que el usuario escriba un prompt.

Escribe exports/resumen-ia.json (esquema versionado, ver docs/resumen-ia.md) y exports/resumen-ia.md.
La app nunca escribe en el vault. Uso: uv run python -m app.modules.finanzas.resumen_ia
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from app.core.dinero import fmt_cop, fmt_moneda, fmt_tasa
from app.core.resumen import escribir_par, sobre

from . import consultas as q
from . import futuro as fu
from . import logica, real

SCHEMA_VERSION = "1"
UNIDADES = "Montos enteros. COP en pesos; USD en centavos (moneda USD); TRM en centavos de peso; tasas en partes por millón (1 % = 10000)."


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def construir(con: sqlite3.Connection, hoy: date) -> dict:
    desde = (hoy - timedelta(days=90)).isoformat()
    # Quincenas e ingresos recientes con plan vs real
    quincenas, pvr = [], []
    for qu in con.execute("SELECT q.*, p.nombre AS plantilla FROM quincenas q LEFT JOIN plantillas p ON p.id = q.plantilla_id"
                          " WHERE q.fecha >= ? ORDER BY q.fecha, q.id", (desde,)):
        lineas = q.lineas_quincena(con, qu["id"])
        quincenas.append({
            "id": qu["id"], "fecha": qu["fecha"], "tipo": qu["tipo"], "neto": qu["neto"], "moneda": "COP",
            "plantilla": qu["plantilla"], "trm": qu["trm"],
            "lineas": [{
                "concepto": l["concepto"], "bolsillo": l["bolsillo"], "tipo_bolsillo": l["tipo"],
                "planeado": l["monto"], "real": l["real"], "pagada": l["pagada"],
                "deuda": l["deuda"], "fondo": l["fondo"],
            } for l in lineas],
        })
        pvr.append({"quincena_id": qu["id"], "fecha": qu["fecha"], "bolsillos": [
            {"bolsillo": b["nombre"], "tipo": b["tipo"], "planeado": b["planeado"], "real": b["real"],
             "diferencia": b["diferencia"]} for b in real.plan_vs_real(con, qu["id"])]})
    gastos = [{"fecha": g["fecha"], "monto": g["monto"], "moneda": "COP", "bolsillo": g["bolsillo"],
               "categoria": g["categoria"], "nota": g["nota"]}
              for g in real.gastos(con, desde, hoy.isoformat())]
    abonos = [{"fecha": m["fecha"], "deuda": m["nombre"], "tipo": m["tipo"], "monto": m["monto"], "moneda": m["moneda"],
               "trm": m["trm"], "costo_cop": m["costo_cop"], "nota": m["nota"]}
              for m in con.execute("SELECT m.*, d.nombre, d.moneda FROM movimientos_deuda m JOIN deudas d ON d.id = m.deuda_id"
                                   " WHERE m.fecha >= ? ORDER BY m.fecha, m.id", (desde,))]
    deudas = []
    for e in q.estado_deudas(con, hoy):
        d, est = e["deuda"], e["estimado"]
        deudas.append({
            "nombre": d["nombre"], "moneda": d["moneda"], "saldo": d["saldo"], "saldo_cop": e["saldo_cop"],
            "trm_usada": e["trm"], "tasa_mensual_ppm": d["tasa_mensual_ppm"], "cuota_mensual": d["cuota_mensual"],
            "fecha_cero_por_promedio": _iso(est.fecha) if est else None,
            "promedio_por_quincena": est.promedio if est else None, "pocos_datos": est.pocos_datos if est else None,
        })
    fondos = [{
        "nombre": x["f"]["nombre"], "objetivo": x["f"]["objetivo"], "acumulado": x["f"]["acumulado"],
        "fecha_objetivo": x["f"]["fecha_objetivo"], "cada_meses": x["f"]["cada_meses"],
        "provision_quincena": x["provision"], "quincenas_restantes": x["quincenas"],
        "estimado": bool(x["f"]["estimado"]), "aporte_fijo": x["f"]["aporte_mensual"] or None,
        "no_liquido": x["aporte_fijo"], "falta": None if x["aporte_fijo"] else (x["estado"].problema or None),
    } for x in real.fondos(con, hoy)]
    metas = [{"nombre": m["meta"]["nombre"], "objetivo": m["avance"].objetivo, "actual": m["avance"].actual,
              "pct": m["avance"].pct, "faltan": m["avance"].faltan, "cuentas": m["cuentas"]} for m in q.avance_metas(con)]
    ind = real.indicadores(con, hoy)
    entrada, esc, avisos = real.entrada_proyeccion(con, hoy)
    p = fu.proyectar(entrada)
    otra = "bola" if esc["estrategia"] == "avalancha" else "avalancha"
    p_otra = fu.proyectar(fu.Entrada(**{**entrada.__dict__, "estrategia": otra}))
    ultimo = p.meses[-1] if p.meses else None
    foto = q.ultima_foto(con)
    patrimonio = q.patrimonio_foto(con, foto) if foto else None
    mes_anterior = (date(hoy.year, hoy.month, 1) - timedelta(days=1)).strftime("%Y-%m")
    rev = real.revision(con, hoy.strftime("%Y-%m")) or real.revision(con, mes_anterior)
    return {
        **sobre("finanzas", hoy, SCHEMA_VERSION, UNIDADES),
        "periodo": {"desde": desde, "hasta": hoy.isoformat()},
        "proximo_pago": logica.proximo_dia_pago(hoy).isoformat(),
        "quincenas": quincenas,
        "plan_vs_real": pvr,
        "gastos": gastos,
        "abonos": abonos,
        "deudas": deudas,
        "fondos": fondos,
        "metas": metas,
        "cuentas": [{"nombre": c["nombre"], "rendimiento_ea_ppm": c["ea_bruto_ppm"],
                     "rendimiento_ea_neto_ppm": c["ea_ppm"], "nota": c["nota"]}
                    for c in real.comparacion_rendimiento(con)["cuentas"]],
        "ahorrar_o_prepagar": [{k: f[k] for k in ("cuenta", "deuda", "dif_ppm", "texto")}
                               for f in real.comparacion_rendimiento(con)["frases"]],
        "patrimonio": None if not foto else {
            "foto": foto["fecha"], "trm": foto["trm"], "cuentas": patrimonio.activos,
            "deudas_cop": patrimonio.deudas_cop, "neto": patrimonio.neto},
        "indicadores": {
            "mes": ind["mes"], "ingreso_neto": ind["ingreso"], "ahorro": ind["ahorro"],
            "tasa_ahorro_pct": ind["tasa_ahorro"], "meses_colchon_decimas": ind["colchon_decimas"],
            "gasto_basico_referencia": ind["gasto_basico"], "pagos_deuda": ind["pagos_deuda"],
            "deuda_ingreso_pct": ind["deuda_ingreso"], "gasto_libre_tope": ind["tope_libre"],
            "gasto_libre_real": ind["real_libre"]},
        "escenario": {k: esc[k] for k in real.CAMPOS_ESCENARIO},
        "eventos": [{"nombre": e["nombre"], "fecha": e["fecha"], "tipo": e["tipo"], "monto": e["monto"],
                     "estimado": bool(e["estimado"]), "destino_deuda": e["deuda"], "destino_fondo": e["fondo"],
                     "solo_escenario": e["escenario"] or None} for e in real.eventos(con)],
        "proyeccion_resumen": {
            "meses": len(p.meses), "estrategia": esc["estrategia"],
            "fecha_cero": p.fecha_cero, "mes_libre_de_deudas": p.mes_libre, "intereses_totales": p.intereses,
            "comparacion": {otra: {"mes_libre_de_deudas": p_otra.mes_libre, "intereses_totales": p_otra.intereses}},
            "mes_meta_1": p.mes_meta1, "mes_m4": p.mes_m4, "rendimientos_cuentas": p.rendimientos,
            "mes_inicio_inversion": p.mes_inicio_inversion,
            "rendimientos_netos_de_retencion": True,  # la inversión de largo plazo va sin retención (variable)
            "al_final": None if not ultimo else {
                "mes": ultimo.clave, "fondo_emergencia": ultimo.emergencia,
                "meses_colchon_decimas": ultimo.meses_colchon_decimas, "deuda_total": ultimo.deuda_total,
                "inversion_largo_plazo": ultimo.inversion,
                "patrimonio": ultimo.patrimonio},
            "por_mes": [{"mes": m.clave, "ingreso": m.ingreso, "gasto": m.gasto, "deuda_total": m.deuda_total,
                         "fondo_emergencia": m.emergencia, "inversion_largo_plazo": m.inversion,
                         "patrimonio": m.patrimonio, "eventos": m.eventos}
                        for m in p.meses],
        },
        "revision": None if not rev else {
            "mes": rev["mes"], **{k: rev[k] for k in real.PREGUNTAS}, "actualizada": rev["actualizada"]},
        "avisos": avisos + p.avisos,
    }


def markdown(d: dict) -> str:
    f = d["fuente"]
    out = [
        "---", "type: finance", f"updated: {d['hoy']}", "sources: [app finanzas]", f"schema_version: {d['schema_version']}",
        "---", "", f"# Resumen para IA, {d['hoy']}", "",
        "Generado por la app de finanzas. Datos de los últimos 90 días; montos en COP salvo que se indique.", "",
        "## Quincenas e ingresos", "",
    ]
    for qu in d["quincenas"]:
        out.append(f"- [M] {qu['fecha']} ({qu['tipo']}): neto {fmt_cop(qu['neto'])} · {f}")
    for b in d["plan_vs_real"]:
        partes = [f"{x['bolsillo']} plan {fmt_cop(x['planeado'])}, " + ("sin registrar" if x["real"] is None else
                  f"real {fmt_cop(x['real'])}") for x in b["bolsillos"]]
        out.append(f"- [M] Plan vs real de {b['fecha']}: " + "; ".join(partes) + f" · {f}")
    out += ["", "## Gastos rápidos", ""]
    out += [f"- [M] {g['fecha']}: {fmt_cop(g['monto'])} en {g['bolsillo']} ({g['categoria'] or 'sin categoría'})"
            + (f", {g['nota']}" if g["nota"] else "") + f" · {f}" for g in d["gastos"]] or [f"- [M] Sin gastos rápidos registrados · {f}"]
    out += ["", "## Deudas", ""]
    for x in d["deudas"]:
        tasa = "sin tasa" if x["tasa_mensual_ppm"] is None else f"tasa {fmt_tasa(x['tasa_mensual_ppm'])} % mensual"
        out.append(f"- [M] {x['nombre']}: {fmt_moneda(x['saldo'], x['moneda'])} {x['moneda']}, {tasa}, "
                   f"en cero por promedio {x['fecha_cero_por_promedio'] or 'sin dato'} · {f}")
    out += ["", "## Fondos de previsión", ""]
    for x in d["fondos"]:
        if x["aporte_fijo"]:
            estado = f"aporte fijo {fmt_cop(x['aporte_fijo'])} cada 30, no líquido, devuelve el {x['fecha_objetivo']}"
        else:
            estado = x["falta"] or f"provisión {fmt_cop(x['provision_quincena'])} por quincena"
        out.append(f"- [M] {x['nombre']}{' (estimado)' if x['estimado'] else ''}: {fmt_cop(x['acumulado'])} de "
                   f"{fmt_cop(x['objetivo'])}, {estado} · {f}")
    out += ["", "## Metas e indicadores", ""]
    for m in d["metas"]:
        out.append(f"- [M] {m['nombre']}: {fmt_cop(m['actual'])} de {fmt_cop(m['objetivo'])} ({m['pct']} %) · {f}")
    i = d["indicadores"]
    def pct(v):
        return "sin datos" if v is None else f"{v} %"
    colchon = "sin datos" if i["meses_colchon_decimas"] is None else f"{i['meses_colchon_decimas'] // 10},{i['meses_colchon_decimas'] % 10} meses"
    out.append(f"- [M] Indicadores de {i['mes']}: tasa de ahorro {pct(i['tasa_ahorro_pct'])}, colchón {colchon}, "
               f"deuda / ingreso {pct(i['deuda_ingreso_pct'])} · {f}")
    pr = d["proyeccion_resumen"]
    out += ["", "## Proyección", ""]
    ceros = "; ".join(f"{k} {v or 'después del horizonte'}" for k, v in pr["fecha_cero"].items())
    out.append(f"- [M] Estrategia {pr['estrategia']}, {pr['meses']} meses. Fechas de cero: {ceros} · {f}")
    if pr["al_final"]:
        a = pr["al_final"]
        out.append(f"- [M] Al final ({a['mes']}): fondo de emergencia {fmt_cop(a['fondo_emergencia'])}, "
                   f"patrimonio {fmt_cop(a['patrimonio'])} · {f}")
    if d["revision"]:
        r = d["revision"]
        out += ["", f"## Revisión de {r['mes']}", ""]
        for k, pregunta in real.PREGUNTAS.items():
            if r.get(k) not in (None, ""):
                out.append(f"- [M] {pregunta} {r[k]} · {f}")
    if d["avisos"]:
        out += ["", "## Avisos", ""] + [f"- {a}" for a in d["avisos"]]
    return ("\n".join(out) + "\n").replace("—", ",")


def escribir(con: sqlite3.Connection, carpeta: Path, hoy: date) -> tuple[Path, Path]:
    datos = construir(con, hoy)
    return escribir_par(carpeta, "resumen-ia", datos, markdown(datos))


def main() -> int:
    from app.core.config import leer_config
    from app.core.db import conectar, migrar
    cfg = leer_config()
    con = conectar(cfg.db_path)
    migrar(con)
    js, md = escribir(con, cfg.exports_path, date.today())
    print(f"Escrito {js} y {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
