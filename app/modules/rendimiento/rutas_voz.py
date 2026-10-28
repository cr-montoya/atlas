"""Rutas del registro por voz: grabar o escribir, progreso, borrador editable, repreguntas y guardar."""

import json
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.core.demo import exigir_externo
from . import consultas as q
from . import nutricion as nu
from . import sensaciones as sen
from . import rutas, voz
from .rutas import Con, render

router = APIRouter(prefix="/rendimiento")


def _mismo_origen(request: Request) -> bool:
    """La cookie de sesión es samesite=lax; además, un POST de voz con Origin de otro host se rechaza."""
    origen = request.headers.get("origin")
    if not origen or origen == "null":
        return True
    return urlparse(origen).netloc == request.headers.get("host", "")


def _prohibido():
    return HTMLResponse("Origen no permitido", status_code=403)


def _ctx_portada(request: Request, con: sqlite3.Connection, error: str = "", texto: str = "") -> dict:
    voz.retener(con, rutas.hoy())
    return {"seccion": "registrar", "historial": voz.historial(con), "activa": voz.activa(con), "error": error,
            "texto": texto, "max_texto": voz.MAX_TEXTO}


@router.get("/voz")
def portada(request: Request, con: sqlite3.Connection = Con):
    return render(request, "rendimiento/voz.html", _ctx_portada(request, con))


def _ocupado(err: voz.Ocupado, json_: bool = False):
    url = f"/rendimiento/voz/{err.entrada_id}?ocupado=1"
    return JSONResponse({"url": url, "error": str(err)}, status_code=409) if json_ else RedirectResponse(url, status_code=303)


@router.post("/voz")
async def enviar_texto(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "voz")
    if not _mismo_origen(request):
        return _prohibido()
    form = await request.form()
    texto = " ".join(str(form.get("texto") or "").split())
    if not texto:
        return render(request, "rendimiento/voz.html", _ctx_portada(request, con, "Escribe qué comiste o entrenaste"), 422)
    if len(texto) > voz.MAX_TEXTO:
        return render(request, "rendimiento/voz.html",
                      _ctx_portada(request, con, f"El texto pasa de {voz.MAX_TEXTO} caracteres", texto[:voz.MAX_TEXTO]), 422)
    try:
        eid = voz.crear(con, rutas.hoy().isoformat(), texto)
    except voz.Ocupado as err:
        return _ocupado(err)
    voz.lanzar(request.app.state.config, eid)
    return RedirectResponse(f"/rendimiento/voz/{eid}", status_code=303)


async def _recibir_audio(request: Request) -> Path | JSONResponse:
    """Escribe el cuerpo crudo a un archivo 0600, cortando a los 10 MB; el formato sale de los primeros bytes."""
    carpeta = voz.carpeta_tmp(request.app.state.config)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{uuid.uuid4().hex}.audio"
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    total = 0
    cabecera = b""
    try:
        with os.fdopen(fd, "wb") as f:
            async for trozo in request.stream():
                total += len(trozo)
                if total > voz.MAX_AUDIO:
                    raise OverflowError
                if len(cabecera) < 12:
                    cabecera += trozo[:12 - len(cabecera)]
                f.write(trozo)
    except OverflowError:
        ruta.unlink(missing_ok=True)
        return JSONResponse({"error": "El audio pasa de 10 MB"}, status_code=413)
    except Exception:
        ruta.unlink(missing_ok=True)
        raise
    if total == 0 or voz.formato(cabecera) is None:
        ruta.unlink(missing_ok=True)
        return JSONResponse({"error": "Ese formato de audio no lo reconozco"}, status_code=422)
    return ruta


@router.post("/voz/audio")
async def enviar_audio(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "voz")
    if not _mismo_origen(request):
        return _prohibido()
    if (ya := voz.activa(con)) is not None:
        return _ocupado(voz.Ocupado(ya["id"]), True)
    ruta = await _recibir_audio(request)
    if isinstance(ruta, JSONResponse):
        return ruta
    try:
        eid = voz.crear(con, rutas.hoy().isoformat())
    except voz.Ocupado as err:
        ruta.unlink(missing_ok=True)
        return _ocupado(err, True)
    voz.lanzar(request.app.state.config, eid, ruta)
    return JSONResponse({"url": f"/rendimiento/voz/{eid}"})


