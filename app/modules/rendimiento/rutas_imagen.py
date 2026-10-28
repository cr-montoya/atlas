"""Rutas de la imagen proyectada: elegir fecha y poses, ver lo que se envía, confirmar, progreso, resultado."""

import json
import sqlite3
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from app.core.demo import exigir_externo
from . import fotos as fx
from . import imagen_proyectada as ip
from . import rutas, trabajos
from .rutas import Con, render

router = APIRouter(prefix="/rendimiento")


def _historial(con: sqlite3.Connection, n: int = 10) -> list[dict]:
    salida = []
    for t in con.execute("SELECT * FROM trabajos_ia WHERE tipo = ? ORDER BY id DESC LIMIT ?", (trabajos.IMAGEN, n)):
        params = json.loads(t["parametros"] or "{}")
        esc = params.get("escenario")
        salida.append({"t": t, "objetivo": params.get("objetivo"), "poses": params.get("poses", []),
                       "escenario": ip.ESCENARIOS[esc][0] if esc in ip.ESCENARIOS else ""})
    return salida


def _ctx(request: Request, con: sqlite3.Connection, fecha: str = "", poses: list[str] | None = None,
         error: str = "", escenario: str = "") -> dict:
    hoy = rutas.hoy()
    boveda = rutas._boveda(request)
    lo, hi = ip.rango(hoy)
    estado = ip.estado_poses(con, hoy)
    con_foto = [e["pose"] for e in estado if e["base"]]
    elegidas = [p for p in (poses if poses is not None else con_foto[:1]) if p in con_foto]
    escenario = ip.escenario_valido(escenario)
    prep, error_prep, objetivo = None, "", None
    if fecha:
        try:
            objetivo = ip.validar_fecha(fecha, hoy)
            prep = ip.preparar(con, boveda, hoy, objetivo, elegidas, escenario=escenario)
        except ip.ImagenInvalida as err:
            error_prep = str(err)
    return {
        "seccion": "analisis", "hoy": hoy, "min": lo, "max": hi, "fecha": fecha, "objetivo": objetivo,
        "atajos": ip.atajos(boveda, hoy), "estado": estado, "elegidas": elegidas, "prep": prep,
        "error": error or error_prep, "activo": trabajos.activo(con), "historial": _historial(con),
        "fecha_corta": ip.fecha_corta, "escenario": escenario, "ESCENARIOS": ip.ESCENARIOS,
    }


@router.get("/imagen")
def portada(request: Request, fecha: str = "", escenario: str = "", con: sqlite3.Connection = Con):
    poses = request.query_params.getlist("poses") if "poses" in request.query_params else None
    return render(request, "rendimiento/imagen.html", _ctx(request, con, fecha, poses, escenario=escenario))


@router.post("/imagen")
async def generar(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "imagen proyectada")
    form = await request.form()
    fecha, poses = str(form.get("fecha") or ""), [str(p) for p in form.getlist("poses")]
    escenario = ip.escenario_valido(str(form.get("escenario") or ""))
    hoy = rutas.hoy()
    try:
        objetivo = ip.validar_fecha(fecha, hoy)
        prep = ip.preparar(con, rutas._boveda(request), hoy, objetivo, poses, escenario=escenario)
    except ip.ImagenInvalida as err:
        return render(request, "rendimiento/imagen.html", _ctx(request, con, fecha, poses, str(err), escenario), 422)
    if form.get("acepto") != "1":
        return render(request, "rendimiento/imagen.html", _ctx(
            request, con, fecha, poses, "Confirma que aceptas enviar las fotos a OpenAI (Codex) para generar la imagen.",
            escenario), 422)
    activo = trabajos.activo(con)
    if activo:
        return render(request, "rendimiento/imagen.html", _ctx(
            request, con, fecha, poses, f"{trabajos.nombre(activo['tipo'])} sigue corriendo. Espera a que termine.",
            escenario), 409)
    tid, nuevo = trabajos.encolar(con, trabajos.IMAGEN, {
        "hoy": hoy.isoformat(), "objetivo": objetivo.isoformat(), "poses": prep.poses, "fotos": prep.ids,
        "escenario": prep.escenario,
        "confirmado": rutas.hoy().isoformat()})
    if nuevo:
        trabajos.lanzar(request.app.state.config, tid)
    return RedirectResponse(f"/rendimiento/imagen/{tid}", status_code=303)


