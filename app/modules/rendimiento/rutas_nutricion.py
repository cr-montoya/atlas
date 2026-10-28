"""Rutas de nutrición y metas: registro rápido de comidas por momento, plan vigente y anillos de metas."""

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from . import logica, metas, rutas
from . import nutricion as nu
from .rutas import Con, _int, render

router = APIRouter(prefix="/rendimiento")


def _dia_valido(fecha: str) -> date:
    try:
        d = date.fromisoformat(fecha)
    except (TypeError, ValueError):
        return rutas.hoy()
    return min(d, rutas.hoy())


def _ctx_comida(request: Request, con: sqlite3.Connection, fecha: str, momento: str, error: str | None = None) -> dict:
    plan = nu.plan_vigente(rutas._boveda(request))
    d = nu.dia(con, fecha)
    mp = plan.momento(momento) if plan else None
    grupos = [g for g, _ in mp.intercambios] if mp else list(nu.GRUPOS)
    return {"fecha": fecha, "clave": momento, "nombre": nu.MOMENTOS[momento], "c": d.comidas.get(momento), "mp": mp,
            "grupos": grupos, "plan_n": dict(mp.intercambios) if mp else {}, "error": error, "vault_estado": d.vault_estado,
            "escribe_vault": request.app.state.config.escribir_comidas}


def _despues_de_guardar(request: Request, con: sqlite3.Connection, fecha: str) -> None:
    cfg = request.app.state.config
    if cfg.escribir_comidas:
        try:
            nu.escribir_vault(con, cfg.vault_path, fecha, nu.plan_vigente(cfg.vault_path))
        except Exception:  # noqa: BLE001 - lo guardado en SQLite ya quedó
            rutas.log.exception("No pude escribir las comidas en el inbox del vault")
    rutas.actualizar_resumen(request, con)


@router.get("/comidas")
def comidas(request: Request, fecha: str = "", con: sqlite3.Connection = Con):
    d = _dia_valido(fecha)
    boveda = rutas._boveda(request)
    plan = nu.plan_vigente(boveda)
    lunes, _ = logica.rango_semana(logica.semana_iso(d))
    dia = nu.dia(con, d.isoformat())
    return render(request, "rendimiento/comidas.html", {
        "seccion": "registrar", "d": d, "hoy": rutas.hoy(), "plan": plan, "dia": dia,
        "anterior": (d - timedelta(days=1)).isoformat(), "siguiente": (d + timedelta(days=1)).isoformat(),
        "tarjetas": [_ctx_comida(request, con, d.isoformat(), m) for m in nu.MOMENTOS],
        "semana": nu.semana(con, plan, lunes, rutas.hoy()), "MOMENTOS": nu.MOMENTOS, "VASO_ML": nu.VASO_ML,
        "escribe_vault": request.app.state.config.escribir_comidas,
        "ruta_inbox": nu.ruta_inbox(boveda, d.isoformat()).relative_to(boveda),
    })


@router.post("/comidas/{fecha}/{momento}")
async def comida_guardar(request: Request, fecha: str, momento: str, con: sqlite3.Connection = Con):
    form = await request.form()
    fecha = _dia_valido(fecha).isoformat()
    if momento not in nu.MOMENTOS:
        return RedirectResponse(f"/rendimiento/comidas?fecha={fecha}", status_code=303)
    accion = str(form.get("accion") or "guardar")
    error = None
    try:
        if accion == "borrar":
            nu.borrar_comida(con, fecha, momento)
        else:
            plan = nu.plan_vigente(rutas._boveda(request))
            mp = plan.momento(momento) if plan else None
            if accion == "plan" and mp:
                inter, segun = dict(mp.intercambios), True
            else:
                inter = {g: _int(form.get(f"i_{g}"), 0) for g in nu.GRUPOS}
                segun = False
            nu.guardar_comida(con, fecha, momento, str(form.get("hora") or ""), str(form.get("texto") or ""), inter, segun)
    except nu.RegistroInvalido as err:
        error = str(err)
    if not error:
        _despues_de_guardar(request, con, fecha)
    if request.headers.get("HX-Request"):
        return render(request, "rendimiento/_comida.html", _ctx_comida(request, con, fecha, momento, error), 422 if error else 200)
    return RedirectResponse(f"/rendimiento/comidas?fecha={fecha}#c-{momento}", status_code=303)


@router.post("/comidas/{fecha}")
async def dia_guardar(request: Request, fecha: str, con: sqlite3.Connection = Con):
    form = await request.form()
    fecha = _dia_valido(fecha).isoformat()
    actual = nu.dia(con, fecha)
    paso = _int(form.get("agua"))
    error = None
    try:
        if paso is not None:
            nu.guardar_dia(con, fecha, agua_vasos=max(0, (actual.agua_vasos or 0) + (1 if paso > 0 else -1)))
        else:
            nu.guardar_dia(con, fecha, suplementos=str(form.get("suplementos") or ""), notas=str(form.get("notas") or ""))
    except nu.RegistroInvalido as err:
        error = str(err)
    if not error:
        _despues_de_guardar(request, con, fecha)
    if request.headers.get("HX-Request") and paso is not None:
        return render(request, "rendimiento/_agua.html", {"dia": nu.dia(con, fecha), "plan": nu.plan_vigente(rutas._boveda(request)),
                                                          "VASO_ML": nu.VASO_ML, "error": error})
    return RedirectResponse(f"/rendimiento/comidas?fecha={fecha}#dia", status_code=303)


@router.get("/metas")
def ver_metas(request: Request, con: sqlite3.Connection = Con):
    return render(request, "rendimiento/metas.html", {
        "seccion": "analisis", "hoy": rutas.hoy(), **metas.construir(con, rutas._boveda(request), rutas.hoy())})
