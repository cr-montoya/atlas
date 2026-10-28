"""Lógica pura de rendimiento: carga total, formatos de kg y medidas, semanas ISO y deltas."""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


class ValorInvalido(ValueError):
    """Un valor escrito por el usuario que no se puede interpretar; el mensaje dice cómo arreglarlo."""


# Carga total ---------------------------------------------------------------

def carga_serie_g(tipo_carga: str, reps: int, carga_g: int, peso_corporal_g: int | None) -> int | None:
    """Carga total de una serie en gramos, según el tipo de carga del ejercicio.

    - barra, máquina, una mancuerna o kettlebell: carga x repeticiones;
    - mancuernas en par: la carga es la de cada mancuerna, se cuentan las dos;
    - unilateral: la carga se mueve con cada lado, se cuentan los dos;
    - peso corporal (más lastre): peso corporal más reciente + lastre. Sin peso corporal, None.
    """
    if tipo_carga in ("barra", "maquina", "mancuerna_una"):
        return carga_g * reps
    if tipo_carga in ("mancuerna_par", "unilateral"):
        return carga_g * 2 * reps
    if tipo_carga in ("peso_corporal", "peso_corporal_lastre"):
        if peso_corporal_g is None:
            return None
        return (peso_corporal_g + (carga_g if tipo_carga == "peso_corporal_lastre" else 0)) * reps
    raise ValueError(f"Tipo de carga desconocido: {tipo_carga}")


# Formatos ------------------------------------------------------------------

def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fmt_decimal(mil: int, max_dec: int = 2) -> str:
    """Milésimas a texto colombiano: 47100 -> '47,1'; 1359750 -> '1.359,75'; 2400000 -> '2.400'."""
    signo = "-" if mil < 0 else ""
    mil = abs(mil)
    escala = 10 ** (3 - max_dec)
    redondo = (mil + escala // 2) // escala * escala
    entero, frac = divmod(redondo, 1000)
    texto = _miles(entero)
    decs = f"{frac:03d}"[:max_dec].rstrip("0")
    return signo + texto + ("," + decs if decs else "")


def fmt_kg(g: int | None) -> str:
    """Gramos a kg: 2400000 -> '2.400 kg'; 1359750 -> '1.359,75 kg'."""
    return "sin dato" if g is None else f"{fmt_decimal(g)} kg"


def fmt_carga(g: int) -> str:
    """Carga de una serie para el campo: 100000 -> '100'; 22500 -> '22,5'."""
    return fmt_decimal(g)


def parse_kg(texto: str) -> int:
    """'100', '22,5', '22.5' -> gramos. Acepta vacío como 0 (peso corporal sin lastre)."""
    t = (texto or "").strip().lower().replace("kg", "").strip()
    if not t:
        return 0
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ValorInvalido("Escribe la carga en kg, por ejemplo 100 o 22,5.") from None
    if d < 0 or d > 1000:
        raise ValorInvalido("La carga debe estar entre 0 y 1.000 kg.")
    return int((d * 1000).to_integral_value())


def parse_decimal_mil(texto: str) -> int:
    """'51,69' -> 51690 (milésimas)."""
    t = (texto or "").strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", t):
        t = t.replace(".", "")
    t = t.replace(",", ".")
    try:
        return int((Decimal(t) * 1000).to_integral_value())
    except InvalidOperation:
        raise ValorInvalido("Escribe un número, por ejemplo 51,69.") from None


def fmt_duracion(s: int | None) -> str:
    """Segundos a '41,3 min' o '1 h 12 min'."""
    if s is None:
        return "sin dato"
    if s >= 3600:
        h, resto = divmod(round(s / 60), 60)
        return f"{h} h {resto} min" if resto else f"{h} h"
    minutos = Decimal(s) / 60
    return f"{fmt_decimal(int((minutos * 1000).to_integral_value()), 1)} min"


def fmt_rpe(x10: int | None) -> str:
    return "" if x10 is None else fmt_decimal(x10 * 100, 1)


# Semanas ISO ----------------------------------------------------------------

def semana_iso(d: date) -> str:
    a, s, _ = d.isocalendar()
    return f"{a}-W{s:02d}"


def rango_semana(semana: str) -> tuple[date, date]:
    m = re.fullmatch(r"(\d{4})-W(\d{2})", semana or "")
    if not m:
        raise ValorInvalido("La semana va como 2026-W42.")
    lunes = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return lunes, lunes + timedelta(days=6)


def semana_anterior(semana: str) -> str:
    lunes, _ = rango_semana(semana)
    return semana_iso(lunes - timedelta(days=7))


# Deltas ---------------------------------------------------------------------

@dataclass(frozen=True)
class Delta:
    valor: int                 # en la unidad de la métrica (milésimas, gramos, segundos o conteo)
    pct_mil: int | None        # porcentaje en milésimas de punto (13,3 % = 13300); None si la base es 0
    clase: str                 # pos | neg | neutro
    sube: bool

    @property
    def signo(self) -> str:
        return "+" if self.valor > 0 else ("-" if self.valor < 0 else "")


def delta(antes: int | None, despues: int | None, direccion: str) -> Delta | None:
    """Delta de B frente a A. El color sigue la dirección de la métrica; neutra va en tinta."""
    if antes is None or despues is None:
        return None
    d = despues - antes
    pct = None if antes == 0 else round(d * 100_000 / abs(antes))
    if d == 0 or direccion == "neutra":
        clase = "neutro"
    elif (d > 0) == (direccion == "mas"):
        clase = "pos"
    else:
        clase = "neg"
    return Delta(d, pct, clase, d > 0)


def fmt_pct(pct_mil: int | None) -> str:
    """13300 -> '13,3 %' (sin signo; el signo lo pone la plantilla con el delta)."""
    if pct_mil is None:
        return ""
    return f"{fmt_decimal(abs(pct_mil), 1)} %"


# Tendencia de la molestia del hombro --------------------------------------------

AVISO_MOLESTIA = "Si la molestia persiste, consúltalo con tu fisio u ortopedista"


def molestia_al_alza(valores: list[int]) -> bool:
    """Tres registros seguidos en alza, o +2 puntos o más entre el promedio de los últimos tres y el de los tres anteriores."""
    if len(valores) >= 3 and valores[-3] < valores[-2] < valores[-1]:
        return True
    if len(valores) >= 6:
        ultimos, previos = valores[-3:], valores[-6:-3]
        return sum(ultimos) / 3 - sum(previos) / 3 >= 2
    return False