def _ctx_entrada(request: Request, con: sqlite3.Connection, e: sqlite3.Row, items: list[dict] | None = None,
                 error: str = "") -> dict:
    cfg = request.app.state.config
    rondas = json.loads(e["rondas"] or "[]")
    b = voz.borrador(e)
    ctx = {"seccion": "registrar", "e": e, "rondas": rondas, "error": error or (e["error"] or ""),
           "procesando": e["estado"] in voz.ACTIVAS, "ocupado": request.query_params.get("ocupado") == "1"}
    if e["estado"] == "borrador":
        items = items if items is not None else b["items"]
        vctx = voz.Contexto.crear(con, cfg.vault_path, e["fecha_base"], rondas)
        tarjetas = voz.validar(vctx, items)
        desde, hasta = voz._rango(vctx)
        ctx.update({
            "tarjetas": tarjetas, "pregunta": b.get("pregunta") if len(rondas) < voz.MAX_RONDAS else None,
            "ultima_ronda": len(rondas) >= voz.MAX_RONDAS, "bloqueada": any(t.bloqueada for t in tarjetas),
            "ejercicios": q.ejercicios(con), "tecnicas": {d: q.tecnicas_por_familia(con, d) for d in q.DISCIPLINAS_COMBATE},
            "MOMENTOS": nu.MOMENTOS, "GRUPOS": nu.GRUPOS, "TIPOS_BLOQUE": q.TIPOS_BLOQUE, "RESULTADOS": q.RESULTADOS,
            "SITUACIONES": q.SITUACIONES, "CON_RESULTADO": q.CON_RESULTADO, "fecha_min": desde.isoformat(),
            "fecha_max": hasta.isoformat(), "VASO_ML": nu.VASO_ML,
            "ESCALAS": sen.ESCALAS, "SINTOMAS": sen.SINTOMAS, "SIN_ENTRENO": sen.SIN_ENTRENO, "DIAS": voz.DIAS,
        })
    elif e["estado"] == "guardada":
        ctx["registros"] = json.loads(e["registros"] or "[]")
    return ctx


def _entrada(con: sqlite3.Connection, entrada_id: int):
    e = voz.entrada(con, entrada_id)
    return e


