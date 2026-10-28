"""Rutas de los análisis con Claude: lanzar, estado en vivo con htmx, resultado guardado e historial."""

import json
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.core.demo import exigir_externo
from . import analisis, logica, semanas, trabajos
from . import fotos as fx
from . import rutas
from .rutas import Con, _int, render
from .vault import NOMBRES

router = APIRouter(prefix="/rendimiento")

DISCIPLINAS = {"": "Todas", "judo": "Judo", "bjj": "BJJ", "muaythai": "Muay Thai"}


def _resultado(t: sqlite3.Row | None) -> dict:
    try:
        return json.loads(t["resultado"]) if t and t["resultado"] else {}
    except ValueError:
        return {"texto": t["resultado"]}


def historial(con: sqlite3.Connection, n: int = 12) -> list[dict]:
    marcas = ",".join("?" * len(trabajos.ANALISIS))
    filas = con.execute(f"SELECT * FROM trabajos_ia WHERE tipo IN ({marcas}) ORDER BY id DESC LIMIT ?",
                        (*trabajos.ANALISIS, n)).fetchall()
    return [_item(t) for t in filas]


def _item(t: sqlite3.Row) -> dict:
    params = json.loads(t["parametros"] or "{}")
    res = _resultado(t)
    return {"t": t, "nombre": trabajos.ANALISIS.get(t["tipo"], t["tipo"]), "params": params, "res": res,
            "que": analisis.resumen_parametros(t["tipo"], params, res)}


def ctx_estado(con: sqlite3.Connection, trabajo_id: int | None = None) -> dict:
    """El trabajo que se muestra en la zona de estado: el pedido, o el activo si hay uno."""
    t = trabajos.trabajo(con, trabajo_id) if trabajo_id else trabajos.activo(con)
    return {"t": t, "item": _item(t) if t else None,
            "es_analisis": bool(t and t["tipo"] in trabajos.ANALISIS)}


def _ctx(request: Request, con: sqlite3.Connection, error: str | None = None, t: int | None = None, **extra) -> dict:
    h = rutas.hoy()
    pose = extra.pop("pose", "") or "frente"
    pose = pose if pose in fx.POSES else "frente"
    lista = fx.de_pose(con, pose)
    por_id = {f.id: f for f in lista}
    fa = por_id.get(_int(extra.pop("a", None))) or (lista[0] if len(lista) > 1 else None)
    fb = por_id.get(_int(extra.pop("b", None))) or (lista[-1] if len(lista) > 1 else None)
    opciones = analisis.semanas_elegibles(h)
    etiquetas = {s: semanas.Semana(s, *logica.rango_semana(s)).etiqueta for s in opciones}
    activo = trabajos.activo(con)
    return {
        "seccion": "analisis", "error": error, "ocupado": activo is not None, **ctx_estado(con, None if activo else t),
        "semanas_op": opciones, "etiquetas": etiquetas, "semana": extra.pop("semana", "") or analisis.semana_por_defecto(h),
        "N_COMBATE": analisis.SESIONES_COMBATE, "DISCIPLINAS": DISCIPLINAS, "REFERENTES": analisis.REFERENTES,
        "n": _int(extra.pop("n", None), 10), "disciplina": extra.pop("disciplina", ""),
        "referente": extra.pop("referente", ""),
        "POSES": fx.POSES, "pose": pose, "fotos_pose": lista, "fa": fa, "fb": fb, "conteo": fx.conteo_por_pose(con),
        "ultimos": {tipo: trabajos.ultimo(con, tipo, "listo") for tipo in trabajos.ANALISIS},
        "historial": historial(con), "relleno": _relleno(con), **extra,
    }


def _relleno(con: sqlite3.Connection) -> dict:
    """El botón del relleno de salud desaparece cuando uno terminó bien; si falló, sigue y muestra el error.
    Un relleno marcado listo que corrió tramos sin escribir archivos (antes de que eso contara como falla) no cuenta."""
    def sirvio(resultado: str | None) -> bool:
        res = json.loads(resultado or "{}")
        return bool(res.get("archivos_nuevos")) or "tramos" not in res
    listo = any(sirvio(r[0]) for r in con.execute(
        "SELECT resultado FROM trabajos_ia WHERE tipo = ? AND estado = 'listo'", (trabajos.RELLENAR,)))
    return {"listo": listo, "ultimo": trabajos.ultimo(con, trabajos.RELLENAR)}


@router.get("/analisis")
def portada(request: Request, con: sqlite3.Connection = Con):
    """Portada de la analítica: comparar semanas, Claude, mi combate y antes y después."""
    ultimo = con.execute("SELECT * FROM trabajos_ia WHERE estado = 'listo' AND tipo IN ("
                         + ",".join("?" * len(trabajos.ANALISIS)) + ") ORDER BY id DESC LIMIT 1",
                         tuple(trabajos.ANALISIS)).fetchone()
    return render(request, "rendimiento/analisis.html", {
        "seccion": "analisis", "ultimo": _item(ultimo) if ultimo else None, "activo": trabajos.activo(con),
        "combates": con.execute("SELECT COUNT(*) FROM sesiones WHERE tipo = 'combate' AND guardada = 1").fetchone()[0],
        "fotos": sum(fx.conteo_por_pose(con).values()),
    })


@router.get("/ia")
def ia(request: Request, pose: str = "", a: str = "", b: str = "", t: int | None = None, con: sqlite3.Connection = Con):
    return render(request, "rendimiento/ia.html", _ctx(request, con, t=t, pose=pose, a=a, b=b))


