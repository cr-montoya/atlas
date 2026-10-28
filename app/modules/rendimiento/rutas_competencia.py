"""Rutas de la competencia: cuenta regresiva, plan del vault, pesajes, guion de combate y checklist del día."""

import sqlite3
from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from . import competencia as comp
from . import evaluaciones as ev
from . import rutas
from .rutas import Con, render

router = APIRouter(prefix="/rendimiento")


def _referencia(con: sqlite3.Connection, boveda) -> dict | None:
    """El último peso de un test (gimnasio u otro método), aparte de los pesajes en casa: otra condición."""
    con_peso = [m for m in ev.todas(con, boveda) if m.tipo == "antropometria" and "Peso" in m.valores]
    if not con_peso:
        return None
    m = max(con_peso, key=lambda x: x.fecha)
    return {"fecha": m.fecha, "g": m.valores["Peso"].valor_mil, "metodo": m.metodo}


def _ctx_checklist(con: sqlite3.Connection, c: comp.Competencia) -> dict:
    hechas = comp.marcas(con, c)
    return {"c": c, "hechas": hechas, "n_hechas": sum(1 for i in c.checklist if i in hechas)}


def _ctx(request: Request, con: sqlite3.Connection, error: str = "", form: dict | None = None) -> dict:
    boveda = rutas._boveda(request)
    momento = comp.ahora()
    hoy = momento.date()
    comp.borrar_marcas_pasadas(con, hoy)
    lectura = comp.vigente(boveda, hoy)
    c = lectura.competencia
    if not comp.activa(c, hoy):
        return {"seccion": "mas", "c": None, "pasada": c, "error_vault": lectura.error}
    todos = comp.pesajes(con)
    desde = (c.torneo.date() - timedelta(days=comp.VENTANA_GRAFICA)).isoformat()
    ultimo = todos[-1] if todos else None
    cuenta_pesaje, cuenta_torneo = comp.cuentas(c, momento)
    return {
        "seccion": "mas", "c": c, "hoy": hoy, "error": error, "form": form or {},
        "cuenta_pesaje": cuenta_pesaje, "cuenta_torneo": cuenta_torneo, "plan_hoy": c.dia(hoy),
        "pesajes": todos, "ultimo": ultimo,
        "frente": comp.frente_al_limite(ultimo.peso_g, c.limite_g) if ultimo and c.limite_g else "",
        "proximo": comp.proximo_pesaje_casa(c, hoy), "referencia": _referencia(con, boveda),
        "grafica": [{"fecha": p.fecha, "v": p.peso_g} for p in todos if p.fecha >= desde], "meta": c.meta_peso,
        "CONDICIONES": comp.CONDICIONES, **_ctx_checklist(con, c),
    }


@router.get("/competencia")
def ver(request: Request, con: sqlite3.Connection = Con):
    return render(request, "rendimiento/competencia.html", _ctx(request, con))


@router.post("/competencia/pesajes")
async def pesaje_guardar(request: Request, con: sqlite3.Connection = Con):
    form = {k: str(v) for k, v in (await request.form()).items()}
    if form.get("accion") == "borrar":
        if comp.borrar_pesaje(con, form.get("fecha", "")):
            rutas.actualizar_resumen(request, con)
        return RedirectResponse("/rendimiento/competencia#pesajes", status_code=303)
    try:
        comp.guardar_pesaje(con, comp.ahora().date(), form.get("fecha", ""), form.get("hora", ""), form.get("peso", ""),
                            form.get("condicion", ""), form.get("nota", ""))
    except comp.PesajeInvalido as err:
        return render(request, "rendimiento/competencia.html", _ctx(request, con, str(err), form), 422)
    rutas.actualizar_resumen(request, con)
    return RedirectResponse("/rendimiento/competencia#pesajes", status_code=303)


@router.post("/competencia/checklist")
async def checklist_marcar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    hoy = comp.ahora().date()
    c = comp.vigente(rutas._boveda(request), hoy).competencia
    if comp.activa(c, hoy):
        comp.marcar(con, c, str(form.get("item") or ""), form.get("marcado") == "1")
        if request.headers.get("HX-Request"):
            return render(request, "rendimiento/_checklist.html", {**_ctx_checklist(con, c), "parcial": True})
    return RedirectResponse("/rendimiento/competencia#checklist", status_code=303)
