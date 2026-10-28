"""Rutas del módulo de rendimiento: hoy, registrar, comparar, tests y más."""

import json
import logging
import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.db import con_peticion

from app.core.demo import exigir_externo
from . import actividades as act
from . import consultas as q
from . import combate, logica, resumen_ia, semanas, tablero, trabajos, vault
from . import sensaciones as sen
from .consultas import ErrorDatos
from .logica import ValorInvalido

router = APIRouter(prefix="/rendimiento")
Con = Depends(con_peticion)
log = logging.getLogger(__name__)

AVISO_HOMBRO = "Ejercicio que carga el hombro: revisa las indicaciones de tu ortopedista y fisio"
TIPOS = {"fuerza": ("fuerza", "fuerza"), "combate": ("combate", "judo")}  # cardio y caminatas vienen del reloj

def hoy() -> date:
    return date.today()


def render(request: Request, plantilla: str, ctx: dict, status: int = 200):
    ctx.setdefault("seccion", "")
    return request.app.state.templates.TemplateResponse(request, plantilla, ctx, status_code=status)


def actualizar_resumen(request: Request, con: sqlite3.Connection) -> None:
    """Regenera exports/rendimiento-ia.*; si falla, lo guardado ya quedó y solo se registra el error."""
    cfg = request.app.state.config
    try:
        resumen_ia.escribir(con, cfg.exports_path, cfg.vault_path, hoy())
    except Exception:  # noqa: BLE001
        log.exception("No pude regenerar el resumen de rendimiento para IA")


def _boveda(request: Request):
    return request.app.state.config.vault_path


def _int(valor, defecto=None):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return defecto


def _mes(texto: str) -> date | None:
    try:
        return date.fromisoformat(f"{texto}-01")
    except (TypeError, ValueError):
        return None


@router.get("")
def inicio(request: Request, mes: str = "", con: sqlite3.Connection = Con):
    ctx = tablero.construir(con, _boveda(request), hoy())
    if _mes(mes):
        ctx["cal"] = tablero.calendario(con, _boveda(request), hoy(), _mes(mes))
    return render(request, "rendimiento/hoy.html", {"seccion": "hoy", "hoy": hoy(), **ctx, **ctx_sync(request, con)})


@router.get("/calendario")
def calendario_mes(request: Request, mes: str = "", con: sqlite3.Connection = Con):
    cal = tablero.calendario(con, _boveda(request), hoy(), _mes(mes) or hoy().replace(day=1))
    return render(request, "rendimiento/_calendario.html", {"cal": cal})


# ---------- Registrar ----------

def dias_registrar(h: date) -> list[dict]:
    """Hoy, ayer y los 6 días anteriores, con su nombre ("lunes 19")."""
    return [{"fecha": (h - timedelta(days=i)).isoformat(), "nombre": sen.nombre_dia(h - timedelta(days=i), h).capitalize()}
            for i in range(sen.DIAS_ATRAS + 1)]


@router.get("/registrar")
def registrar(request: Request, guardada: int | None = None, fecha: str = "", con: sqlite3.Connection = Con):
    try:
        f = sen.fecha_editable(fecha, hoy()) if fecha else hoy().isoformat()
    except sen.SensacionInvalida:
        f = hoy().isoformat()
    recientes = con.execute("SELECT * FROM sesiones WHERE guardada = 1 ORDER BY fecha DESC, id DESC LIMIT 8").fetchall()
    ultima = q.sesion(con, guardada) if guardada else None
    return render(request, "rendimiento/registrar.html", {
        "seccion": "registrar", "hoy": hoy(), "fecha": f, "dias": dias_registrar(hoy()),
        "borradores": {t: q.borrador(con, f, t) for t in TIPOS},
        "recientes": recientes, "guardada": ultima,
        "vinculada": act.por_clave(con, _boveda(request), ultima["clave_importada"]) if ultima else None,
    })


