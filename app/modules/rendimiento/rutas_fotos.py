"""Rutas de fotos antes y después: comparar con deslizador, línea de tiempo, guía de pose y subida."""

import sqlite3
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from . import evaluaciones as ev
from . import fotos as fx
from . import rutas
from .rutas import Con, render

router = APIRouter(prefix="/rendimiento")


def _base(request: Request):
    return request.app.state.config.fotos_path


@router.get("/fotos")
def fotos(request: Request, pose: str = "frente", a: int | None = None, b: int | None = None, ok: int = 0,
          fechas: str = "", exif: int = 0, r: int = 0, mal: str = "", con: sqlite3.Connection = Con):
    pose = pose if pose in fx.POSES else "frente"
    lista = fx.de_pose(con, pose)
    por_id = {f.id: f for f in lista}
    fa = por_id.get(a) or (lista[0] if lista else None)
    fb = por_id.get(b) or (lista[-1] if lista else None)
    meds = ev.todas(con, rutas._boveda(request))
    return render(request, "rendimiento/fotos.html", {
        "seccion": "analisis", "pose": pose, "POSES": fx.POSES, "lista": lista, "fa": fa, "fb": fb,
        "medidas_a": ev.medidas_cercanas(meds, fa.fecha) if fa else [],
        "medidas_b": ev.medidas_cercanas(meds, fb.fecha) if fb else [],
        "conteo": fx.conteo_por_pose(con), "ok": ok, "subida": {
            "fechas": [f for f in fechas.split(",") if f][:fx.MAX_LOTE], "exif": exif, "reemplazos": r,
            "fallidas": [m for m in mal.split("|") if m][:5]},
    })


@router.get("/fotos/nueva")
def foto_nueva(request: Request, pose: str = "frente", con: sqlite3.Connection = Con):
    pose = pose if pose in fx.POSES else "frente"
    return render(request, "rendimiento/foto_nueva.html", {
        "seccion": "analisis", "pose": pose, "POSES": fx.POSES, "anterior": fx.ultima(con, pose),
        "hoy": rutas.hoy().isoformat(), "error": None})


@router.post("/fotos")
async def foto_guardar(request: Request, fecha: str = Form(""), pose: str = Form(""), notas: str = Form(""),
                       fecha_de_la_foto: str = Form(""), foto: list[UploadFile] | None = File(None),
                       con: sqlite3.Connection = Con):
    """Una foto de la cámara o varias de la galería o los archivos. Con fecha_de_la_foto=1, cada foto toma
    la fecha en que se tomó (EXIF), leída antes de descartar los metadatos; si no la trae, la del formulario."""
    quiere_json = "application/json" in request.headers.get("accept", "")
    archivos = [f for f in (foto or []) if f.filename or f.size]
    hoy = rutas.hoy()
    guardadas: list[fx.Foto] = []
    de_la_foto = reemplazos = 0
    fallidas: list[str] = []
    error = None
    try:
        if not archivos:
            raise fx.FotoInvalida("Elige una foto.")
        if len(archivos) > fx.MAX_LOTE:
            raise fx.FotoInvalida(f"Sube hasta {fx.MAX_LOTE} fotos a la vez.")
        if pose not in fx.POSES:
            raise fx.FotoInvalida("Elige la pose: frente, perfil derecho o espalda.")
        for archivo in archivos:
            datos = await archivo.read()
            tomada = fx.fecha_tomada(datos, hoy) if fecha_de_la_foto == "1" else None
            dia = tomada or fecha or hoy.isoformat()
            ya = fx.foto_por(con, dia, pose)
            try:
                guardadas.append(fx.guardar(con, _base(request), dia, pose, datos, notas))
            except fx.FotoInvalida as err:
                if len(archivos) == 1:
                    raise
                fallidas.append(f"{(archivo.filename or 'foto')[:40]} ({err})")
                continue
            de_la_foto += tomada is not None
            reemplazos += ya is not None  # incluye dos fotos del mismo día en la misma subida
        if not guardadas:
            raise fx.FotoInvalida("No pude leer ninguna foto. " + "; ".join(fallidas))
    except fx.FotoInvalida as err:
        error = str(err)
    if error:
        if quiere_json:
            return JSONResponse({"ok": False, "error": error}, status_code=422)
        return render(request, "rendimiento/foto_nueva.html", {
            "seccion": "analisis", "pose": pose if pose in fx.POSES else "frente", "POSES": fx.POSES,
            "anterior": fx.ultima(con, pose) if pose in fx.POSES else None, "hoy": hoy.isoformat(),
            "error": error}, 422)
    rutas.actualizar_resumen(request, con)
    ultima = guardadas[-1]
    destino = f"/rendimiento/fotos?pose={ultima.pose}&b={ultima.id}&ok={len(guardadas)}"
    if len(archivos) > 1 or fecha_de_la_foto == "1":
        destino += "&" + urlencode({"fechas": ",".join(sorted({g.fecha for g in guardadas})), "exif": de_la_foto,
                                    "r": reemplazos, "mal": "|".join(fallidas[:5])})
    if quiere_json:
        return JSONResponse({"ok": True, "url": destino})
    return RedirectResponse(destino, status_code=303)


@router.get("/fotos/{foto_id}/imagen")
def foto_imagen(request: Request, foto_id: int, mini: int = 0, con: sqlite3.Connection = Con):
    f = fx.foto(con, foto_id)
    if f is None:
        return Response(status_code=404)
    ruta = fx.ruta(_base(request), f, bool(mini))
    if not ruta.is_file():
        return Response(status_code=404)
    # Detrás del PIN; el navegador puede guardarla en su caché privada, nunca un proxy.
    return FileResponse(ruta, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/fotos/{foto_id}/borrar")
def foto_borrar(request: Request, foto_id: int, con: sqlite3.Connection = Con):
    f = fx.foto(con, foto_id)
    fx.borrar(con, _base(request), foto_id)
    rutas.actualizar_resumen(request, con)
    return RedirectResponse(f"/rendimiento/fotos?pose={f.pose if f else 'frente'}", status_code=303)
