"""Acceso con PIN y cookie de sesión firmada (itsdangerous), válida 30 días."""

import hmac
import os
import time
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from starlette.middleware.base import BaseHTTPMiddleware

COOKIE = "brain_sesion"
# Cookie de antes de la app multi-módulo: se sigue aceptando para no cerrar sesiones abiertas.
COOKIE_ANTERIOR = "finanzas_sesion"
RUTAS_LIBRES = ("/login", "/static/", "/salud", "/caddy-raiz.crt")
MAX_INTENTOS = 5
BLOQUEO_SEG = 300

router = APIRouter()
_intentos: dict[str, list[float]] = {}


def _firmador(request: Request) -> TimestampSigner:
    return TimestampSigner(request.app.state.config.secreto, salt="sesion")


def _cookies(request: Request) -> tuple[str, ...]:
    """La demo usa solo su cookie; la app real, la suya y la anterior a la app multi-módulo."""
    cfg = request.app.state.config
    return (cfg.cookie,) if cfg.demo else (cfg.cookie, COOKIE_ANTERIOR)


def sesion_valida(request: Request) -> bool:
    cfg = request.app.state.config
    for nombre in _cookies(request):
        valor = request.cookies.get(nombre)
        if not valor:
            continue
        try:
            _firmador(request).unsign(valor, max_age=cfg.dias_sesion * 86400)
            return True
        except (BadSignature, SignatureExpired):
            continue
    return False


class SesionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ruta = request.url.path
        if ruta.startswith(RUTAS_LIBRES) or sesion_valida(request):
            return await call_next(request)
        if request.headers.get("HX-Request"):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse("/login", status_code=303)


def _bloqueado(ip: str) -> bool:
    ahora = time.monotonic()
    recientes = [t for t in _intentos.get(ip, []) if ahora - t < BLOQUEO_SEG]
    _intentos[ip] = recientes
    return len(recientes) >= MAX_INTENTOS


@router.get("/login")
def login_form(request: Request):
    if sesion_valida(request):
        return RedirectResponse("/", status_code=303)
    return request.app.state.templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login(request: Request, pin: str = Form("")):
    ip = request.client.host if request.client else "?"
    tpl = request.app.state.templates
    if _bloqueado(ip):
        return tpl.TemplateResponse(
            request, "login.html",
            {"error": "Demasiados intentos. Espera 5 minutos y vuelve a probar."}, status_code=429,
        )
    if not hmac.compare_digest(pin.strip().encode(), request.app.state.config.pin.encode()):
        _intentos.setdefault(ip, []).append(time.monotonic())
        return tpl.TemplateResponse(
            request, "login.html", {"error": "PIN incorrecto. Revisa e intenta de nuevo."}, status_code=401,
        )
    _intentos.pop(ip, None)
    resp = RedirectResponse("/", status_code=303)
    firma = _firmador(request).sign("usuario").decode()
    for nombre in _cookies(request):  # las dos, para que una versión anterior de la app siga entrando
        resp.set_cookie(
            nombre, firma, max_age=request.app.state.config.dias_sesion * 86400, httponly=True, samesite="lax",
        )
    return resp


@router.get("/caddy-raiz.crt")
def certificado_raiz(request: Request):
    """Certificado raíz público de la CA interna de Caddy, para instalarlo en el celular (no es secreto).
    Se toma de BRAIN_CA_RAIZ o de ~/caddy-raiz.crt (ver README, "HTTPS para atlas.local")."""
    if request.app.state.config.demo:
        return Response("No disponible en la demo.", status_code=404, media_type="text/plain; charset=utf-8")
    ruta = Path(os.environ.get("BRAIN_CA_RAIZ", Path.home() / "caddy-raiz.crt"))
    if not ruta.is_file():
        return Response("Falta el certificado raíz: cópialo con los pasos del README.", status_code=404,
                        media_type="text/plain; charset=utf-8")
    return Response(ruta.read_bytes(), media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="atlas-raiz.crt"'})


@router.post("/salir")
def salir(request: Request):
    resp = RedirectResponse("/login", status_code=303)
    for nombre in _cookies(request):
        resp.delete_cookie(nombre)
    return resp