@router.get("/voz/{entrada_id:int}")
def ver(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    e = _entrada(con, entrada_id)
    if e is None:
        return RedirectResponse("/rendimiento/voz", status_code=303)
    return render(request, "rendimiento/voz_entrada.html", _ctx_entrada(request, con, e))


@router.get("/voz/{entrada_id:int}/estado")
def estado(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    e = _entrada(con, entrada_id)
    if e is None or e["estado"] not in voz.ACTIVAS:
        return HTMLResponse("", headers={"HX-Refresh": "true"})
    return render(request, "rendimiento/_voz_estado.html", {"e": e, "procesando": True})


def _items_del_form(e: sqlite3.Row, form) -> list[dict]:
    return voz.desde_formulario(form, voz.borrador(e)["items"])


def _guardar_borrador(con: sqlite3.Connection, e: sqlite3.Row, items: list[dict]) -> None:
    b = voz.borrador(e)
    with con:
        con.execute("UPDATE voz_entradas SET borrador = ?, error = NULL, actualizada = datetime('now', 'localtime')"
                    " WHERE id = ? AND estado = 'borrador'",
                    (voz._json_borrador(items, b.get("pregunta"), b.get("preguntados") or []), e["id"]))


@router.post("/voz/{entrada_id:int}/editar")
async def editar(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    """Guarda las ediciones del borrador; con `quitar`, además quita un ítem, ejercicio, serie, bloque o entrada."""
    if not _mismo_origen(request):
        return _prohibido()
    e = _entrada(con, entrada_id)
    if e is None or e["estado"] != "borrador":
        return RedirectResponse(f"/rendimiento/voz/{entrada_id}", status_code=303)
    form = await request.form()
    items = _items_del_form(e, form)
    if form.get("quitar"):
        items = voz.quitar(items, str(form.get("quitar")))
    _guardar_borrador(con, e, items)
    if request.headers.get("X-Solo-Guardar"):
        return JSONResponse({"ok": True})
    return RedirectResponse(f"/rendimiento/voz/{entrada_id}", status_code=303)


@router.post("/voz/{entrada_id:int}/responder")
async def responder(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "voz")
    if not _mismo_origen(request):
        return _prohibido()
    e = _entrada(con, entrada_id)
    if e is None:
        return RedirectResponse("/rendimiento/voz", status_code=303)
    form = await request.form()
    texto = " ".join(str(form.get("respuesta") or "").split())[:voz.MAX_TEXTO]
    if e["estado"] != "borrador" or len(json.loads(e["rondas"])) >= voz.MAX_RONDAS:
        return HTMLResponse("Ese relato ya no admite respuestas", status_code=409)
    items = _items_del_form(e, form)
    if not texto:
        return render(request, "rendimiento/voz_entrada.html",
                      _ctx_entrada(request, con, e, items, "Escribe la respuesta o grábala"), 422)
    try:
        voz.preparar_respuesta(con, entrada_id, items, False, texto)
    except voz.Ocupado as err:
        return _ocupado(err)
    except voz.NoSeGuarda as err:
        return HTMLResponse(str(err), status_code=409)
    voz.lanzar(request.app.state.config, entrada_id)
    return RedirectResponse(f"/rendimiento/voz/{entrada_id}", status_code=303)


@router.post("/voz/{entrada_id:int}/responder/audio")
async def responder_audio(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    """La respuesta grabada. El borrador del formulario se guardó antes con /editar (voz.js)."""
    exigir_externo(request.app.state.config, "voz")
    if not _mismo_origen(request):
        return _prohibido()
    e = _entrada(con, entrada_id)
    if e is None or e["estado"] != "borrador" or len(json.loads(e["rondas"])) >= voz.MAX_RONDAS:
        return JSONResponse({"error": "Ese relato ya no admite respuestas"}, status_code=409)
    if (ya := voz.activa(con)) is not None:
        return _ocupado(voz.Ocupado(ya["id"]), True)
    ruta = await _recibir_audio(request)
    if isinstance(ruta, JSONResponse):
        return ruta
    try:
        voz.preparar_respuesta(con, entrada_id, voz.borrador(voz.entrada(con, entrada_id))["items"], True, None)
    except voz.Ocupado as err:
        ruta.unlink(missing_ok=True)
        return _ocupado(err, True)
    except voz.NoSeGuarda as err:
        ruta.unlink(missing_ok=True)
        return JSONResponse({"error": str(err)}, status_code=409)
    voz.lanzar(request.app.state.config, entrada_id, ruta)
    return JSONResponse({"url": f"/rendimiento/voz/{entrada_id}"})


@router.post("/voz/{entrada_id:int}/reintentar")
async def reintentar(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "voz")
    if not _mismo_origen(request):
        return _prohibido()
    form = await request.form()
    try:
        voz.reintentar(con, entrada_id, str(form.get("texto") or "") or None)
    except voz.Ocupado as err:
        return _ocupado(err)
    except voz.NoSeGuarda as err:
        return HTMLResponse(str(err), status_code=409)
    voz.lanzar(request.app.state.config, entrada_id)
    return RedirectResponse(f"/rendimiento/voz/{entrada_id}", status_code=303)


@router.post("/voz/{entrada_id:int}/guardar")
async def guardar(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    if not _mismo_origen(request):
        return _prohibido()
    e = _entrada(con, entrada_id)
    if e is None:
        return RedirectResponse("/rendimiento/voz", status_code=303)
    if e["estado"] != "borrador":
        return HTMLResponse("Ese relato ya no está en borrador", status_code=409)
    form = await request.form()
    items = _items_del_form(e, form)
    cfg = request.app.state.config
    try:
        registros = voz.guardar(cfg, con, entrada_id, items)
    except voz.NoSeGuarda as err:
        return HTMLResponse(str(err), status_code=409)
    except ValueError as err:
        _guardar_borrador(con, e, items)
        return render(request, "rendimiento/voz_entrada.html", _ctx_entrada(request, con, voz.entrada(con, entrada_id),
                                                                              items, str(err)), 422)
    except sqlite3.Error:
        rutas.log.exception("No pude guardar el relato %s", entrada_id)
        _guardar_borrador(con, e, items)
        return render(request, "rendimiento/voz_entrada.html", _ctx_entrada(
            request, con, voz.entrada(con, entrada_id), items, "No pude guardar; no se guardó nada"), 500)
    # Lo mismo que hace Comidas después de guardar: el inbox del vault (si está activo) y el resumen para IA
    if cfg.escribir_comidas:
        for fecha in sorted({r["fecha"] for r in registros if r["tipo"] in ("comida", "agua")}):
            try:
                nu.escribir_vault(con, cfg.vault_path, fecha, nu.plan_vigente(cfg.vault_path))
            except Exception:  # noqa: BLE001 - lo guardado en SQLite ya quedó
                rutas.log.exception("No pude escribir las comidas en el inbox del vault")
    rutas.actualizar_resumen(request, con)
    return RedirectResponse(f"/rendimiento/voz/{entrada_id}", status_code=303)


@router.post("/voz/{entrada_id:int}/descartar")
async def descartar(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    if not _mismo_origen(request):
        return _prohibido()
    e = _entrada(con, entrada_id)
    if e is not None and e["estado"] in voz.ACTIVAS:
        return HTMLResponse("Espera a que termine de procesar", status_code=409)
    if e is not None and e["estado"] != "guardada":
        with con:
            con.execute("DELETE FROM voz_entradas WHERE id = ?", (entrada_id,))
    return RedirectResponse("/rendimiento/voz", status_code=303)