def _envio(t: sqlite3.Row, res: dict) -> str:
    """'Enviado a OpenAI (Codex, gpt-6.1-sol) el 2026-10-19: análisis con …; imagen de frente con la foto del …'."""
    env = res.get("enviado") or {}
    partes = []
    bases = [r for r in env.get("paso1", []) if r[1].startswith("foto base")]
    cal = [r for r in env.get("paso1", []) if r[1].startswith("calibración")]
    if bases:
        texto = "análisis con " + ", ".join(f"{r[1].split(' de ', 1)[1].split(',')[0]} {r[0]}" for r in bases)
        if cal:
            texto += " y calibración " + " y ".join(r[0] for r in cal)
        partes.append(texto)
    for pose, fecha in (env.get("paso2") or {}).items():
        partes.append(f"imagen de {fx.POSES.get(pose, pose).lower()} con la foto del {fecha}")
    modelo = res.get("modelo") or "modelo predeterminado"
    params = json.loads(t["parametros"] or "{}")
    dia = params.get("hoy") or (t["inicio"] or t["creado"] or "")[:10]
    return f"Enviado a OpenAI (Codex, {modelo}) el {dia}: " + "; ".join(partes)


def _ctx_trabajo(request: Request, con: sqlite3.Connection, tid: int) -> dict | None:
    t = trabajos.trabajo(con, tid)
    if t is None or t["tipo"] != trabajos.IMAGEN:
        return None
    params = json.loads(t["parametros"] or "{}")
    try:
        res = json.loads(t["resultado"]) if t["resultado"] else {}
    except ValueError:
        res = {}
    filas = []
    for r in ip.de_trabajo(con, tid):
        base = fx.foto(con, r["foto_base_id"]) if r["foto_base_id"] else None
        lado = False
        if base and r["ancho"] and r["alto"]:
            lado = abs(base.ancho / base.alto - r["ancho"] / r["alto"]) / (base.ancho / base.alto) > 0.02
        filas.append({"r": r, "base": base, "lado_a_lado": lado, "nombre": fx.POSES.get(r["pose"], r["pose"])})
    corriendo = t["estado"] in ("en_cola", "corriendo")
    return {"seccion": "analisis", "t": t, "params": params, "res": res, "filas": filas, "corriendo": corriendo,
            "progreso": ip.PROGRESO.get(tid, "En cola" if t["estado"] == "en_cola" else "Preparando"),
            "envio": _envio(t, res) if res.get("enviado") else "", "PALABRA": ip.PALABRA,
            "objetivo": date.fromisoformat(params["objetivo"]) if params.get("objetivo") else None}


@router.get("/imagen/{trabajo_id:int}")
def ver(request: Request, trabajo_id: int, con: sqlite3.Connection = Con):
    ctx = _ctx_trabajo(request, con, trabajo_id)
    if ctx is None:
        return RedirectResponse("/rendimiento/imagen", status_code=303)
    return render(request, "rendimiento/imagen_resultado.html", ctx)


@router.get("/imagen/{trabajo_id:int}/estado")
def estado(request: Request, trabajo_id: int, con: sqlite3.Connection = Con):
    ctx = _ctx_trabajo(request, con, trabajo_id)
    if ctx is None:
        return RedirectResponse("/rendimiento/imagen", status_code=303)
    resp = render(request, "rendimiento/_imagen_estado.html", ctx)
    if not ctx["corriendo"] and request.headers.get("HX-Request"):
        resp.headers["HX-Refresh"] = "true"
    return resp


@router.post("/imagen/{trabajo_id:int}/cancelar")
def cancelar(request: Request, trabajo_id: int, con: sqlite3.Connection = Con):
    t = trabajos.trabajo(con, trabajo_id)
    if t is not None and t["tipo"] == trabajos.IMAGEN and t["estado"] in ("en_cola", "corriendo"):
        ip.CANCELADOS.add(trabajo_id)
    return RedirectResponse(f"/rendimiento/imagen/{trabajo_id}", status_code=303)


@router.get("/imagen/archivo/{imagen_id}")
def archivo(request: Request, imagen_id: int, con: sqlite3.Connection = Con):
    r = ip.imagen(con, imagen_id)
    ruta = request.app.state.config.fotos_path / ip.GENERADAS / r["archivo"] if r is not None and r["archivo"] else None
    if ruta is None or not ruta.is_file():
        return RedirectResponse("/rendimiento/imagen", status_code=303)
    return FileResponse(ruta, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/imagen/archivo/{imagen_id}/borrar")
def borrar(request: Request, imagen_id: int, con: sqlite3.Connection = Con):
    tid = ip.borrar(con, request.app.state.config, imagen_id)
    return RedirectResponse(f"/rendimiento/imagen/{tid}" if tid else "/rendimiento/imagen", status_code=303)
