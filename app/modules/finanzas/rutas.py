"""Rutas del módulo de finanzas: tablero, quincenas, deudas, metas, fotos, ajustes y exportar."""

import logging
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from app.core.db import con_peticion
from app.core.dinero import MontoInvalido, parse_centavos, parse_cop, parse_moneda

from . import consultas as q
from . import exportar, logica, real, resumen_ia
from .consultas import ErrorDatos
from .logica import Linea, RepartoInvalido

router = APIRouter()
Con = Depends(con_peticion)


def hoy() -> date:
    return date.today()


def actualizar_resumen_ia(request: Request, con: sqlite3.Connection) -> None:
    """Regenera exports/resumen-ia.*; si falla, la operación de plata ya quedó guardada."""
    try:
        resumen_ia.escribir(con, request.app.state.config.exports_path, hoy())
    except Exception:  # noqa: BLE001
        logging.getLogger("finanzas").exception("No se pudo escribir el resumen para IA")


def render(request: Request, nombre: str, ctx: dict, status: int = 200) -> HTMLResponse:
    ctx.setdefault("seccion", "")
    return request.app.state.templates.TemplateResponse(request, nombre, ctx, status_code=status)


def _a_int(valor, defecto=None):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


# ---------- Tablero ----------

@router.get("/")
def tablero(request: Request, con: sqlite3.Connection = Con):
    h = hoy()
    pago = logica.proximo_dia_pago(h)
    foto = q.ultima_foto(con)
    ultima = q.quincenas(con, 1)
    ultimo = None
    if ultima:
        lineas = q.lineas_quincena(con, ultima[0]["id"])
        ultimo = {"quincena": ultima[0],
                  "tira": q.tira(con, [(l["bolsillo_id"], l["monto"]) for l in lineas]),
                  "pvr": real.plan_vs_real(con, ultima[0]["id"])}
    return render(request, "finanzas/tablero.html", {
        "seccion": "inicio",
        "hoy": h,
        "pago": pago,
        "dias_para_pago": (pago - h).days,
        "plantilla_pago": logica.plantilla_para_fecha(pago),
        "deudas": [d for d in q.estado_deudas(con, h) if d["deuda"]["saldo"] > 0],
        "metas": q.avance_metas(con),
        "foto": foto,
        "patrimonio": q.patrimonio_foto(con, foto) if foto else None,
        "serie": q.serie_patrimonio(con),
        "ultimo": ultimo,
        "ind": real.indicadores(con, h),
        "fondos": real.fondos(con, h),
    })


# ---------- Quincena: registrar, repartir, confirmar ----------

def _lineas_pedir(con, plantilla_id: int | None) -> list[Linea]:
    if not plantilla_id:
        return []
    return [l for l in q.lineas_plantilla(con, plantilla_id) if l.modo == "pedir"]


def _ctx_quincena(con, **extra) -> dict:
    h = hoy()
    pago = logica.proximo_dia_pago(h)
    sugerida = q.plantilla_por_nombre(con, logica.plantilla_para_fecha(pago))
    plantillas = q.plantillas(con)
    pid = extra.pop("plantilla_id", None)
    if pid is None:
        pid = sugerida["id"] if sugerida else (plantillas[0]["id"] if plantillas else 0)
    ctx = {
        "seccion": "quincena",
        "tipo": extra.pop("tipo", "quincena"),
        "tipos": logica.TIPOS_INGRESO,
        "fecha": extra.pop("fecha", pago.isoformat()),
        "neto_txt": extra.pop("neto_txt", ""),
        "plantillas": plantillas,
        "plantilla_id": pid,
        "pedidos": _lineas_pedir(con, pid),
        "pedidos_txt": extra.pop("pedidos_txt", {}),
        "historial": q.quincenas(con),
        "bolsillos": q.bolsillos(con),
        "deudas": q.deudas(con),
        "editor": None,
        "error": None,
    }
    ctx.update(extra)
    return ctx


