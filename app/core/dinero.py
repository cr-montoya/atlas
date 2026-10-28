"""Montos como enteros: COP en pesos, USD en centavos, TRM en centavos de peso.

Formato colombiano: punto para miles y coma para decimales ("4.650.000", "1.837,00").
Nunca se usa float para montos.
"""

import re


class MontoInvalido(ValueError):
    pass


_LIMPIAR = re.compile(r"[\s$]|COP|USD", re.IGNORECASE)


def _limpiar(texto: str) -> tuple[bool, str]:
    if texto is None:
        raise MontoInvalido("Escribe un monto.")
    t = _LIMPIAR.sub("", str(texto))
    negativo = t.startswith("-")
    if negativo:
        t = t[1:]
    if not t:
        raise MontoInvalido("Escribe un monto.")
    return negativo, t


def _partes(t: str) -> tuple[str, str]:
    """Separa entero y decimales con formato colombiano (coma decimal, punto de miles)."""
    if t.count(",") > 1:
        raise MontoInvalido(f"No entiendo el monto «{t}».")
    entero, _, dec = t.partition(",")
    if "." in entero:
        grupos = entero.split(".")
        if not grupos[0] or any(len(g) != 3 for g in grupos[1:]) or len(grupos[0]) > 3:
            raise MontoInvalido(f"No entiendo el monto «{t}». Usa puntos para los miles: 4.650.000")
        entero = "".join(grupos)
    if not entero.isdigit() or (dec and not dec.isdigit()):
        raise MontoInvalido(f"No entiendo el monto «{t}».")
    return entero, dec


def parse_cop(texto: str, permitir_negativo: bool = False) -> int:
    """'4.650.000' -> 4650000. Acepta ',00' al final; rechaza centavos de peso."""
    negativo, t = _limpiar(texto)
    entero, dec = _partes(t)
    if dec.strip("0"):
        raise MontoInvalido("Los pesos no llevan decimales.")
    valor = int(entero)
    if negativo:
        if not permitir_negativo:
            raise MontoInvalido("El monto no puede ser negativo.")
        valor = -valor
    return valor


def parse_centavos(texto: str, permitir_negativo: bool = False) -> int:
    """'1.837,00' -> 183700; '260' -> 26000; '3.199,61' -> 319961."""
    negativo, t = _limpiar(texto)
    entero, dec = _partes(t)
    if len(dec) > 2:
        raise MontoInvalido("Usa máximo dos decimales.")
    valor = int(entero) * 100 + int(dec.ljust(2, "0") or 0)
    if negativo:
        if not permitir_negativo:
            raise MontoInvalido("El monto no puede ser negativo.")
        valor = -valor
    return valor


parse_usd = parse_centavos
parse_trm = parse_centavos


def parse_moneda(texto: str, moneda: str, permitir_negativo: bool = False) -> int:
    if moneda == "USD":
        return parse_centavos(texto, permitir_negativo)
    return parse_cop(texto, permitir_negativo)


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fmt_cop(pesos: int | None) -> str:
    if pesos is None:
        return ""
    signo = "-" if pesos < 0 else ""
    return signo + _miles(abs(pesos))


def fmt_centavos(centavos: int | None) -> str:
    if centavos is None:
        return ""
    signo = "-" if centavos < 0 else ""
    entero, dec = divmod(abs(centavos), 100)
    return f"{signo}{_miles(entero)},{dec:02d}"


fmt_usd = fmt_centavos
fmt_trm = fmt_centavos


def fmt_moneda(valor: int | None, moneda: str) -> str:
    return fmt_centavos(valor) if moneda == "USD" else fmt_cop(valor)


def div_redondeo(a: int, b: int) -> int:
    """División entera con redondeo a la mitad hacia arriba (en valor absoluto)."""
    if b == 0:
        raise ZeroDivisionError
    signo = -1 if (a < 0) != (b < 0) else 1
    q, r = divmod(abs(a), abs(b))
    if r * 2 >= abs(b):
        q += 1
    return signo * q


def usd_a_cop(centavos_usd: int, trm_centavos: int) -> int:
    """260,00 USD a TRM 3.199,60 -> 831.896 COP."""
    return div_redondeo(centavos_usd * trm_centavos, 10_000)


def cop_a_usd(pesos: int, trm_centavos: int) -> int:
    """Centavos de USD que compra un monto en pesos a una TRM."""
    return div_redondeo(pesos * 10_000, trm_centavos)


def a_cop(valor: int, moneda: str, trm_centavos: int | None) -> int:
    if moneda == "USD":
        if not trm_centavos:
            raise ValueError("Falta la TRM para convertir USD a COP.")
        return usd_a_cop(valor, trm_centavos)
    return valor


def porcentaje(parte: int, total: int) -> int:
    """Porcentaje entero redondeado: 12.000.000 de 17.000.000 -> 71."""
    if total <= 0:
        return 0
    return div_redondeo(parte * 100, total)


def parse_tasa(texto: str) -> int:
    """Porcentaje a partes por millón: '2,1285' -> 21285; '2' -> 20000. Máximo 4 decimales."""
    negativo, t = _limpiar(str(texto).replace("%", ""))
    if negativo:
        raise MontoInvalido("La tasa no puede ser negativa.")
    entero, dec = _partes(t)
    if len(dec) > 4:
        raise MontoInvalido("Usa máximo cuatro decimales en la tasa.")
    return int(entero) * 10_000 + int(dec.ljust(4, "0") or 0)


def fmt_tasa(ppm: int | None) -> str:
    """21285 -> '2,1285'; 20000 -> '2'."""
    if ppm is None:
        return ""
    entero, dec = divmod(ppm, 10_000)
    dec_txt = f"{dec:04d}".rstrip("0")
    return f"{_miles(entero)},{dec_txt}" if dec_txt else _miles(entero)


def ea_a_mensual_ppm(ea_ppm: int) -> int:
    """Tasa efectiva anual a mensual equivalente, ambas en ppm: 9,00 % E.A. -> 7.207 (0,7207 % mensual).
    Usa Decimal solo para la raíz; el resultado es entero."""
    from decimal import Decimal, getcontext
    getcontext().prec = 30
    m = (1 + Decimal(ea_ppm) / 1_000_000) ** (Decimal(1) / 12) - 1
    return int((m * 1_000_000).to_integral_value())


def mensual_a_ea_ppm(mensual_ppm: int) -> int:
    """Tasa mensual a efectiva anual, en ppm: 5.811 (0,5811 % mensual) -> 72.000 (7,2 % E.A.)."""
    from decimal import Decimal, getcontext
    getcontext().prec = 30
    ea = (1 + Decimal(mensual_ppm) / 1_000_000) ** 12 - 1
    return int((ea * 1_000_000).to_integral_value())
