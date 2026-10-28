"""Módulos de Atlas (la app del Life Brain): nombre, ruta de inicio y secciones de su navegación."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Seccion:
    clave: str
    ruta: str
    nombre: str
    icono: str


@dataclass(frozen=True)
class Modulo:
    clave: str
    nombre: str
    inicio: str
    prefijo: str
    secciones: tuple[Seccion, ...]


FINANZAS = Modulo("finanzas", "Finanzas", "/", "", (
    Seccion("inicio", "/", "Inicio", "house"),
    Seccion("quincena", "/quincena", "Quincena", "wallet"),
    Seccion("deudas", "/deudas", "Deudas", "credit-card"),
    Seccion("futuro", "/futuro", "Futuro", "chart-line-up"),
    Seccion("mas", "/mas", "Más", "dots-three"),
))

RENDIMIENTO = Modulo("rendimiento", "Rendimiento", "/rendimiento", "/rendimiento", (
    Seccion("hoy", "/rendimiento", "Hoy", "pulse"),
    Seccion("registrar", "/rendimiento/registrar", "Registrar", "plus-circle"),
    Seccion("analisis", "/rendimiento/analisis", "Análisis", "chart-line-up"),
    Seccion("tests", "/rendimiento/tests", "Tests", "gauge"),
    Seccion("mas", "/rendimiento/mas", "Más", "dots-three"),
))

MODULOS = (FINANZAS, RENDIMIENTO)


def modulo_de(ruta: str) -> Modulo:
    """Finanzas vive en la raíz (sus rutas no cambian); los demás módulos, bajo su prefijo."""
    for m in MODULOS:
        if m.prefijo and (ruta == m.prefijo or ruta.startswith(m.prefijo + "/")):
            return m
    return FINANZAS