@router.get("/quincena")
def quincena_nueva(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/quincena.html", _ctx_quincena(con))


@router.get("/quincena/pedidos")
def quincena_pedidos(request: Request, plantilla_id: int, con: sqlite3.Connection = Con):
    return render(request, "finanzas/_pedidos.html",
                  {"pedidos": _lineas_pedir(con, plantilla_id), "pedidos_txt": {}})


def _bolsillo_libre(con) -> int:
    bs = q.bolsillos(con)
    libres = [b for b in bs if b["tipo"] == "libre"]
    return (libres or bs)[0]["id"] if bs else 0


def _editor(con, neto: int, lineas: list[Linea], trm_txt: str = "", errores: dict | None = None) -> dict:
    info_b = {b["id"]: b for b in q.bolsillos(con)}
    info_d = {d["id"]: d for d in q.deudas(con)}
    montos = [l.monto or 0 for l in lineas]
    c = logica.cuadre(neto, montos)
    ok, motivo = logica.puede_confirmar(neto, montos)
    return {
        "neto": neto,
        "lineas": lineas,
        "info_b": info_b,
        "info_d": info_d,
        "cuadre": c,
        "puede": ok and not errores,
        "motivo": motivo,
        "tira": q.tira(con, [(l.bolsillo_id, l.monto or 0) for l in lineas if (l.monto or 0) > 0]),
        "pide_trm": any(l.deuda_id and info_d.get(l.deuda_id) and info_d[l.deuda_id]["moneda"] == "USD"
                        for l in lineas),
        "trm_txt": trm_txt,
        "errores": errores or {},
    }


@router.post("/quincena/propuesta")
async def quincena_propuesta(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    fecha = str(form.get("fecha", ""))
    neto_txt = str(form.get("neto", ""))
    pid = _a_int(form.get("plantilla_id"), 0)
    tipo = str(form.get("tipo", "quincena"))
    pedidos_txt = {k[7:]: str(v) for k, v in form.items() if k.startswith("pedido_")}
    ctx = _ctx_quincena(con, fecha=fecha, neto_txt=neto_txt, plantilla_id=pid, pedidos_txt=pedidos_txt, tipo=tipo)
    try:
        neto = parse_cop(neto_txt)
        if neto <= 0:
            raise MontoInvalido("El neto debe ser mayor que cero.")
        f = date.fromisoformat(fecha)
        if tipo not in logica.TIPOS_INGRESO:
            raise RepartoInvalido("Elige el tipo de ingreso.")
        if pid:
            lineas = q.lineas_plantilla(con, pid)
            if not lineas:
                raise RepartoInvalido("Esa plantilla no tiene líneas.")
            # Provisión de fondos: entra sola antes del resto.
            i_resto = next((i for i, l in enumerate(lineas) if l.modo == "resto"), len(lineas))
            lineas[i_resto:i_resto] = real.lineas_fondo(con, f)
        else:
            lineas = [Linea("Libre", _bolsillo_libre(con), None, "resto")]
        pedidos = {}
        for l in lineas:
            if l.modo == "pedir":
                txt = pedidos_txt.get(str(l.plantilla_linea_id), "")
                if not txt.strip():
                    raise RepartoInvalido(f"Escribe el valor de «{l.concepto}» antes de calcular el resto.")
                pedidos[l.plantilla_linea_id] = parse_cop(txt)
        ctx["editor"] = _editor(con, neto, logica.aplicar_plantilla(neto, lineas, pedidos))
    except (MontoInvalido, RepartoInvalido) as e:
        ctx["error"] = str(e)
    except ValueError:
        ctx["error"] = "La fecha no es válida."
    return render(request, "finanzas/quincena.html", ctx, 200 if not ctx["error"] else 422)


def _leer_editor(form) -> tuple[int, list[Linea], dict, str]:
    """Lee las líneas del formulario del reparto. Devuelve neto, líneas, errores por fila y TRM."""
    errores: dict = {}
    try:
        neto = parse_cop(str(form.get("neto", "")))
    except MontoInvalido as e:
        neto, errores["neto"] = 0, str(e)
    conceptos = form.getlist("concepto")
    bolsillos = form.getlist("bolsillo_id")
    montos = form.getlist("monto")
    modos = form.getlist("modo")
    deudas = form.getlist("deuda_id")
    fondos = form.getlist("fondo_id")
    lineas = []
    for i, concepto in enumerate(conceptos):
        txt = str(montos[i]) if i < len(montos) else ""
        try:
            monto = parse_cop(txt, permitir_negativo=True) if txt.strip() else 0
        except MontoInvalido as e:
            monto, errores[i] = 0, str(e)
        lineas.append(Linea(
            concepto=str(concepto).strip() or "Sin concepto",
            bolsillo_id=_a_int(bolsillos[i] if i < len(bolsillos) else None, 0),
            monto=monto,
            modo=str(modos[i]) if i < len(modos) else "fijo",
            deuda_id=_a_int(deudas[i] if i < len(deudas) else None),
            extra={"txt": txt},
            fondo_id=_a_int(fondos[i] if i < len(fondos) else None),
        ))
    return neto, lineas, errores, str(form.get("trm", ""))


@router.post("/quincena/cuadre")
async def quincena_cuadre(request: Request, con: sqlite3.Connection = Con):
    neto, lineas, errores, trm_txt = _leer_editor(await request.form())
    return render(request, "finanzas/_cuadre.html", {"e": _editor(con, neto, lineas, trm_txt, errores), "oob": True})


@router.post("/quincena/recalcular")
async def quincena_recalcular(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    neto, lineas, errores, trm_txt = _leer_editor(form)
    resto = [l for l in lineas if l.modo == "resto"]
    if resto:
        resto[0].monto = neto - sum(l.monto for l in lineas if l.modo != "resto")
        resto[0].extra["txt"] = ""
    ctx = _ctx_quincena(con, fecha=str(form.get("fecha", "")), plantilla_id=_a_int(form.get("plantilla_id"), 0),
                        tipo=str(form.get("tipo", "quincena")))
    ctx["editor"] = _editor(con, neto, lineas, trm_txt, errores)
    return render(request, "finanzas/quincena.html", ctx)


@router.get("/quincena/linea-nueva")
def quincena_linea_nueva(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/_linea_nueva.html",
                  {"bolsillos": q.bolsillos(con), "deudas": q.deudas(con)})


@router.post("/quincena/confirmar")
async def quincena_confirmar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    neto, lineas, errores, trm_txt = _leer_editor(form)
    fecha = str(form.get("fecha", ""))
    pid = _a_int(form.get("plantilla_id"), 0)
    tipo = str(form.get("tipo", "quincena"))
    error = None
    trm = None
    try:
        if errores:
            raise RepartoInvalido("Corrige los montos marcados.")
        e = _editor(con, neto, lineas)
        if e["pide_trm"]:
            if not trm_txt.strip():
                raise RepartoInvalido("Escribe la TRM para el abono en USD.")
            trm = parse_centavos(trm_txt)
        qid = q.confirmar_quincena(con, fecha, neto, pid or None, lineas, trm, tipo)
        actualizar_resumen_ia(request, con)
        return RedirectResponse(f"/quincena/{qid}?confirmada=1", status_code=303)
    except (RepartoInvalido, MontoInvalido, ErrorDatos) as ex:
        error = str(ex)
    ctx = _ctx_quincena(con, fecha=fecha, plantilla_id=pid, tipo=tipo)
    ctx["editor"] = _editor(con, neto, lineas, trm_txt, errores)
    ctx["error"] = error
    return render(request, "finanzas/quincena.html", ctx, 422)


@router.get("/quincena/{qid}")
def quincena_detalle(request: Request, qid: int, confirmada: int = 0, con: sqlite3.Connection = Con):
    qu = q.quincena(con, qid)
    if not qu:
        return RedirectResponse("/quincena", status_code=303)
    lineas = q.lineas_quincena(con, qid)
    abonos = con.execute(
        "SELECT m.*, d.nombre, d.moneda FROM movimientos_deuda m JOIN deudas d ON d.id = m.deuda_id"
        " WHERE m.quincena_id = ? ORDER BY m.id", (qid,)
    ).fetchall()
    return render(request, "finanzas/quincena_detalle.html", {
        "seccion": "quincena", "q": qu, "lineas": lineas, "abonos": abonos, "confirmada": confirmada,
        "pvr": real.plan_vs_real(con, qid), "tipos": logica.TIPOS_INGRESO,
        "segmentos": q.tira(con, [(l["bolsillo_id"], l["monto"]) for l in lineas]),
    })


# ---------- Deudas ----------

@router.get("/deudas")
def deudas(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/deudas.html", {
        "seccion": "deudas", "estado": q.estado_deudas(con, hoy()), "error": None,
    })


@router.post("/deudas")
async def deuda_crear(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    moneda = str(form.get("moneda", "COP"))
    try:
        q.crear_deuda(con, str(form.get("nombre", "")), moneda, parse_moneda(str(form.get("saldo", "")), moneda))
        return RedirectResponse("/deudas", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        return render(request, "finanzas/deudas.html", {
            "seccion": "deudas", "estado": q.estado_deudas(con, hoy()), "error": str(e),
        }, 422)


def _ctx_deuda(con, deuda_id: int, **extra) -> dict:
    d = q.deuda(con, deuda_id)
    estado = next(e for e in q.estado_deudas(con, hoy()) if e["deuda"]["id"] == deuda_id)
    ctx = {"seccion": "deudas", "d": d, "e": estado, "movs": q.movimientos(con, deuda_id),
           "hoy": hoy().isoformat(), "error_abono": None, "error_ajuste": None, "error_param": None, "ok": None}
    ctx.update(extra)
    return ctx


@router.get("/deudas/{deuda_id}")
def deuda_detalle(request: Request, deuda_id: int, ok: str = "", con: sqlite3.Connection = Con):
    try:
        return render(request, "finanzas/deuda.html", _ctx_deuda(con, deuda_id, ok=ok or None))
    except ErrorDatos:
        return RedirectResponse("/deudas", status_code=303)


@router.post("/deudas/{deuda_id}/abono")
async def deuda_abono(request: Request, deuda_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        d = q.deuda(con, deuda_id)
        fecha = str(form.get("fecha", ""))
        date.fromisoformat(fecha)
        monto = parse_moneda(str(form.get("monto", "")), d["moneda"])
        trm = parse_centavos(str(form.get("trm", ""))) if d["moneda"] == "USD" and str(form.get("trm", "")).strip() else None
        q.abonar(con, deuda_id, fecha, monto, trm=trm, nota=str(form.get("nota", "")).strip())
        return RedirectResponse(f"/deudas/{deuda_id}?ok=abono", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        error = str(e)
    except ValueError:
        error = "La fecha no es válida."
    return render(request, "finanzas/deuda.html", _ctx_deuda(con, deuda_id, error_abono=error), 422)


@router.post("/deudas/{deuda_id}/ajuste")
async def deuda_ajuste(request: Request, deuda_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        d = q.deuda(con, deuda_id)
        fecha = str(form.get("fecha", ""))
        date.fromisoformat(fecha)
        saldo = parse_moneda(str(form.get("saldo", "")), d["moneda"])
        q.ajustar_saldo(con, deuda_id, fecha, saldo, nota=str(form.get("nota", "")).strip())
        return RedirectResponse(f"/deudas/{deuda_id}?ok=ajuste", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        error = str(e)
    except ValueError:
        error = "La fecha no es válida."
    return render(request, "finanzas/deuda.html", _ctx_deuda(con, deuda_id, error_ajuste=error), 422)


# ---------- Metas y foto mensual ----------

def _ctx_metas(con, **extra) -> dict:
    foto = q.ultima_foto(con)
    ctx = {
        "seccion": "futuro", "metas": q.avance_metas(con), "foto": foto,
        "patrimonio": q.patrimonio_foto(con, foto) if foto else None,
        "saldos": q.saldos_foto(con, foto["id"]) if foto else [],
        "serie": q.serie_patrimonio(con), "cuentas": q.cuentas(con), "error": None,
    }
    ctx.update(extra)
    return ctx


@router.get("/metas")
def metas(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/metas.html", _ctx_metas(con))


@router.post("/metas")
async def meta_crear(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        q.crear_meta(con, str(form.get("nombre", "")), parse_cop(str(form.get("objetivo", ""))),
                     [int(c) for c in form.getlist("cuenta_id")])
        return RedirectResponse("/metas", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        return render(request, "finanzas/metas.html", _ctx_metas(con, error=str(e)), 422)


def _ctx_foto(con, **extra) -> dict:
    foto = q.ultima_foto(con)
    previos = {r["id"]: r["saldo"] for r in q.saldos_foto(con, foto["id"])} if foto else {}
    trm = q.ultima_trm(con)
    ctx = {
        "seccion": "futuro", "fecha": hoy().isoformat(), "cuentas": q.cuentas(con), "deudas": q.deudas(con),
        "previos": previos, "trm_txt": "", "trm_sugerida": trm, "valores": {}, "error": None,
    }
    ctx.update(extra)
    return ctx


@router.get("/fotos/nueva")
def foto_nueva(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/foto.html", _ctx_foto(con))


@router.post("/fotos")
async def foto_guardar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    valores = {k: str(v) for k, v in form.items()}
    try:
        saldos = {c["id"]: parse_cop(valores.get(f"cuenta_{c['id']}", "") or "0", permitir_negativo=True)
                  for c in q.cuentas(con)}
        sd = {d["id"]: parse_moneda(valores.get(f"deuda_{d['id']}", "") or "0", d["moneda"])
              for d in q.deudas(con)}
        trm = parse_centavos(valores.get("trm", ""))
        q.guardar_foto(con, valores.get("fecha", ""), trm, saldos, sd)
        return RedirectResponse("/metas", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        ctx = _ctx_foto(con, fecha=valores.get("fecha", ""), trm_txt=valores.get("trm", ""),
                        valores=valores, error=str(e))
        return render(request, "finanzas/foto.html", ctx, 422)


# ---------- Más: bolsillos, plantillas, cuentas, exportar ----------

@router.get("/mas")
def mas(request: Request):
    return render(request, "finanzas/mas.html", {"seccion": "mas"})


@router.get("/bolsillos")
def bolsillos(request: Request, ok: str = "", con: sqlite3.Connection = Con):
    return render(request, "finanzas/bolsillos.html", {
        "seccion": "mas", "bolsillos": q.bolsillos(con), "cuentas": q.cuentas(con),
        "tipos": logica.TIPOS_BOLSILLO, "error": None, "ok": ok or None,
    })


@router.post("/bolsillos")
async def bolsillo_crear(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        q.crear_bolsillo(con, str(form.get("nombre", "")), str(form.get("tipo", "")))
        return RedirectResponse("/bolsillos", status_code=303)
    except ErrorDatos as e:
        return render(request, "finanzas/bolsillos.html", {
            "seccion": "mas", "bolsillos": q.bolsillos(con), "cuentas": q.cuentas(con),
            "tipos": logica.TIPOS_BOLSILLO, "error": str(e),
        }, 422)


@router.post("/cuentas")
async def cuenta_crear(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        q.crear_cuenta(con, str(form.get("nombre", "")))
        return RedirectResponse("/bolsillos#cuentas", status_code=303)
    except ErrorDatos as e:
        return render(request, "finanzas/bolsillos.html", {
            "seccion": "mas", "bolsillos": q.bolsillos(con), "cuentas": q.cuentas(con),
            "tipos": logica.TIPOS_BOLSILLO, "error_cuenta": str(e), "error": None,
        }, 422)


def _ctx_plantilla(con, p, lineas: list[Linea], **extra) -> dict:
    ctx = {"seccion": "mas", "p": p, "lineas": lineas, "bolsillos": q.bolsillos(con),
           "deudas": q.deudas(con), "plantillas": q.plantillas(con), "error": None, "ok": None,
           "fondos_fijos": [x["f"] for x in real.fondos(con, hoy()) if x["aporte_fijo"]]}
    ctx.update(extra)
    return ctx


@router.get("/plantillas/linea-nueva")
def plantilla_linea_nueva(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/_plantilla_linea.html", {
        "l": Linea("", 0, None, "fijo"), "bolsillos": q.bolsillos(con), "deudas": q.deudas(con),
        "fondos_fijos": [x["f"] for x in real.fondos(con, hoy()) if x["aporte_fijo"]],
    })


@router.get("/plantillas/{nombre}")
def plantilla(request: Request, nombre: str, ok: str = "", con: sqlite3.Connection = Con):
    p = q.plantilla_por_nombre(con, nombre)
    if not p:
        return RedirectResponse("/mas", status_code=303)
    return render(request, "finanzas/plantilla.html",
                  _ctx_plantilla(con, p, q.lineas_plantilla(con, p["id"]), ok=ok or None))


@router.post("/plantillas/{nombre}")
async def plantilla_guardar(request: Request, nombre: str, con: sqlite3.Connection = Con):
    p = q.plantilla_por_nombre(con, nombre)
    if not p:
        return RedirectResponse("/mas", status_code=303)
    form = await request.form()
    conceptos, bolsillos_ = form.getlist("concepto"), form.getlist("bolsillo_id")
    modos, montos, deudas_ = form.getlist("modo"), form.getlist("monto"), form.getlist("deuda_id")
    fondos_ = form.getlist("fondo_id")
    lineas, error = [], None
    for i, c in enumerate(conceptos):
        modo = str(modos[i])
        try:
            monto = parse_cop(str(montos[i])) if modo == "fijo" else None
        except MontoInvalido as e:
            monto, error = 0, f"«{c}»: {e}"
        lineas.append(Linea(str(c).strip(), _a_int(bolsillos_[i], 0), monto, modo, _a_int(deudas_[i]),
                            fondo_id=_a_int(fondos_[i] if i < len(fondos_) else None)))
    lineas = [l for l in lineas if l.concepto]
    try:
        if error:
            raise RepartoInvalido(error)
        if any(not l.bolsillo_id for l in lineas):
            raise RepartoInvalido("Cada línea necesita un bolsillo.")
        q.guardar_lineas_plantilla(con, p["id"], lineas)
        return RedirectResponse(f"/plantillas/{nombre}?ok=1", status_code=303)
    except (RepartoInvalido, sqlite3.IntegrityError) as e:
        return render(request, "finanzas/plantilla.html", _ctx_plantilla(con, p, lineas, error=str(e)), 422)


def _info_resumen_ia(request: Request) -> dict:
    cfg = request.app.state.config
    ruta = cfg.exports_path / "resumen-ia.json"
    from datetime import datetime
    # En la demo, la ruta va relativa a su carpeta de datos: la absoluta lleva el usuario del computador.
    visible = f"demo/datos/{ruta.relative_to(cfg.datos_demo)}" if cfg.demo and cfg.datos_demo else str(ruta)
    return {"ruta": visible, "existe": ruta.exists(),
            "generado": datetime.fromtimestamp(ruta.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if ruta.exists() else None}


@router.get("/exportar")
def exportar_vista(request: Request, mes: str = "", ok: str = "", con: sqlite3.Connection = Con):
    mes = mes or hoy().strftime("%Y-%m")
    try:
        md = exportar.resumen_mes(con, mes, hoy())
        error = None
    except ValueError as e:
        md, error = "", str(e)
    return render(request, "finanzas/exportar.html", {"seccion": "mas", "mes": mes, "md": md, "error": error,
                                                      "ia": _info_resumen_ia(request), "ok": ok or None})


@router.post("/exportar/resumen-ia")
def exportar_resumen_ia(request: Request, con: sqlite3.Connection = Con):
    resumen_ia.escribir(con, request.app.state.config.exports_path, hoy())
    return RedirectResponse("/exportar?ok=ia#t-ia", status_code=303)


@router.get("/exportar/{archivo}")
def exportar_descarga(archivo: str, con: sqlite3.Connection = Con):
    mes = archivo.removesuffix("-resumen-finanzas.md").removesuffix(".md")
    try:
        md = exportar.resumen_mes(con, mes, hoy())
    except ValueError as e:
        return PlainTextResponse(str(e), status_code=400)
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{mes}-resumen-finanzas.md"',
    })
