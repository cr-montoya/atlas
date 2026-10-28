import pytest

from app.core.dinero import (MontoInvalido, cop_a_usd, fmt_cop, fmt_usd, parse_cop, parse_usd,
                             porcentaje, usd_a_cop)


@pytest.mark.parametrize("texto,valor", [
    ("4.650.000", 4650000), ("4650000", 4650000), ("$ 4.650.000", 4650000),
    ("4.650.000,00", 4650000), ("0", 0), (" 226.582 ", 226582), ("1.000", 1000),
])
def test_parse_cop(texto, valor):
    assert parse_cop(texto) == valor


@pytest.mark.parametrize("texto", ["", "abc", "4.48.380", "4,5", "1.2345", "12.34.567", "-5"])
def test_parse_cop_rechaza(texto):
    with pytest.raises(MontoInvalido):
        parse_cop(texto)


def test_parse_cop_negativo_permitido():
    assert parse_cop("-2.934.784", permitir_negativo=True) == -2934784


@pytest.mark.parametrize("texto,valor", [
    ("1.837,00", 183700), ("1837", 183700), ("260", 26000), ("260,5", 26050),
    ("3.199,61", 319961), ("0,01", 1), ("USD 1.577,00", 157700),
])
def test_parse_usd(texto, valor):
    assert parse_usd(texto) == valor


def test_parse_usd_rechaza_tres_decimales():
    with pytest.raises(MontoInvalido):
        parse_usd("1,234")


def test_formatos():
    assert fmt_cop(4650000) == "4.650.000"
    assert fmt_cop(-2934784) == "-2.934.784"
    assert fmt_cop(0) == "0"
    assert fmt_usd(183700) == "1.837,00"
    assert fmt_usd(157700) == "1.577,00"
    assert fmt_usd(5) == "0,05"


def test_ida_y_vuelta():
    for v in [0, 1, 999, 1000, 4650000, 123456789]:
        assert parse_cop(fmt_cop(v)) == v
        assert parse_usd(fmt_usd(v)) == v


def test_conversion_usd_cop_del_spec():
    # 260,00 USD a TRM 3.199,60 -> 831.896 COP
    assert usd_a_cop(26000, 319960) == 831896
    # Dato real: 260 USD a 3.199,61 -> 831.898,6 redondea a 831.899
    assert usd_a_cop(26000, 319961) == 831899


def test_cop_a_usd():
    assert cop_a_usd(831896, 319960) == 26000


def test_porcentaje_redondea():
    assert porcentaje(12_000_000, 17_000_000) == 71
    assert porcentaje(0, 10) == 0
    assert porcentaje(5, 0) == 0


def test_sin_float_en_resultados():
    assert isinstance(parse_cop("4.650.000"), int)
    assert isinstance(parse_usd("1.837,00"), int)
    assert isinstance(usd_a_cop(26000, 319960), int)


def test_tasa_en_ppm():
    from app.core.dinero import fmt_tasa, parse_tasa
    assert parse_tasa("2,1285") == 21285 and parse_tasa("2 %") == 20000 and parse_tasa("0,5") == 5000
    assert fmt_tasa(21285) == "2,1285" and fmt_tasa(20000) == "2" and fmt_tasa(666700) == "66,67"
    with pytest.raises(MontoInvalido):
        parse_tasa("1,23456")