@router.post("/sesiones")
async def sesion_nueva(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    tipo = str(form.get("tipo") or "")
    if tipo not in TIPOS:
        return RedirectResponse("/rendimiento/registrar", status_code=303)
    try:
        f = sen.fecha_editable(form.get("fecha"), hoy()) if "fecha" in form else hoy().isoformat()
    except sen.SensacionInvalida:
        return HTMLResponse("Solo se pueden registrar los últimos 7 días", status_code=422)
    existente = q.borrador(con, f, tipo)
    sesion_id = existente["id"] if existente else q.crear_sesion(con, f, *TIPOS[tipo])
    return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}", status_code=303)


def _ctx_fuerza(request: Request, con: sqlite3.Connection, sesion_id: int, **extra) -> dict:
    s = q.sesion(con, sesion_id)
    boveda = _boveda(request)
    pc = q.peso_corporal_g(con, boveda)
    bloques = q.bloques(con, sesion_id, pc)
    anterior = q.sesion_anterior(con, sesion_id, "fuerza") if not bloques else None
    recientes = q.ejercicios_recientes(con)
    vinculada = act.por_clave(con, boveda, s["clave_importada"])
    candidatas = [] if vinculada else act.candidatas_vinculo(con, boveda, s["fecha"], act.DISCIPLINAS_VINCULO["fuerza"], sesion_id)
    return {
        "seccion": "registrar", "s": s, "bloques": bloques, "peso_corporal_g": pc,
        "total_g": q.carga_total_sesion(con, sesion_id, pc), "anterior": anterior,
        "anterior_n": len(q.bloques(con, anterior["id"])) if anterior else 0,
        "ejercicios": q.ejercicios(con), "recientes": recientes, "aviso_hombro": AVISO_HOMBRO,
        "vinculada": vinculada, "candidatas": candidatas, "error": None, **extra,
    }


@router.get("/sesiones/{sesion_id}", response_class=HTMLResponse)
def sesion_ver(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    try:
        s = q.sesion(con, sesion_id)
    except ErrorDatos:
        return RedirectResponse("/rendimiento/registrar", status_code=303)
    return pagina_sesion(request, con, s)


def pagina_sesion(request: Request, con: sqlite3.Connection, s: sqlite3.Row, error: str | None = None):
    if s["tipo"] == "fuerza":
        return render(request, "rendimiento/fuerza.html", _ctx_fuerza(request, con, s["id"], error=error),
                      422 if error else 200)
    if s["tipo"] == "combate":
        from .rutas_combate import ctx_combate
        return render(request, "rendimiento/combate.html", ctx_combate(request, con, s["id"], error=error),
                      422 if error else 200)
    return RedirectResponse("/rendimiento/registrar", status_code=303)


def _bloque(request: Request, con: sqlite3.Connection, sesion_id: int, ejercicio_id: int, error: str | None = None):
    """Responde el bloque del ejercicio y, fuera de banda, la carga total de la sesión."""
    ctx = _ctx_fuerza(request, con, sesion_id, error=error)
    b = next((x for x in ctx["bloques"] if x.ejercicio["id"] == ejercicio_id), None)
    ctx.update(b=b, ejercicio_id=ejercicio_id, oob=True)
    return render(request, "rendimiento/_ejercicio.html", ctx, 422 if error else 200)


@router.post("/sesiones/{sesion_id}/ejercicios")
async def ejercicio_agregar(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    ejercicio_id = _int(form.get("ejercicio_id"))
    try:
        e = q.ejercicio(con, ejercicio_id)
        ya = con.execute("SELECT 1 FROM series WHERE sesion_id = ? AND ejercicio_id = ?", (sesion_id, e["id"])).fetchone()
        if not ya:
            q.agregar_serie(con, sesion_id, e["id"], peso_corporal_g=_pc_si_aplica(request, con, e))
    except ErrorDatos as err:
        if request.headers.get("HX-Request"):
            return HTMLResponse(f'<p class="error" role="alert">{err}</p>', status_code=422)
        return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}", status_code=303)
    if request.headers.get("HX-Request"):
        return _bloque(request, con, sesion_id, e["id"])
    return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}#ej-{e['id']}", status_code=303)


def _pc_si_aplica(request: Request, con: sqlite3.Connection, e: sqlite3.Row) -> int | None:
    if e["tipo_carga"] in ("peso_corporal", "peso_corporal_lastre"):
        return q.peso_corporal_g(con, _boveda(request))
    return None


