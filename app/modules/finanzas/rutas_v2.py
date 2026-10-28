"""Rutas de v2: plan vs real, gasto rápido, fondos, eventos, futuro (proyección) y revisión."""

import sqlite3
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.core.dinero import MontoInvalido, fmt_cop, parse_cop, parse_tasa

from . import consultas as q
from . import futuro as fu
from . import real
from .consultas import ErrorDatos
from . import rutas as _rutas
from .rutas import Con, _a_int, actualizar_resumen_ia, render

router = APIRouter()


def hoy() -> date:
    return _rutas.hoy()


def _es_htmx(request: Request) -> bool:
    return bool(request.headers.get("HX-Request"))


def _monto_opcional(txt: str) -> int | None:
    txt = (txt or "").strip()
    return parse_cop(txt) if txt else None


# ---------- Plan vs real ----------

def _fila(request, con, linea_id: int, error: str | None = None, editar: bool = False):
    l = real.linea(con, linea_id)
    return render(request, "finanzas/_fila_real.html", {"l": l, "error": error, "editar": editar,
                                                         "pvr": real.plan_vs_real(con, l["quincena_id"]), "oob": True})


@router.post("/lineas/{linea_id}/pagada")
def linea_pagada(request: Request, linea_id: int, con: sqlite3.Connection = Con):
    l = real.linea(con, linea_id)
    if not l:
        return RedirectResponse("/quincena", status_code=303)
    if l["real"] is None:
        real.marcar_pago(con, linea_id, hoy().isoformat())
    else:
        real.quitar_pago(con, linea_id)
    if _es_htmx(request):
        return _fila(request, con, linea_id)
    return RedirectResponse(f"/quincena/{l['quincena_id']}", status_code=303)


@router.get("/lineas/{linea_id}/real")
def linea_real_form(request: Request, linea_id: int, con: sqlite3.Connection = Con):
    return _fila(request, con, linea_id, editar=True)


@router.get("/lineas/{linea_id}")
def linea_fila(request: Request, linea_id: int, con: sqlite3.Connection = Con):
    return _fila(request, con, linea_id)


