"""Reglas de dinero puras (sin base de datos), cubiertas por pruebas."""

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.dinero import a_cop, porcentaje

TIPOS_BOLSILLO = ("fijo", "deuda", "ahorro", "libre")
TIPOS_INGRESO = {
    "quincena": "Quincena", "extra": "Extra", "prima": "Prima",
    "intereses_cesantias": "Intereses de cesantías", "cesantias": "Cesantías", "otro": "Otro ingreso",
}
VENTANA_ABONOS_DIAS = 60


# ---------- Días de pago (15 y 30; en febrero, el último día) ----------

def dias_pago_del_mes(anio: int, mes: int) -> list[date]:
    ultimo = calendar.monthrange(anio, mes)[1]
    return [date(anio, mes, 15), date(anio, mes, min(30, ultimo))]


def proximo_dia_pago(hoy: date, incluir_hoy: bool = True) -> date:
    anio, mes = hoy.year, hoy.month
    while True:
        for d in dias_pago_del_mes(anio, mes):
            if d > hoy or (incluir_hoy and d == hoy):
                return d
        anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)


def ultimo_dia_pago(hoy: date) -> date:
    """El día de pago más reciente que ya llegó (hoy incluido)."""
    anio, mes = hoy.year, hoy.month
    while True:
        pasados = [d for d in dias_pago_del_mes(anio, mes) if d <= hoy]
        if pasados:
            return pasados[-1]
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)


def dias_pago_despues(hoy: date, n: int) -> date:
    """El n-ésimo día de pago estrictamente después de hoy (n >= 1)."""
    d = hoy
    for _ in range(n):
        d = proximo_dia_pago(d, incluir_hoy=False)
    return d


def plantilla_para_fecha(fecha: date) -> str:
    return "15" if fecha.day <= 15 else "30"


def periodo(fecha: date) -> int:
    """Número correlativo de quincena: dos por mes."""
    return (fecha.year * 12 + fecha.month - 1) * 2 + (0 if fecha.day <= 15 else 1)


# ---------- Plantillas y reparto ----------

class RepartoInvalido(ValueError):
    pass


@dataclass
class Linea:
    concepto: str
    bolsillo_id: int
    monto: int | None = None
    modo: str = "fijo"  # fijo | pedir | resto
    deuda_id: int | None = None
    plantilla_linea_id: int | None = None
    extra: dict = field(default_factory=dict)
    fondo_id: int | None = None


def validar_plantilla(lineas: list[Linea]) -> None:
    restos = [l for l in lineas if l.modo == "resto"]
    if len(restos) > 1:
        raise RepartoInvalido("Una plantilla puede tener máximo una línea de resto.")
    for l in lineas:
        if l.modo == "fijo" and (l.monto is None or l.monto < 0):
            raise RepartoInvalido(f"La línea «{l.concepto}» necesita un monto.")


def aplicar_plantilla(neto: int, lineas: list[Linea], pedidos: dict[int, int]) -> list[Linea]:
    """Devuelve las líneas con monto: las fijas tal cual, las 'pedir' con el valor dado,
    y la de resto con el neto menos la suma de las demás (puede salir negativa)."""
    validar_plantilla(lineas)
    salida: list[Linea] = []
    for i, l in enumerate(lineas):
        monto = l.monto
        if l.modo == "pedir":
            clave = l.plantilla_linea_id if l.plantilla_linea_id is not None else i
            if clave not in pedidos:
                raise RepartoInvalido(f"Falta el valor de «{l.concepto}».")
            monto = pedidos[clave]
        salida.append(Linea(l.concepto, l.bolsillo_id, monto, l.modo, l.deuda_id, l.plantilla_linea_id,
                            fondo_id=l.fondo_id))
    resto = [l for l in salida if l.modo == "resto"]
    if resto:
        resto[0].monto = neto - sum(l.monto for l in salida if l.modo != "resto")
    return salida


@dataclass
class Cuadre:
    neto: int
    asignado: int

    @property
    def diferencia(self) -> int:
        """Positiva: falta por repartir. Negativa: se repartió de más."""
        return self.neto - self.asignado

    @property
    def cuadra(self) -> bool:
        return self.diferencia == 0


def cuadre(neto: int, montos: list[int]) -> Cuadre:
    return Cuadre(neto, sum(montos))


def puede_confirmar(neto: int, montos: list[int]) -> tuple[bool, str]:
    if neto <= 0:
        return False, "El neto debe ser mayor que cero."
    if not montos:
        return False, "El reparto no tiene líneas."
    if any(m < 0 for m in montos):
        return False, "Hay líneas negativas: las fijas superan el neto."
    c = cuadre(neto, montos)
    if not c.cuadra:
        return False, "La suma de las líneas no da el neto."
    return True, ""


def totales_por_bolsillo(lineas: list[tuple[int, int]]) -> dict[int, int]:
    """[(bolsillo_id, monto)] -> {bolsillo_id: total}, en orden de aparición."""
    tot: dict[int, int] = {}
    for b, m in lineas:
        tot[b] = tot.get(b, 0) + m
    return tot


# ---------- Deudas ----------

@dataclass
class Estimado:
    fecha: date
    quincenas: int
    promedio: int  # por quincena, en la moneda de la deuda
    pocos_datos: bool


def fecha_estimada_cero(saldo: int, abonos: list[tuple[date, int]], hoy: date) -> Estimado | None:
    """Promedio de abono por quincena con los abonos de los últimos 60 días.
    Las quincenas se cuentan desde la del primer abono de la ventana hasta la del último
    día de pago ya ocurrido (la quincena en curso cuenta cuando llega su día de pago).
    Sin abonos recientes no hay fecha."""
    if saldo <= 0:
        return None
    desde = hoy - timedelta(days=VENTANA_ABONOS_DIAS)
    recientes = [(f, m) for f, m in abonos if desde < f <= hoy and m > 0]
    if not recientes:
        return None
    total = sum(m for _, m in recientes)
    primero = min(f for f, _ in recientes)
    n_periodos = max(1, periodo(ultimo_dia_pago(hoy)) - periodo(primero) + 1)
    promedio = total // n_periodos
    if promedio <= 0:
        return None
    quincenas = -(-saldo // promedio)
    periodos_con_abono = {periodo(f) for f, _ in recientes}
    return Estimado(
        fecha=dias_pago_despues(hoy, quincenas),
        quincenas=quincenas,
        promedio=promedio,
        pocos_datos=len(periodos_con_abono) < 2,
    )


# ---------- Metas y patrimonio ----------

@dataclass
class Avance:
    actual: int
    objetivo: int

    @property
    def pct(self) -> int:
        return min(100, porcentaje(self.actual, self.objetivo))

    @property
    def faltan(self) -> int:
        return max(0, self.objetivo - self.actual)


@dataclass
class Patrimonio:
    activos: int
    deudas_cop: int

    @property
    def neto(self) -> int:
        return self.activos - self.deudas_cop


def patrimonio(saldos_cuentas: list[int], deudas: list[tuple[int, str]], trm: int) -> Patrimonio:
    """Suma de cuentas menos deudas convertidas a COP con la TRM de la foto."""
    return Patrimonio(
        activos=sum(saldos_cuentas),
        deudas_cop=sum(a_cop(s, moneda, trm) for s, moneda in deudas),
    )