@router.post("/sesiones/{sesion_id}/ejercicios/{ejercicio_id}/serie")
def serie_agregar(request: Request, sesion_id: int, ejercicio_id: int, con: sqlite3.Connection = Con):
    e = q.ejercicio(con, ejercicio_id)
    q.agregar_serie(con, sesion_id, ejercicio_id, peso_corporal_g=_pc_si_aplica(request, con, e))
    return _respuesta_serie(request, con, sesion_id, ejercicio_id)


@router.post("/sesiones/{sesion_id}/ejercicios/{ejercicio_id}/quitar")
def ejercicio_quitar(request: Request, sesion_id: int, ejercicio_id: int, con: sqlite3.Connection = Con):
    q.quitar_ejercicio(con, sesion_id, ejercicio_id)
    return _respuesta_serie(request, con, sesion_id, ejercicio_id)


@router.post("/series/{serie_id}")
async def serie_editar(request: Request, serie_id: int, con: sqlite3.Connection = Con):
    s = q.serie(con, serie_id)
    form = await request.form()
    error = None
    try:
        reps = _int(form.get("reps"))
        if reps is None:
            raise ErrorDatos("Escribe las repeticiones.")
        rpe = str(form.get("rpe") or "").strip().replace(",", ".")
        rpe_x10 = round(float(rpe) * 10) if rpe else None
        q.actualizar_serie(con, serie_id, reps=reps, carga_g=logica.parse_kg(str(form.get("carga") or "")), rpe_x10=rpe_x10)
    except (ErrorDatos, ValorInvalido) as err:
        error = str(err)
    except ValueError:
        error = "El RPE va de 1 a 10, por ejemplo 8 u 8,5."
    return _respuesta_serie(request, con, s["sesion_id"], s["ejercicio_id"], error)


@router.post("/series/{serie_id}/ajustar")
async def serie_ajustar(request: Request, serie_id: int, campo: str, paso: int, con: sqlite3.Connection = Con):
    s = q.serie(con, serie_id)
    try:
        q.ajustar_serie(con, serie_id, campo, 1 if paso > 0 else -1)
    except ErrorDatos as err:
        return _respuesta_serie(request, con, s["sesion_id"], s["ejercicio_id"], str(err))
    return _respuesta_serie(request, con, s["sesion_id"], s["ejercicio_id"])


@router.post("/series/{serie_id}/borrar")
def serie_borrar(request: Request, serie_id: int, con: sqlite3.Connection = Con):
    s = q.serie(con, serie_id)
    q.borrar_serie(con, serie_id)
    return _respuesta_serie(request, con, s["sesion_id"], s["ejercicio_id"])


def _respuesta_serie(request: Request, con: sqlite3.Connection, sesion_id: int, ejercicio_id: int, error: str | None = None):
    if request.headers.get("HX-Request"):
        return _bloque(request, con, sesion_id, ejercicio_id, error)
    return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}#ej-{ejercicio_id}", status_code=303)


@router.post("/sesiones/{sesion_id}/repetir")
def sesion_repetir(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    anterior = q.sesion_anterior(con, sesion_id, "fuerza")
    if anterior and not q.bloques(con, sesion_id):
        q.repetir_sesion(con, sesion_id, anterior["id"], q.peso_corporal_g(con, _boveda(request)))
    return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}", status_code=303)


