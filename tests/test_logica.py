from datetime import date

import pytest

from app.modules.finanzas import logica
from app.modules.finanzas.logica import Linea, RepartoInvalido


def test_proximo_dia_pago():
    assert logica.proximo_dia_pago(date(2026, 10, 17)) == date(2026, 10, 30)
    assert logica.proximo_dia_pago(date(2026, 10, 30)) == date(2026, 10, 30)
    assert logica.proximo_dia_pago(date(2026, 10, 31)) == date(2026, 11, 15)
    assert logica.proximo_dia_pago(date(2027, 2, 16)) == date(2027, 2, 28)
    assert logica.proximo_dia_pago(date(2026, 12, 31)) == date(2027, 1, 15)


def test_ultimo_dia_pago():
    assert logica.ultimo_dia_pago(date(2026, 10, 17)) == date(2026, 10, 15)
    assert logica.ultimo_dia_pago(date(2026, 10, 30)) == date(2026, 10, 30)
    assert logica.ultimo_dia_pago(date(2026, 1, 10)) == date(2025, 12, 30)


def test_plantilla_para_fecha():
    assert logica.plantilla_para_fecha(date(2026, 10, 15)) == "15"
    assert logica.plantilla_para_fecha(date(2026, 10, 30)) == "30"
    assert logica.plantilla_para_fecha(date(2027, 2, 28)) == "30"


def test_resto_plantilla_15():
    lineas = [Linea("Educa", 1, 226582), Linea("Mercado", 1, 700000), Linea("Cositas", 1, 150000),
              Linea("Admin", 1, 130000), Linea("Mamá", 1, 250000), Linea("Datos", 1, 50000),
              Linea("Ahorro", 3, 1000000), Linea("Libre", 4, None, "resto")]
    r = logica.aplicar_plantilla(4650000, lineas, {})
    assert r[-1].monto == 4650000 - (226582 + 700000 + 150000 + 130000 + 250000 + 50000 + 1000000)
    assert sum(l.monto for l in r) == 4650000


def test_plantilla_30_pide_valor():
    lineas = [Linea("Mercado", 1, 700000), Linea("Tarjeta Uno", 2, None, "pedir", plantilla_linea_id=9),
              Linea("Libre", 4, None, "resto")]
    with pytest.raises(RepartoInvalido):
        logica.aplicar_plantilla(4650000, lineas, {})
    r = logica.aplicar_plantilla(4650000, lineas, {9: 1200000})
    assert [l.monto for l in r] == [700000, 1200000, 4650000 - 1900000]


def test_maximo_un_resto():
    with pytest.raises(RepartoInvalido):
        logica.validar_plantilla([Linea("A", 1, None, "resto"), Linea("B", 1, None, "resto")])


def test_resto_negativo_no_confirma():
    r = logica.aplicar_plantilla(100, [Linea("A", 1, 300), Linea("L", 4, None, "resto")], {})
    assert r[1].monto == -200
    ok, motivo = logica.puede_confirmar(100, [l.monto for l in r])
    assert not ok and "negativ" in motivo


def test_cuadre():
    c = logica.cuadre(1000, [400, 500])
    assert c.diferencia == 100 and not c.cuadra
    assert logica.cuadre(1000, [400, 600]).cuadra
    assert logica.cuadre(1000, [400, 700]).diferencia == -100


def test_totales_por_bolsillo():
    assert logica.totales_por_bolsillo([(1, 100), (2, 50), (1, 25)]) == {1: 125, 2: 50}


def test_fecha_estimada_sin_abonos():
    assert logica.fecha_estimada_cero(1000, [], date(2026, 10, 17)) is None
    # Abonos de hace más de 60 días no cuentan
    assert logica.fecha_estimada_cero(1000, [(date(2026, 7, 1), 500)], date(2026, 10, 17)) is None


def test_fecha_estimada_promedio_por_quincena():
    hoy = date(2026, 10, 17)
    # Abonos el 30 sep y el 15 oct: dos quincenas (la del 30 oct aún no llega)
    abonos = [(date(2026, 9, 30), 600), (date(2026, 10, 15), 600)]
    e = logica.fecha_estimada_cero(1000, abonos, hoy)
    assert e.promedio == 600
    assert e.quincenas == 2
    assert e.fecha == date(2026, 11, 15)  # 30 oct, 15 nov
    assert not e.pocos_datos
    # Llegado el 30 oct sin abonar, esa quincena cuenta y baja el promedio
    e = logica.fecha_estimada_cero(1000, abonos, date(2026, 10, 30))
    assert e.promedio == 400


def test_fecha_estimada_pocos_datos():
    e = logica.fecha_estimada_cero(183700, [(date(2026, 10, 15), 26000)], date(2026, 10, 17))
    assert e.pocos_datos
    assert e.promedio == 26000 and e.quincenas == 8
    assert e.fecha == date(2027, 2, 15)


def test_avance_meta_escalon_1():
    a = logica.Avance(12_000_000, 17_000_000)
    assert a.pct == 71 and a.faltan == 5_000_000
    assert logica.Avance(20, 10).pct == 100 and logica.Avance(20, 10).faltan == 0


def test_patrimonio_negativo():
    # Cuentas 12.853.000; deudas 15.787.784 COP en total
    p = logica.patrimonio([12_000_000, 452_000, 401_000], [(15_787_784, "COP")], 400000)
    assert p.neto == -2_934_784


def test_patrimonio_convierte_usd_con_trm_de_la_foto():
    p = logica.patrimonio([1_000_000], [(10000, "USD"), (500_000, "COP")], 400000)
    assert p.deudas_cop == 400_000 + 500_000