def _lanzar(request: Request, con: sqlite3.Connection, tipo: str, params: dict, form_ctx: dict):
    activo = trabajos.activo(con)
    if activo:
        nombre = trabajos.nombre(activo["tipo"])
        return render(request, "rendimiento/ia.html", _ctx(
            request, con, f"{nombre} sigue corriendo. Espera a que termine para lanzar otro análisis.", **form_ctx), 409)
    tid, nuevo = trabajos.encolar(con, tipo, {**params, "hoy": rutas.hoy().isoformat()})
    if nuevo:
        trabajos.lanzar(request.app.state.config, tid)
    return RedirectResponse(f"/rendimiento/ia?t={tid}#estado", status_code=303)


@router.post("/ia/semana")
async def ia_semana(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "análisis")
    form = await request.form()
    semana = str(form.get("semana") or "")
    if semana not in analisis.semanas_elegibles(rutas.hoy()):
        return render(request, "rendimiento/ia.html", _ctx(request, con, "Elige una de las últimas 12 semanas."), 422)
    return _lanzar(request, con, "analisis_semana", {"semana": semana}, {"semana": semana})


@router.post("/ia/combate")
async def ia_combate(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "análisis")
    form = await request.form()
    n = _int(form.get("n"), 10)
    disciplina = str(form.get("disciplina") or "")
    referente = str(form.get("referente") or "").strip()[:80]
    valores = {"n": n, "disciplina": disciplina, "referente": referente}
    if n not in analisis.SESIONES_COMBATE or disciplina not in DISCIPLINAS:
        return render(request, "rendimiento/ia.html", _ctx(request, con, "Elige cuántas sesiones y la disciplina.", **valores), 422)
    hay = con.execute("SELECT 1 FROM sesiones WHERE tipo = 'combate' AND guardada = 1"
                      + (" AND disciplina = ?" if disciplina else ""), (disciplina,) if disciplina else ()).fetchone()
    if not hay:
        que = NOMBRES.get(disciplina, "combate")
        return render(request, "rendimiento/ia.html", _ctx(
            request, con, f"No hay sesiones de {que} registradas. Registra una en Registrar, Combate.", **valores), 422)
    return _lanzar(request, con, "analisis_combate", {"n": n, "disciplina": disciplina, "referente": referente}, valores)


@router.post("/ia/fotos")
async def ia_fotos(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "análisis")
    form = await request.form()
    a, b, pose = _int(form.get("a")), _int(form.get("b")), str(form.get("pose") or "")
    valores = {"pose": pose, "a": a, "b": b}
    try:
        analisis.fotos_elegidas(con, a, b)
    except analisis.AnalisisInvalido as err:
        return render(request, "rendimiento/ia.html", _ctx(request, con, str(err), **valores), 422)
    if form.get("confirmo") != "1":
        return render(request, "rendimiento/ia.html", _ctx(
            request, con, "Confirma que aceptas enviar las dos fotos a Anthropic (Claude) para este análisis.", **valores), 422)
    confirmado = datetime.now().isoformat(timespec="minutes")
    return _lanzar(request, con, "comparar_fotos", {"a": a, "b": b, "confirmado": confirmado}, valores)


@router.post("/ia/rellenar-salud")
async def ia_rellenar_salud(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "relleno de salud")
    if _relleno(con)["listo"]:
        return RedirectResponse("/rendimiento/ia", status_code=303)
    activo = trabajos.activo(con)
    if activo:
        return render(request, "rendimiento/ia.html", _ctx(
            request, con, f"{trabajos.nombre(activo['tipo'])} sigue corriendo. Espera a que termine."), 409)
    tid, nuevo = trabajos.encolar(con, trabajos.RELLENAR, {"hoy": rutas.hoy().isoformat()})
    if nuevo:
        trabajos.lanzar(request.app.state.config, tid)
    return RedirectResponse(f"/rendimiento/ia?t={tid}#estado", status_code=303)


@router.get("/ia/estado/{trabajo_id}")
def ia_estado(request: Request, trabajo_id: int, con: sqlite3.Connection = Con):
    ctx = ctx_estado(con, trabajo_id)
    resp = render(request, "rendimiento/_ia_estado.html", ctx)
    t = ctx["t"]
    if t and request.headers.get("HX-Request"):
        if t["estado"] == "listo" and t["tipo"] in trabajos.ANALISIS:
            resp.headers["HX-Redirect"] = f"/rendimiento/ia/{trabajo_id}"
        elif t["estado"] in ("listo", "fallido"):
            resp.headers["HX-Refresh"] = "true"  # vuelve a habilitar los botones
    return resp


@router.get("/ia/{trabajo_id}")
def ia_resultado(request: Request, trabajo_id: int, con: sqlite3.Connection = Con):
    t = trabajos.trabajo(con, trabajo_id)
    if t is None or t["tipo"] not in trabajos.ANALISIS:
        return RedirectResponse("/rendimiento/ia", status_code=303)
    item = _item(t)
    duracion = None
    if t["inicio"] and t["fin"]:
        duracion = int((datetime.fromisoformat(t["fin"]) - datetime.fromisoformat(t["inicio"])).total_seconds())
    return render(request, "rendimiento/ia_resultado.html", {"seccion": "analisis", "item": item, "t": t, "duracion": duracion,
                                                              "ocupado": trabajos.activo(con) is not None})