@router.post("/sesiones/{sesion_id}/guardar")
async def sesion_guardar(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    s = q.sesion(con, sesion_id)
    boveda = _boveda(request)
    clave = (str(form.get("vincular") or "") or None) if "vincular" in form else s["clave_importada"]
    vinculada = act.por_clave(con, boveda, clave) if clave else None
    if clave and vinculada is None:
        clave = None
    minutos = str(form.get("duracion_min") or "").strip()
    try:
        if minutos:
            duracion_s = round(float(minutos.replace(",", ".")) * 60)
        elif vinculada:
            duracion_s = vinculada.duracion_s
        elif s["tipo"] == "combate":
            duracion_s = q.duracion_combate(con, sesion_id)
        else:
            duracion_s = s["duracion_s"]
    except ValueError:
        return pagina_sesion(request, con, s, "La duración va en minutos, por ejemplo 55.")
    try:
        q.guardar_sesion(con, sesion_id, duracion_s=duracion_s, molestia=_int(form.get("molestia")),
                         sensaciones=_int(form.get("sensaciones")), notas=str(form.get("notas") or ""),
                         clave_importada=clave)
    except ErrorDatos as err:
        return pagina_sesion(request, con, s, str(err))
    if vinculada and not vinculada.confirmada and s["disciplina"] in ("judo", "bjj"):
        q.anotar(con, vinculada.clave, disciplina=s["disciplina"])  # confirma el "Judo o BJJ" de Polar
    if "vincular" in form and not clave and s["tipo"] in act.DISCIPLINAS_VINCULO:
        # "No vincular" con candidatas a la vista: Hoy no las vuelve a proponer para esta sesión
        cands = act.candidatas_vinculo(con, boveda, s["fecha"], act.DISCIPLINAS_VINCULO[s["tipo"]], sesion_id)
        act.descartar_vinculos(con, sesion_id, [a.clave for a in cands])
    actualizar_resumen(request, con)
    return RedirectResponse(f"/rendimiento/registrar?guardada={sesion_id}", status_code=303)


@router.post("/sesiones/{sesion_id}/vincular")
async def sesion_vincular(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    """Desde el aviso de Hoy: la sesión ya guardada es la que registró el reloj."""
    form = await request.form()
    try:
        act.vincular(con, _boveda(request), sesion_id, str(form.get("clave") or ""))
    except ErrorDatos as err:
        log.info("No se pudo vincular la sesión %s: %s", sesion_id, err)
        return RedirectResponse(f"/rendimiento/sesiones/{sesion_id}", status_code=303)
    actualizar_resumen(request, con)
    return RedirectResponse("/rendimiento#vinculos", status_code=303)


@router.post("/sesiones/{sesion_id}/descartar-vinculo")
async def sesion_descartar_vinculo(request: Request, sesion_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    claves = [str(c) for c in form.getlist("clave") if c]
    if claves:
        try:
            q.sesion(con, sesion_id)
        except ErrorDatos:
            return RedirectResponse("/rendimiento", status_code=303)
        act.descartar_vinculos(con, sesion_id, claves)
    return RedirectResponse("/rendimiento#vinculos", status_code=303)


@router.post("/sesiones/{sesion_id}/borrar")
def sesion_borrar(sesion_id: int, con: sqlite3.Connection = Con):
    q.borrar_sesion(con, sesion_id)
    return RedirectResponse("/rendimiento/registrar", status_code=303)


# ---------- Actividades del reloj (cardio, caminatas y todo lo importado) ----------

DISCIPLINAS_ELEGIBLES = {"judo": "Judo", "bjj": "BJJ", "muaythai": "Muay Thai", "fuerza": "Fuerza", "caminata": "Caminata",
                         "caminadora": "Caminadora", "carrera": "Carrera", "ciclismo": "Ciclismo", "cardio": "Cardio", "otro": "Otro"}


@router.get("/actividades")
def actividades_lista(request: Request, todas: int = 0, con: sqlite3.Connection = Con):
    boveda = _boveda(request)
    lista = sorted(act.todas(con, boveda), key=lambda a: (a.fecha, a.hora), reverse=True)
    if not todas:
        lista = lista[:30]
    notas = q.anotaciones(con)
    vinculadas = q.claves_vinculadas(con)
    imp = vault.importar(boveda)
    return render(request, "rendimiento/actividades.html", {
        "seccion": "registrar", "lista": lista, "notas": notas, "vinculadas": vinculadas, "todas": todas,
        "avisos": imp.avisos, **ctx_sync(request, con),
    })


@router.get("/actividad")
def actividad_ver(request: Request, clave: str, ok: int = 0, con: sqlite3.Connection = Con):
    a = act.por_clave(con, _boveda(request), clave)
    if a is None:
        return RedirectResponse("/rendimiento/actividades", status_code=303)
    return render(request, "rendimiento/actividad.html", {
        "seccion": "registrar", "a": a, "nota": q.anotaciones(con).get(clave), "ok": ok,
        "DISCIPLINAS": DISCIPLINAS_ELEGIBLES, "error": None,
    })


@router.post("/actividad")
async def actividad_guardar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    clave = str(form.get("clave") or "")
    a = act.por_clave(con, _boveda(request), clave)
    if a is None:
        return RedirectResponse("/rendimiento/actividades", status_code=303)
    campos: dict = {"sensaciones": _int(form.get("sensaciones")), "molestia_hombro": _int(form.get("molestia")),
                    "notas": str(form.get("notas") or "").strip() or None}
    disciplina = str(form.get("disciplina") or "")
    if disciplina in DISCIPLINAS_ELEGIBLES:
        campos["disciplina"] = disciplina
    if "es_entrenamiento" in form:
        campos["es_entrenamiento"] = 1 if form.get("es_entrenamiento") == "1" else 0
    error = None
    if campos["sensaciones"] is not None and not 1 <= campos["sensaciones"] <= 5:
        error = "Las sensaciones van de 1 a 5."
    elif campos["molestia_hombro"] is not None and not 0 <= campos["molestia_hombro"] <= 10:
        error = "La molestia del hombro va de 0 a 10."
    if error:
        return render(request, "rendimiento/actividad.html", {
            "seccion": "registrar", "a": a, "nota": q.anotaciones(con).get(clave), "ok": 0,
            "DISCIPLINAS": DISCIPLINAS_ELEGIBLES, "error": error}, 422)
    q.anotar(con, clave, **campos)
    actualizar_resumen(request, con)
    return RedirectResponse(f"/rendimiento/actividad?clave={clave}&ok=1", status_code=303)


# ---------- Sincronizar sensores ----------

def ctx_sync(request: Request, con: sqlite3.Connection, trabajo_id: int | None = None) -> dict:
    activo = trabajos.activo(con)
    otro = activo if activo and activo["tipo"] != "sincronizar" else None  # un análisis ocupa la cola
    t = trabajos.trabajo(con, trabajo_id) if trabajo_id else (None if otro else activo) or trabajos.ultimo(con, "sincronizar")
    if t and t["tipo"] != "sincronizar":
        t = trabajos.ultimo(con, "sincronizar")
    ultimo_ok = trabajos.ultimo(con, "sincronizar", "listo")
    resultado = json.loads(t["resultado"]) if t and t["resultado"] else {}
    hace = None
    if ultimo_ok and ultimo_ok["fin"]:
        hace = max(0, (hoy() - date.fromisoformat(ultimo_ok["fin"][:10])).days)
    imp = vault.importar(_boveda(request))
    return {"t": t, "resultado": resultado, "hace": hace, "ultima": imp.ultima_fecha, "ocupado_por": otro,
            "polar_sin_auth": trabajos.polar_sin_autorizacion(resultado) if resultado else False}


@router.post("/sincronizar")
def sincronizar(request: Request, con: sqlite3.Connection = Con):
    exigir_externo(request.app.state.config, "sincronizar")
    imp = vault.importar(_boveda(request))
    tid, nuevo = trabajos.encolar(con, "sincronizar", {"ultima": imp.ultima_fecha, "hoy": hoy().isoformat()})
    if nuevo:
        trabajos.lanzar(request.app.state.config, tid)
    if request.headers.get("HX-Request"):
        es_sync = trabajos.trabajo(con, tid)["tipo"] == "sincronizar"
        return render(request, "rendimiento/_sync.html", ctx_sync(request, con, tid if es_sync else None))
    return RedirectResponse(request.headers.get("referer") or "/rendimiento/actividades", status_code=303)


@router.get("/trabajos/{trabajo_id}")
def trabajo_estado(request: Request, trabajo_id: int, con: sqlite3.Connection = Con):
    ctx = ctx_sync(request, con, trabajo_id)
    resp = render(request, "rendimiento/_sync.html", ctx)
    if ctx["t"] and ctx["t"]["estado"] == "listo" and request.headers.get("HX-Request"):
        resp.headers["HX-Refresh"] = "true"  # recarga la pantalla para mostrar lo que llegó
    return resp


# ---------- Comparar semanas ----------

@router.get("/comparar")
def comparar(request: Request, a: str = "", b: str = "", con: sqlite3.Connection = Con):
    boveda = _boveda(request)
    actual = logica.semana_iso(hoy())
    b = b if _semana_valida(b) else actual
    a = a if _semana_valida(a) else logica.semana_anterior(b)
    todas_act = act.todas(con, boveda)
    imp = vault.importar(boveda)
    sa = semanas.resumen(con, boveda, a, todas_act, imp)
    sb = semanas.resumen(con, boveda, b, todas_act, imp)
    metricas = semanas.comparar(sa, sb)
    grupos: dict[str, list] = {}
    for m in metricas:
        grupos.setdefault(m.grupo, []).append(m)
    opciones = semanas.semanas_recientes(hoy(), 52)
    etiquetas = {s: semanas.Semana(s, *logica.rango_semana(s)).etiqueta for s in set(opciones) | {a, b}}
    return render(request, "rendimiento/comparar.html", {
        "seccion": "analisis", "sa": sa, "sb": sb, "grupos": grupos, "opciones": opciones, "etiquetas": etiquetas,
        "a": a, "b": b,
    })


def _semana_valida(s: str) -> bool:
    try:
        logica.rango_semana(s)
        return True
    except ValorInvalido:
        return False


# ---------- Mi combate y Más ----------

PERIODOS = {"4": ("4 semanas", 28), "12": ("12 semanas", 84), "todo": ("Todo", None)}


@router.get("/combate")
def mi_combate(request: Request, periodo: str = "4", disciplina: str = "", con: sqlite3.Connection = Con):
    periodo = periodo if periodo in PERIODOS else "4"
    dias = PERIODOS[periodo][1]
    desde = (hoy() - timedelta(days=dias)).isoformat() if dias else "2000-01-01"
    disciplina = disciplina if disciplina in q.DISCIPLINAS_COMBATE else ""
    p = combate.patrones(con, desde, hoy().isoformat(), disciplina or None)
    return render(request, "rendimiento/mi_combate.html", {
        "seccion": "analisis", "p": p, "periodo": periodo, "PERIODOS": PERIODOS, "disciplina": disciplina,
        "DISCIPLINAS": {"": "Todas", "judo": "Judo", "bjj": "BJJ", "muaythai": "Muay Thai"},
    })


GRUPOS = ("piernas", "cadera", "empuje", "tirón", "core", "cuerpo completo")
TIPOS_CARGA = {"barra": "Barra", "maquina": "Máquina o polea", "mancuerna_par": "Mancuernas en par (kg de cada una)",
               "mancuerna_una": "Una mancuerna o kettlebell", "unilateral": "Unilateral (se cuentan los dos lados)",
               "peso_corporal": "Peso corporal", "peso_corporal_lastre": "Peso corporal más lastre"}


@router.get("/mas")
def mas(request: Request):
    return render(request, "rendimiento/mas.html", {"seccion": "mas"})


@router.get("/catalogo/ejercicios")
def catalogo_ejercicios(request: Request, ok: int = 0, con: sqlite3.Connection = Con):
    return render(request, "rendimiento/catalogo_ejercicios.html", {
        "seccion": "mas", "ejercicios": q.ejercicios(con, activos=False), "GRUPOS": GRUPOS, "TIPOS_CARGA": TIPOS_CARGA,
        "ok": ok, "error": None, "valores": {}})


@router.post("/catalogo/ejercicios")
async def catalogo_ejercicio_nuevo(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    v = {k: str(x) for k, x in form.items()}
    try:
        if v.get("grupo") not in GRUPOS or v.get("tipo_carga") not in TIPOS_CARGA:
            raise ErrorDatos("Elige el grupo muscular y el tipo de carga.")
        q.crear_ejercicio(con, v.get("nombre", ""), v["grupo"], v["tipo_carga"], v.get("carga_hombro") == "1")
    except ErrorDatos as err:
        return render(request, "rendimiento/catalogo_ejercicios.html", {
            "seccion": "mas", "ejercicios": q.ejercicios(con, activos=False), "GRUPOS": GRUPOS, "TIPOS_CARGA": TIPOS_CARGA,
            "ok": 0, "error": str(err), "valores": v}, 422)
    return RedirectResponse("/rendimiento/catalogo/ejercicios?ok=1", status_code=303)


@router.post("/catalogo/ejercicios/{ejercicio_id}")
async def catalogo_ejercicio_editar(request: Request, ejercicio_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    e = q.ejercicio(con, ejercicio_id)
    q.editar_ejercicio(con, ejercicio_id, e["grupo"], e["tipo_carga"],
                       form.get("carga_hombro") == "1" if "carga_hombro" in form else bool(e["carga_hombro"]),
                       form.get("activo") == "1" if "activo" in form else bool(e["activo"]))
    return RedirectResponse(f"/rendimiento/catalogo/ejercicios#e-{ejercicio_id}", status_code=303)


@router.get("/catalogo/tecnicas")
def catalogo_tecnicas(request: Request, disciplina: str = "judo", ok: int = 0, con: sqlite3.Connection = Con):
    disciplina = disciplina if disciplina in q.DISCIPLINAS_COMBATE else "judo"
    lista = con.execute("SELECT * FROM tecnicas WHERE disciplina = ? ORDER BY familia, nombre", (disciplina,)).fetchall()
    return render(request, "rendimiento/catalogo_tecnicas.html", {
        "seccion": "mas", "tecnicas": lista, "disciplina": disciplina, "ok": ok, "error": None, "valores": {},
        "DISCIPLINAS": {"judo": "Judo", "bjj": "BJJ", "muaythai": "Muay Thai"}})


@router.post("/catalogo/tecnicas")
async def catalogo_tecnica_nueva(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    v = {k: str(x) for k, x in form.items()}
    disciplina = v.get("disciplina", "judo")
    try:
        q.crear_tecnica(con, disciplina, v.get("familia", ""), v.get("nombre", ""))
    except ErrorDatos as err:
        lista = con.execute("SELECT * FROM tecnicas WHERE disciplina = ? ORDER BY familia, nombre", (disciplina,)).fetchall()
        return render(request, "rendimiento/catalogo_tecnicas.html", {
            "seccion": "mas", "tecnicas": lista, "disciplina": disciplina, "ok": 0, "error": str(err), "valores": v,
            "DISCIPLINAS": {"judo": "Judo", "bjj": "BJJ", "muaythai": "Muay Thai"}}, 422)
    return RedirectResponse(f"/rendimiento/catalogo/tecnicas?disciplina={disciplina}&ok=1", status_code=303)


@router.post("/catalogo/tecnicas/{tecnica_id}")
async def catalogo_tecnica_activar(request: Request, tecnica_id: int, con: sqlite3.Connection = Con):
    form = await request.form()
    q.activar_tecnica(con, tecnica_id, form.get("activo") == "1")
    t = con.execute("SELECT disciplina FROM tecnicas WHERE id = ?", (tecnica_id,)).fetchone()
    return RedirectResponse(f"/rendimiento/catalogo/tecnicas?disciplina={t[0] if t else 'judo'}#t-{tecnica_id}", status_code=303)


# ---------- Confirmar judo o BJJ por semana ----------

@router.get("/confirmar")
def confirmar(request: Request, ok: int = 0, con: sqlite3.Connection = Con):
    pendientes = act.sin_confirmar(con, _boveda(request))
    semanas_p: dict[str, list] = {}
    for a in pendientes:
        semanas_p.setdefault(logica.semana_iso(date.fromisoformat(a.fecha)), []).append(a)
    etiquetas = {s: semanas.Semana(s, *logica.rango_semana(s)).etiqueta for s in semanas_p}
    return render(request, "rendimiento/confirmar.html", {
        "seccion": "registrar", "semanas_p": semanas_p, "etiquetas": etiquetas, "ok": ok, "total": len(pendientes)})


@router.post("/confirmar")
async def confirmar_guardar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    pendientes = {a.clave for a in act.sin_confirmar(con, _boveda(request))}
    n = 0
    for clave, valor in form.multi_items():
        if clave.startswith("d:") and clave[2:] in pendientes and valor in ("judo", "bjj"):
            q.anotar(con, clave[2:], disciplina=str(valor))
            n += 1
    if n:
        actualizar_resumen(request, con)
    return RedirectResponse(f"/rendimiento/confirmar?ok={n}", status_code=303)
