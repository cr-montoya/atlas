"""Punto de entrada: app FastAPI con núcleo (PIN, layout) y módulos."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core import auth
from app.core.demo import AVISO, NoDisponibleEnDemo
from app.core.config import Config, leer_config, validar_demo
from app.core.db import conectar, migrar
from app.core.plantillas import crear_templates
from app.modules.finanzas.rutas import router as finanzas_router
from app.modules.finanzas.rutas_v2 import router as finanzas_v2_router
from app.modules.rendimiento.rutas import router as rendimiento_router
from app.modules.rendimiento.rutas_combate import router as rendimiento_combate_router
from app.modules.rendimiento.rutas_competencia import router as rendimiento_competencia_router
from app.modules.rendimiento.rutas_ia import router as rendimiento_ia_router
from app.modules.rendimiento.rutas_nutricion import router as rendimiento_nutricion_router
from app.modules.rendimiento.rutas_fotos import router as rendimiento_fotos_router
from app.modules.rendimiento.rutas_tests import router as rendimiento_tests_router
from app.modules.rendimiento.imagen_proyectada import limpiar_interrumpidos as limpiar_imagenes_interrumpidas
from app.modules.rendimiento.rutas_imagen import router as rendimiento_imagen_router
from app.modules.rendimiento.rutas_voz import router as rendimiento_voz_router
from app.modules.rendimiento.voz import recuperar as recuperar_voz
from app.modules.rendimiento.consultas import borrar_borradores_viejos
from app.modules.rendimiento import rutas as rutas_rendimiento
from app.modules.rendimiento.rutas_dia import router as rendimiento_dia_router
from app.modules.rendimiento.trabajos import recuperar_interrumpidos, sincronizar_al_arrancar

# Routers por módulo, en orden de registro. Finanzas vive en la raíz; los demás, bajo su prefijo.
ROUTERS = (finanzas_v2_router, finanzas_router, rendimiento_tests_router, rendimiento_fotos_router, rendimiento_router,
           rendimiento_combate_router, rendimiento_ia_router,
           rendimiento_nutricion_router, rendimiento_competencia_router, rendimiento_imagen_router,
           rendimiento_voz_router, rendimiento_dia_router)


def crear_app(config: Config | None = None) -> FastAPI:
    config = config or leer_config()
    if config.demo:
        validar_demo(config)  # antes de abrir o crear cualquier archivo

    app = FastAPI(title="Atlas", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config
    con = conectar(config.db_path)
    migrar(con)
    recuperar_interrumpidos(con)
    borrar_borradores_viejos(con, rutas_rendimiento.hoy())
    con.close()
    limpiar_imagenes_interrumpidas(config)
    recuperar_voz(config)
    if config.sincronizar_al_arrancar and not config.demo:
        sincronizar_al_arrancar(config)
    app.state.templates = crear_templates()
    app.state.templates.env.globals["demo"] = config.demo
    app.state.templates.env.globals["aviso_demo"] = AVISO

    @app.exception_handler(NoDisponibleEnDemo)
    def no_disponible(request: Request, err: NoDisponibleEnDemo):
        if request.headers.get("HX-Request"):
            return HTMLResponse(f'<p class="aviso" role="alert">{AVISO}</p>', status_code=409)
        volver = request.headers.get("referer") or "/"
        if not volver.startswith((str(request.base_url), "/")):
            volver = "/"
        return app.state.templates.TemplateResponse(
            request, "demo_no_disponible.html", {"aviso": AVISO, "volver": volver, "seccion": ""}, status_code=409)
    app.add_middleware(auth.SesionMiddleware)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "core" / "static"), name="static")

    @app.get("/salud")
    def salud():
        return {"ok": True}

    app.include_router(auth.router)
    for router in ROUTERS:
        app.include_router(router)
    return app