@router.post("/lineas/{linea_id}/real")
async def linea_real(request: Request, linea_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    l = real.linea(con, linea_id)
    if not l:
        return RedirectResponse("/quincena", status_code=303)
    try:
        real.marcar_pago(con, linea_id, str(form.get("fecha") or hoy().isoformat()), parse_cop(str(form.get("real", ""))))
    except (MontoInvalido, ErrorDatos) as e:
        if _es_htmx(request):
            return _fila(request, con, linea_id, error=str(e), editar=True)
    if _es_htmx(request):
        return _fila(request, con, linea_id)
    return RedirectResponse(f"/quincena/{l['quincena_id']}", status_code=303)


# ---------- Gasto rápido ----------

def _ctx_gasto(con, **extra) -> dict:
    h = hoy()
    ctx = {"seccion": "quincena", "bolsillos": q.bolsillos(con), "categorias": real.categorias(con),
           "recientes": real.gastos(con, date.fromordinal(h.toordinal() - 30).isoformat(), h.isoformat())[:10],
           "valores": {}, "error": None, "ok": None, "fecha": h.isoformat()}
    libres = [b for b in ctx["bolsillos"] if b["tipo"] == "libre"]
    ctx["bolsillo_defecto"] = (libres or ctx["bolsillos"] or [{"id": 0}])[0]["id"]
    ctx.update(extra)
    return ctx


@router.get("/gasto")
def gasto_form(request: Request, ok: str = "", con: sqlite3.Connection = Con):
    return render(request, "finanzas/gasto.html", _ctx_gasto(con, ok=ok or None))


@router.post("/gasto")
async def gasto_guardar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    valores = {k: str(v) for k, v in form.items()}
    try:
        txt = valores.get("monto", "")
        if not txt.strip():
            raise MontoInvalido("Escribe el monto del gasto.")
        real.crear_gasto(con, valores.get("fecha") or hoy().isoformat(), parse_cop(txt),
                         _a_int(valores.get("bolsillo_id"), 0), _a_int(valores.get("categoria_id")),
                         valores.get("nota", ""))
        return RedirectResponse("/gasto?ok=1", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        return render(request, "finanzas/gasto.html", _ctx_gasto(con, valores=valores, error=str(e)), 422)


@router.post("/gastos/{gasto_id}/borrar")
def gasto_borrar(gasto_id: int, con: sqlite3.Connection = Con):
    real.borrar_gasto(con, gasto_id)
    return RedirectResponse("/gasto", status_code=303)


# ---------- Futuro: proyección, escenario, metas y fondos ----------

ESC_MONTOS = ("neto_quincena", "gasto_basico", "tarjeta_mes", "libre", "ahorro_mensual", "meta_m4")
# Perfiles de gasto libre total (Tarjeta Uno, efectivo libre) al mes. El base del usuario es el punto medio.
PERFILES = {"disciplinado": (1_000_000, 300_000), "medio": (1_250_000, 500_000), "relajado": (1_500_000, 800_000)}


def _leer_escenario(form) -> tuple[dict, dict]:
    cambios, errores = {}, {}
    for k in ESC_MONTOS:
        if k in form:
            try:
                cambios[k] = parse_cop(str(form.get(k) or "0"))
            except MontoInvalido as e:
                errores[k] = str(e)
    if form.get("perfil") in PERFILES:
        cambios["tarjeta_mes"], cambios["libre"] = PERFILES[str(form.get("perfil"))]
    if "estrategia" in form:
        cambios["estrategia"] = str(form.get("estrategia"))
    if "meses" in form:
        cambios["meses"] = _a_int(form.get("meses"), 24)
    cambios["incluir_extra"] = 1 if form.get("incluir_extra") else 0
    if "inversion_ea" in form:
        cambios["topar_en_m4"] = 1 if form.get("topar_en_m4") else 0
        try:
            cambios["inversion_ea_ppm"] = parse_tasa(str(form.get("inversion_ea") or "0"))
        except MontoInvalido as e:
            errores["inversion_ea"] = str(e)
    if "sobrante" in form:
        cambios["sobrante_a_ahorro"] = 1 if form.get("sobrante") == "ahorro" else 0
    cambios["incapacidad_activa"] = 1 if form.get("incapacidad_activa") else 0
    if "incapacidad_inicio" in form:
        cambios["incapacidad_inicio"] = str(form.get("incapacidad_inicio") or "")
    if "incapacidad_meses" in form:
        cambios["incapacidad_meses"] = max(1, _a_int(form.get("incapacidad_meses"), 1))
    if "retencion" in form:
        try:
            cambios["retencion_ppm"] = parse_tasa(str(form.get("retencion") or "0"))
        except MontoInvalido as e:
            errores["retencion"] = str(e)
    if "incapacidad_pct" in form:
        try:
            cambios["incapacidad_pct_ppm"] = parse_tasa(str(form.get("incapacidad_pct") or "0"))  # 66,67 % = 666.700 ppm
        except MontoInvalido as e:
            errores["incapacidad_pct"] = str(e)
    return cambios, errores


def _ctx_proyeccion(con, cambios: dict | None = None, errores: dict | None = None) -> dict:
    h = hoy()
    entrada, esc, avisos = real.entrada_proyeccion(con, h, cambios)
    p = fu.proyectar(entrada)
    comp = [fu.comparar_estrategia(entrada.deudas, _pago_deudas(p), e) for e in ("avalancha", "bola")]
    return {"p": p, "esc": esc, "avisos": avisos + p.avisos, "comparacion": comp,
            "rend": real.comparacion_rendimiento(con),
            "pago_deudas": _pago_deudas(p), "errores": errores or {},
            "serie": [{"mes": m.clave, "patrimonio": m.patrimonio, "emergencia": m.emergencia,
                       "deuda": m.deuda_total, "inversion": m.inversion, "eventos": m.eventos} for m in p.meses],
            "incapacidad": [m.clave for m in p.meses if esc["incapacidad_activa"]
                            and m.clave in fu._meses_incapacidad((esc["incapacidad_inicio"], esc["incapacidad_meses"], 1))],
            "meta1": entrada.meta1, "meta_m4": esc["meta_m4"], "perfiles": PERFILES}


def _pago_deudas(p: fu.Proyeccion) -> int:
    """Promedio mensual destinado a deudas en los meses con deuda (para comparar estrategias)."""
    meses = [sum(m.abonos.values()) for m in p.meses if sum(m.abonos.values()) > 0]
    return sum(meses) // len(meses) if meses else 0


@router.get("/futuro")
def futuro(request: Request, ok: str = "", con: sqlite3.Connection = Con):
    h = hoy()
    ctx = _ctx_proyeccion(con)
    ctx.update({"seccion": "futuro", "metas": q.avance_metas(con), "fondos": real.fondos(con, h),
                "eventos": real.eventos(con), "foto": q.ultima_foto(con), "ok": ok or None})
    return render(request, "finanzas/futuro.html", ctx)


@router.post("/futuro/proyeccion")
async def futuro_proyeccion(request: Request, con: sqlite3.Connection = Con):
    cambios, errores = _leer_escenario(await request.form())
    return render(request, "finanzas/_proyeccion.html", _ctx_proyeccion(con, cambios, errores))


@router.post("/futuro/escenario")
async def futuro_escenario(request: Request, con: sqlite3.Connection = Con):
    cambios, errores = _leer_escenario(await request.form())
    try:
        if errores:
            raise ErrorDatos("Corrige los montos marcados.")
        real.guardar_escenario(con, cambios)
        actualizar_resumen_ia(request, con)
        return RedirectResponse("/futuro?ok=escenario#t-proyeccion", status_code=303)
    except ErrorDatos as e:
        ctx = _ctx_proyeccion(con, cambios, errores)
        ctx.update({"seccion": "futuro", "metas": q.avance_metas(con), "fondos": real.fondos(con, hoy()),
                    "eventos": real.eventos(con), "foto": q.ultima_foto(con), "ok": None, "error_escenario": str(e)})
        return render(request, "finanzas/futuro.html", ctx, 422)


# ---------- Fondos ----------

def _ctx_fondo(con, f=None, **extra) -> dict:
    ctx = {"seccion": "futuro", "f": f, "bolsillos": q.bolsillos(con), "error": None, "valores": {},
           "movs": con.execute("SELECT * FROM fondo_movimientos WHERE fondo_id = ? ORDER BY fecha DESC, id DESC LIMIT 20",
                               (f["id"],)).fetchall() if f else [],
           "estado": next((x for x in real.fondos(con, hoy()) if f and x["f"]["id"] == f["id"]), None),
           "hoy": hoy().isoformat()}
    ctx.update(extra)
    return ctx


@router.get("/fondos/nuevo")
def fondo_nuevo(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/fondo.html", _ctx_fondo(con))


@router.get("/fondos/{fondo_id}")
def fondo_ver(request: Request, fondo_id: int, ok: str = "", con: sqlite3.Connection = Con):
    try:
        return render(request, "finanzas/fondo.html", _ctx_fondo(con, real.fondo(con, fondo_id), ok=ok or None))
    except ErrorDatos:
        return RedirectResponse("/futuro", status_code=303)


@router.post("/fondos")
@router.post("/fondos/{fondo_id}")
async def fondo_guardar(request: Request, fondo_id: int | None = None, con: sqlite3.Connection = Con):
    form = await request.form()
    valores = {k: str(v) for k, v in form.items()}
    try:
        fid = real.guardar_fondo(
            con, valores.get("nombre", ""), parse_cop(valores.get("objetivo") or "0"),
            valores.get("fecha_objetivo") or None, _a_int(valores.get("cada_meses")),
            _a_int(valores.get("bolsillo_id"), 0), bool(valores.get("estimado")), fondo_id,
            parse_cop(valores.get("aporte_mensual") or "0"), _monto_opcional(valores.get("aporte_proximo", "")))
        return RedirectResponse(f"/fondos/{fid}?ok=guardado", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        f = real.fondo(con, fondo_id) if fondo_id else None
        return render(request, "finanzas/fondo.html", _ctx_fondo(con, f, error=str(e), valores=valores), 422)


@router.post("/fondos/{fondo_id}/uso")
async def fondo_uso(request: Request, fondo_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        real.usar_fondo(con, fondo_id, str(form.get("fecha", "")), parse_cop(str(form.get("monto", ""))),
                        str(form.get("nota", "")).strip())
        return RedirectResponse(f"/fondos/{fondo_id}?ok=uso", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        return render(request, "finanzas/fondo.html", _ctx_fondo(con, real.fondo(con, fondo_id), error_uso=str(e)), 422)


# ---------- Eventos ----------

def _ctx_evento(con, ev=None, **extra) -> dict:
    ctx = {"seccion": "futuro", "ev": ev, "deudas": q.deudas(con), "fondos": [x["f"] for x in real.fondos(con, hoy())],
           "error": None, "valores": {}}
    ctx.update(extra)
    return ctx


@router.get("/eventos/nuevo")
def evento_nuevo(request: Request, con: sqlite3.Connection = Con):
    return render(request, "finanzas/evento.html", _ctx_evento(con))


@router.get("/eventos/{evento_id}")
def evento_ver(request: Request, evento_id: int, con: sqlite3.Connection = Con):
    ev = con.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone()
    if not ev:
        return RedirectResponse("/futuro", status_code=303)
    return render(request, "finanzas/evento.html", _ctx_evento(con, ev))


@router.post("/eventos")
@router.post("/eventos/{evento_id}")
async def evento_guardar(request: Request, evento_id: int | None = None, con: sqlite3.Connection = Con):
    form = await request.form()
    v = {k: str(x) for k, x in form.items()}
    try:
        real.guardar_evento(con, v.get("nombre", ""), v.get("fecha", ""), v.get("tipo", ""),
                            _monto_opcional(v.get("monto", "")), bool(v.get("estimado")),
                            _a_int(v.get("deuda_id")), _a_int(v.get("fondo_id")),
                            "extra" if v.get("solo_extra") else "", v.get("nota", "").strip(), evento_id)
        return RedirectResponse("/futuro#t-eventos", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        ev = con.execute("SELECT * FROM eventos WHERE id = ?", (evento_id,)).fetchone() if evento_id else None
        return render(request, "finanzas/evento.html", _ctx_evento(con, ev, error=str(e), valores=v), 422)


@router.post("/eventos/{evento_id}/borrar")
def evento_borrar(evento_id: int, con: sqlite3.Connection = Con):
    real.borrar_evento(con, evento_id)
    return RedirectResponse("/futuro#t-eventos", status_code=303)


# ---------- Rendimiento de una cuenta ----------

@router.post("/cuentas/{cuenta_id}/rendimiento")
async def cuenta_rendimiento(request: Request, cuenta_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        txt = str(form.get("ea", "")).strip()
        real.guardar_rendimiento(con, cuenta_id, parse_tasa(txt) if txt else None, str(form.get("nota", "")))
        return RedirectResponse("/bolsillos?ok=rendimiento#cuentas", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        return render(request, "finanzas/bolsillos.html", {
            "seccion": "mas", "bolsillos": q.bolsillos(con), "cuentas": q.cuentas(con),
            "tipos": __import__("app.modules.finanzas.logica", fromlist=["x"]).TIPOS_BOLSILLO,
            "error": None, "error_rend": str(e), "error_rend_id": cuenta_id}, 422)


# ---------- Tasa y cuota de una deuda ----------

@router.post("/deudas/{deuda_id}/parametros")
async def deuda_parametros(request: Request, deuda_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        tasa_txt = str(form.get("tasa", "")).strip()
        real.actualizar_deuda(con, deuda_id, parse_tasa(tasa_txt) if tasa_txt else None,
                              parse_cop(str(form.get("cuota") or "0")), bool(form.get("prepagar")))
        return RedirectResponse(f"/deudas/{deuda_id}?ok=parametros", status_code=303)
    except (MontoInvalido, ErrorDatos) as e:
        from .rutas import _ctx_deuda
        return render(request, "finanzas/deuda.html", _ctx_deuda(con, deuda_id, error_param=str(e)), 422)


# ---------- Revisión mensual ----------

@router.get("/revision")
def revision(request: Request, mes: str = "", ok: str = "", con: sqlite3.Connection = Con):
    mes = mes or hoy().strftime("%Y-%m")
    return render(request, "finanzas/revision.html", {
        "seccion": "mas", "mes": mes, "r": real.revision(con, mes), "preguntas": real.PREGUNTAS,
        "ok": ok or None, "error": None, "valores": {}})


@router.post("/revision")
async def revision_guardar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    v = {k: str(x) for k, x in form.items()}
    mes = v.get("mes", "")
    try:
        real.guardar_revision(con, mes, {**v, "sensacion": _a_int(v.get("sensacion"))})
        actualizar_resumen_ia(request, con)
        return RedirectResponse(f"/revision?mes={mes}&ok=1", status_code=303)
    except ErrorDatos as e:
        return render(request, "finanzas/revision.html", {
            "seccion": "mas", "mes": mes, "r": None, "preguntas": real.PREGUNTAS, "ok": None,
            "error": str(e), "valores": v}, 422)


__all__ = ["router", "fmt_cop"]
