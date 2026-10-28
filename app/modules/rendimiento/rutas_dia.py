"""Rutas de Cómo me sentí (formulario e historial) y de la vista del día."""

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import consultas as q
from . import dia as dia_mod
from . import rutas, vault
from . import sensaciones as sen
from .rutas import Con, render

router = APIRouter(prefix="/rendimiento")

VOLVER = ("hoy", "historial", "dia")


def _volver(valor) -> str:
    return valor if valor in VOLVER else "hoy"


def _destino(volver: str, fecha: str) -> str:
    return {"hoy": "/rendimiento", "historial": "/rendimiento/sensaciones/historial",
            "dia": f"/rendimiento/dia/{fecha}"}[volver]


def _ctx_form(fecha: str | None, volver: str, fila: dict | None, error: str = "") -> dict:
    h = rutas.hoy()
    d = date.fromisoformat(fecha) if fecha else None
    return {"seccion": "mas", "fecha": fecha, "d": d, "nombre": sen.nombre_dia(d, h) if d else "", "volver": volver,
            "destino": _destino(volver, fecha or h.isoformat()), "fila": {**{k: None for k in sen.CAMPOS}, "sintomas": [], **(fila or {})}, "error": error,
            "ESCALAS": sen.ESCALAS, "SINTOMAS": sen.SINTOMAS, "SIN_ENTRENO": sen.SIN_ENTRENO, "MAX": sen.MAX}


@router.get("/sensaciones")
def sensaciones_form(request: Request, fecha: str = "", volver: str = "", con: sqlite3.Connection = Con):
    volver = _volver(volver)
    try:
        f = sen.fecha_editable(fecha or rutas.hoy().isoformat(), rutas.hoy())
    except sen.SensacionInvalida as err:
        return render(request, "rendimiento/sensaciones.html", _ctx_form(None, volver, None, str(err)), 422)
    return render(request, "rendimiento/sensaciones.html", _ctx_form(f, volver, sen.leer(con, f)))


def _escala(crudo) -> int | None:
    t = str(crudo or "").strip()
    if not t:
        return None
    try:
        return int(t)
    except ValueError:
        raise sen.SensacionInvalida("Las escalas van de 1 a 5") from None


@router.post("/sensaciones")
async def sensaciones_guardar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    volver = _volver(form.get("volver"))
    try:
        f = sen.fecha_editable(form.get("fecha"), rutas.hoy())
    except sen.SensacionInvalida as err:
        return render(request, "rendimiento/sensaciones.html", _ctx_form(None, volver, None, str(err)), 422)
    sintomas = [str(s) for s in form.getlist("sintomas")]
    campos = {"sintomas": sintomas, "sin_entreno": str(form.get("sin_entreno") or "") or None}
    for k in ("sintomas_otros", "dolor", "notas"):
        campos[k] = " ".join(str(form.get(k) or "").split()) or None
    try:
        for k in sen.CLAVES_ESCALA:
            campos[k] = _escala(form.get(k))
        sen.validar(campos)
        sen.guardar(con, f, **campos)   # el relato se conserva: no viene del formulario
    except sen.SensacionInvalida as err:
        fila = {**(sen.leer(con, f) or {}), **{k: v for k, v in campos.items() if k in sen.CAMPOS}}
        for k in sen.CLAVES_ESCALA:
            if not isinstance(fila.get(k), int):
                fila[k] = None
        return render(request, "rendimiento/sensaciones.html", _ctx_form(f, volver, fila, str(err)), 422)
    return RedirectResponse(_destino(volver, f), status_code=303)


@router.get("/sensaciones/historial")
def sensaciones_historial(request: Request, con: sqlite3.Connection = Con):
    h = rutas.hoy()
    imp = vault.importar(rutas._boveda(request))
    desde = h - timedelta(days=sen.DIAS_HISTORIAL - 1)
    sesiones = q.sesiones_entre(con, desde.isoformat(), h.isoformat())
    return render(request, "rendimiento/sensaciones_historial.html", {
        "seccion": "mas", "dias": sen.historial(con, imp, h, sesiones), "ESCALAS": sen.ESCALAS, "SINTOMAS": sen.SINTOMAS,
        "SIN_ENTRENO_TXT": sen.SIN_ENTRENO_TXT, "es_bajo": sen.es_bajo, "fmt_sueno": sen.fmt_sueno,
        "HRV_ESTADOS": vault.HRV_ESTADOS,
    })


@router.get("/dia/{fecha}")
def dia(request: Request, fecha: str, con: sqlite3.Connection = Con):
    if not sen.FECHA.fullmatch(fecha):
        return HTMLResponse("Fecha no válida", status_code=422)
    try:
        f = date.fromisoformat(fecha).isoformat()
    except ValueError:
        return HTMLResponse("Fecha no válida", status_code=422)
    try:
        ctx = dia_mod.construir(con, rutas._boveda(request), f, rutas.hoy())
    except dia_mod.FechaFuera:
        return HTMLResponse("Ese día no está en el calendario", status_code=404)
    return render(request, "rendimiento/dia.html", {
        "seccion": "hoy", **ctx, "ESCALAS": sen.ESCALAS, "SINTOMAS": sen.SINTOMAS, "SIN_ENTRENO_TXT": sen.SIN_ENTRENO_TXT,
        "es_bajo": sen.es_bajo, "fmt_sueno": sen.fmt_sueno, "HRV_ESTADOS": vault.HRV_ESTADOS, "MOMENTOS": dia_mod.nu.MOMENTOS,
        "VASO_ML": dia_mod.nu.VASO_ML,
    })
