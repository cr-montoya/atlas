"""Rutas del registro de combate técnico-táctico: disciplina, bloques, técnicas, situaciones y resultados."""

import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import actividades as act
from . import consultas as q
from . import rutas
from .consultas import ErrorDatos
from .rutas import Con, render

router = APIRouter(prefix="/rendimiento")

DURACION_DEFECTO_MIN = {"tecnica": 20, "drill": 15, "situacional": 15, "randori": None}
ROUNDS_DEFECTO = {"randori": 5}


def ctx_combate(request: Request, con: sqlite3.Connection, sesion_id: int, **extra) -> dict:
    s = q.sesion(con, sesion_id)
    boveda = rutas._boveda(request)
    vinculada = act.por_clave(con, boveda, s["clave_importada"])
    candidatas = [] if vinculada else act.candidatas_vinculo(
        con, boveda, s["fecha"], act.DISCIPLINAS_VINCULO["combate"], sesion_id)
    return {
        "seccion": "registrar", "s": s, "bloques": q.bloques_combate(con, sesion_id),
        "duracion_s": q.duracion_combate(con, sesion_id), "vinculada": vinculada, "candidatas": candidatas,
        "recientes": q.buscar_tecnicas(con, s["disciplina"]), "catalogo": q.tecnicas_por_familia(con, s["disciplina"]),
        **_constantes(), "error": None, **extra,
    }


def _constantes() -> dict:
    return {"TIPOS_BLOQUE": q.TIPOS_BLOQUE, "SITUACIONES": q.SITUACIONES, "RIVALES": q.RIVALES,
            "RESULTADOS": q.RESULTADOS, "DISCIPLINAS": {"judo": "Judo", "bjj": "BJJ", "muaythai": "Muay Thai"}}


def _es_htmx(request: Request) -> bool:
    return bool(request.headers.get("HX-Request"))


def _bloque(request: Request, con: sqlite3.Connection, bloque_id: int, error: str | None = None, status: int = 200):
    b = q.bloque_combate(con, bloque_id)
    if not _es_htmx(request):
        return RedirectResponse(f"/rendimiento/sesiones/{b['sesion_id']}#bl-{bloque_id}", status_code=303)
    ctx = ctx_combate(request, con, b["sesion_id"], error_bloque=error, error_id=bloque_id)
    ctx["b"] = next(x for x in ctx["bloques"] if x.bloque["id"] == bloque_id)
    ctx["oob"] = True
    return render(request, "rendimiento/_bloque_combate.html", ctx, 422 if error else status)


def _minutos(valor) -> int | None:
    t = str(valor or "").strip().replace(",", ".")
    if not t:
        return None
    try:
        return round(float(t) * 60)
    except ValueError:
        raise ErrorDatos("Escribe los minutos con números, por ejemplo 30.") from None


@router.post("/sesiones/{sesion_id}/disciplina")
async def disciplina(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        q.cambiar_disciplina(con, sesion_id, str(form.get("disciplina") or ""))
    except ErrorDatos as err:
        return render(request, "rendimiento/combate.html", ctx_combate(request, con, sesion_id, error=str(err)), 422)
    return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}", status_code=303)


@router.post("/sesiones/{sesion_id}/bloques")
async def bloque_nuevo(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    tipo = str(form.get("tipo") or "")
    try:
        minutos = DURACION_DEFECTO_MIN.get(tipo)
        bloque_id = q.crear_bloque(con, sesion_id, tipo, minutos * 60 if minutos else None, ROUNDS_DEFECTO.get(tipo))
    except ErrorDatos:
        return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}", status_code=303)
    return _bloque(request, con, bloque_id)


@router.post("/bloques/{bloque_id}")
async def bloque_editar(request: Request, bloque_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    try:
        rounds = str(form.get("rounds") or "").strip()
        q.actualizar_bloque(con, bloque_id, duracion_s=_minutos(form.get("duracion_min")),
                            rounds=int(rounds) if rounds.isdigit() else None,
                            rivales=[str(x) for x in form.getlist("rival")])
    except ErrorDatos as err:
        return _bloque(request, con, bloque_id, str(err))
    return _bloque(request, con, bloque_id)


@router.post("/bloques/{bloque_id}/borrar")
def bloque_borrar(request: Request, bloque_id: int, con: sqlite3.Connection = Con):
    b = q.bloque_combate(con, bloque_id)
    q.borrar_bloque(con, bloque_id)
    if _es_htmx(request):
        ctx = ctx_combate(request, con, b["sesion_id"])
        return render(request, "rendimiento/_bloque_combate.html", {**ctx, "b": None, "bloque_id": bloque_id, "oob": True})
    return RedirectResponse(f"/rendimiento/sesiones/{b['sesion_id']}", status_code=303)


@router.get("/bloques/{bloque_id}/tecnicas", response_class=HTMLResponse)
def tecnicas(request: Request, bloque_id: int, q_texto: str = "", con: sqlite3.Connection = Con):
    b = q.bloque_combate(con, bloque_id)
    s = q.sesion(con, b["sesion_id"])
    texto = request.query_params.get("q", q_texto)
    lista = q.buscar_tecnicas(con, s["disciplina"], texto)
    return render(request, "rendimiento/_tecnicas.html",
                  {"lista": lista, "texto": texto, "bloque_id": bloque_id, "disciplina": s["disciplina"]})


@router.post("/bloques/{bloque_id}/entradas")
async def entrada_nueva(request: Request, bloque_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    tecnica = str(form.get("tecnica_id") or "").strip()
    situacion = str(form.get("situacion") or "").strip() or None
    try:
        q.agregar_entrada(con, bloque_id, tecnica_id=int(tecnica) if tecnica.isdigit() else None, situacion=situacion,
                          resultado=str(form.get("resultado") or "trabajada"), detalle=str(form.get("detalle") or ""))
    except ErrorDatos as err:
        return _bloque(request, con, bloque_id, str(err))
    return _bloque(request, con, bloque_id)


@router.post("/entradas/{entrada_id}")
async def entrada_editar(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    e = q.entrada(con, entrada_id)
    form = await request.form()
    try:
        q.actualizar_entrada(con, entrada_id, resultado=str(form.get("resultado") or e["resultado"]),
                             detalle=str(form.get("detalle") if "detalle" in form else (e["detalle"] or "")))
    except ErrorDatos as err:
        return _bloque(request, con, e["bloque_id"], str(err))
    return _bloque(request, con, e["bloque_id"])


@router.post("/entradas/{entrada_id}/borrar")
def entrada_borrar(request: Request, entrada_id: int, con: sqlite3.Connection = Con):
    e = q.entrada(con, entrada_id)
    q.borrar_entrada(con, entrada_id)
    return _bloque(request, con, e["bloque_id"])
