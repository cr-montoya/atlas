from datetime import date

from app.modules.finanzas import futuro as fu
from app.modules.finanzas.futuro import DeudaSim, Entrada, EstadoFondo, EventoSim, FondoSim

HOY = date(2026, 10, 17)


def test_quincenas_hasta():
    assert fu.quincenas_hasta(HOY, date(2027, 4, 15)) == 12
    assert fu.quincenas_hasta(date(2026, 10, 30), date(2026, 10, 30)) == 1
    assert fu.quincenas_hasta(HOY, date(2026, 10, 20)) == 0


def test_provision_soat():
    f = EstadoFondo(343300, 0, date(2027, 4, 15))
    assert f.quincenas(HOY) == 12
    assert f.provision(HOY) == 28609
    assert f.provision(date(2026, 10, 30)) == 28609


def test_provision_moto():
    assert EstadoFondo(200000, 0, date(2027, 1, 15)).provision(HOY) == 33334


def test_fondo_sin_fecha_o_monto():
    assert EstadoFondo(343300, 0, None).problema == "falta la fecha"
    assert EstadoFondo(343300, 0, None).provision(HOY) == 0
    assert EstadoFondo(0, 0, date(2027, 1, 1)).problema == "falta el monto"


def test_fondo_completo_y_vencido():
    assert EstadoFondo(100, 100, date(2027, 1, 1)).provision(HOY) == 0
    assert EstadoFondo(100, 40, date(2026, 10, 1)).provision(HOY) == 60  # ya pasó: todo ahora


def test_sumar_meses():
    assert fu.sumar_meses(date(2027, 1, 15), 3) == date(2027, 4, 15)
    assert fu.sumar_meses(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_interes_ppm():
    assert fu.interes(1_000_000, 21285) == 21285  # 2,1285 % mensual
    assert fu.interes(1_000_000, None) == 0


def test_avalancha_y_bola_del_spec():
    deudas = [DeudaSim("Tarjeta", 3_000_000, 20000), DeudaSim("Crédito", 1_000_000, 10000)]
    a = fu.comparar_estrategia(deudas, 1_000_000, "avalancha")
    b = fu.comparar_estrategia(deudas, 1_000_000, "bola")
    assert a.meses_cero == {"Tarjeta": 4, "Crédito": 5} and a.mes_libre == 5 and a.intereses == 167955
    assert b.meses_cero == {"Tarjeta": 5, "Crédito": 2} and b.mes_libre == 5 and b.intereses == 201353
    assert a.orden == ["Tarjeta", "Crédito"] and b.orden == ["Crédito", "Tarjeta"]
    assert deudas[0].saldo == 3_000_000  # no muta la entrada


def _entrada(**kw):
    base = dict(hoy=date(2026, 11, 1), meses=12, neto_quincena=1_000_000, gasto_basico=1_000_000,
                tarjeta_mes=0, libre=0, ahorro_mensual=0, estrategia="avalancha",
                deudas=[DeudaSim("A", 2_000_000)], fondos=[], eventos=[], emergencia=0, otros_activos=0)
    base.update(kw)
    return Entrada(**base)


def test_proyeccion_simple_sin_intereses():
    # Ingreso 2 M, gasto 1 M: sobra 1 M al mes para la deuda de 2 M.
    p = fu.proyectar(_entrada())
    assert p.fecha_cero == {"A": "2026-12"} and p.mes_libre == "2026-12"
    assert p.meses[2].emergencia == 1_000_000  # en enero ya sin deuda, todo al colchón
    assert p.avisos == ["A sin tasa: la fecha de cero puede ser optimista."]


def test_proyeccion_tarjeta_mes_mas_alta_retrasa():
    a = fu.proyectar(_entrada(meses=24, deudas=[DeudaSim("Tarjeta", 6_000_000, 21285)], tarjeta_mes=0))
    b = fu.proyectar(_entrada(meses=24, deudas=[DeudaSim("Tarjeta", 6_000_000, 21285)], tarjeta_mes=500_000))
    assert a.fecha_cero["Tarjeta"] < b.fecha_cero["Tarjeta"]


def test_evento_a_deuda_y_estimado():
    ev = EventoSim("Cesantías", date(2027, 2, 15), "ingreso", 1_500_000, True, deuda="A")
    p = fu.proyectar(_entrada(neto_quincena=500_000, deudas=[DeudaSim("A", 1_500_000)], eventos=[ev]))
    assert p.fecha_cero["A"] == "2027-02"
    assert "Cesantías (estimado)" in p.meses[3].eventos


def test_evento_sin_monto_avisa():
    ev = EventoSim("Extra Freelance", date(2026, 11, 30), "ingreso", None, True, deuda="A")
    p = fu.proyectar(_entrada(eventos=[ev]))
    assert any("Extra Freelance sin monto" in a for a in p.avisos)


def test_cuota_minima_con_deficit():
    # Ingreso igual al gasto básico (que incluye la cuota): la cuota se paga y no sobra nada.
    p = fu.proyectar(_entrada(neto_quincena=500_000, deudas=[DeudaSim("S", 1_000_000, None, 200_000)]))
    assert p.meses[0].abonos == {"S": 200_000}
    assert p.meses[0].emergencia == 0


def test_incapacidad_baja_el_ingreso():
    normal = fu.proyectar(_entrada())
    inc = fu.proyectar(_entrada(incapacidad=("2027-01", 2, 666700)))
    assert inc.meses[2].ingreso == 1_333_400 and normal.meses[2].ingreso == 2_000_000
    assert inc.meses[4].ingreso == 2_000_000


def test_fondo_en_proyeccion_provisiona_y_usa():
    f = FondoSim("SOAT", 300_000, 0, date(2027, 1, 15), 12)
    p = fu.proyectar(_entrada(deudas=[], fondos=[f], meses=4))
    assert p.meses[2].fondos == 0 and "Uso SOAT" in p.meses[2].eventos  # enero: se usa
    assert f.acumulado == 0  # la entrada no muta


def test_meses_colchon_y_metas():
    p = fu.proyectar(_entrada(deudas=[], emergencia=12_000_000, gasto_basico=2_900_000, neto_quincena=1_450_000, meta1=17_000_000))
    assert p.meses[0].meses_colchon_decimas == 41
    assert p.mes_meta1 is None


def test_natillera_devuelve_en_noviembre_y_reinicia():
    nat = FondoSim("Natillera", 0, 1_200_000, date(2026, 11, 30), 12, 120_000, 150_000)
    ev = EventoSim("Intereses natillera", date(2026, 11, 30), "ingreso", 200_000, True)
    p = fu.proyectar(_entrada(hoy=date(2026, 10, 17), deudas=[], fondos=[nat], eventos=[ev], meses=3,
                              emergencia=0, neto_quincena=1_000_000, gasto_basico=2_000_000))
    oct_, nov, dic = p.meses
    assert oct_.fondos == 1_320_000  # aporte del 30 oct
    assert nov.fondos == 0 and "Devolución Natillera" in nov.eventos
    assert nov.ingreso == 2_000_000 + 1_440_000 + 200_000  # quincenas + 12 aportes (incluido el del 30 nov) + intereses
    assert dic.fondos == 150_000  # ciclo nuevo
    assert nov.meses_colchon_decimas == div(nov.emergencia)


def div(emergencia):
    from app.core.dinero import div_redondeo
    return div_redondeo(emergencia * 10, 2_000_000)


def test_plan_sobrante_a_ahorro_tras_la_tarjeta():
    deudas = [DeudaSim("Tarjeta", 2_000_000, 21285), DeudaSim("Educa", 9_000_000, None, 200_000, prepagar=False)]
    p = fu.proyectar(_entrada(neto_quincena=1_500_000, gasto_basico=1_200_000, deudas=deudas, sobrante_a_ahorro=True))
    nov, dic, ene = p.meses[0], p.meses[1], p.meses[2]
    assert nov.abonos == {"Educa": 200_000, "Tarjeta": 1_800_000}
    assert p.fecha_cero["Tarjeta"] == "2026-12"  # 2.000.000 más intereses no alcanza en un mes
    assert ene.abonos == {"Educa": 200_000}  # sin tarjeta: solo la cuota
    assert ene.emergencia - dic.emergencia == 1_800_000  # el sobrante va al ahorro
    todo = fu.proyectar(_entrada(neto_quincena=1_500_000, gasto_basico=1_200_000, deudas=deudas, sobrante_a_ahorro=False))
    assert todo.meses[2].abonos["Educa"] > 200_000


def test_traslado_a_fondo_no_cambia_patrimonio():
    f = FondoSim("Odontología", 0, 0, None)
    ev = EventoSim("Natillera para odontología", date(2026, 11, 30), "traslado", 600_000, False, fondo="Odontología")
    sin = fu.proyectar(_entrada(deudas=[], fondos=[f], meses=2))
    con = fu.proyectar(_entrada(deudas=[], fondos=[f], eventos=[ev], meses=2))
    assert con.meses[0].fondos == 600_000
    assert con.meses[0].emergencia == sin.meses[0].emergencia - 600_000
    assert con.meses[0].patrimonio == sin.meses[0].patrimonio


def test_rendimiento_hace_crecer_el_ahorro():
    from app.core.dinero import ea_a_mensual_ppm, mensual_a_ea_ppm
    assert ea_a_mensual_ppm(90_000) == 7_207  # 9,00 % E.A. = 0,7207 % mensual
    assert mensual_a_ea_ppm(5_811) == 72_004  # 0,5811 % mensual = 7,2004 % E.A. (la app lo muestra como 7,2 %)
    base = dict(deudas=[], emergencia=10_000_000, otros_activos=1_000_000, neto_quincena=500_000, meses=12)
    sin = fu.proyectar(_entrada(**base))
    con = fu.proyectar(_entrada(**base, rend_emergencia_ppm=7_207, rend_otros_ppm=7_207))
    assert con.meses[1].rendimiento - sin.meses[1].rendimiento > 0
    assert con.meses[0].emergencia - sin.meses[0].emergencia == 72_070  # hoy = 1 nov: mes completo
    assert con.rendimientos > 0 and sin.rendimientos == 0
    assert con.meses[-1].patrimonio > sin.meses[-1].patrimonio


def test_rendimiento_neto_y_mes_en_curso_prorrateado():
    base = dict(hoy=date(2026, 11, 16), deudas=[], emergencia=10_000_000, otros_activos=0, neto_quincena=0,
                gasto_basico=0, meses=2, rend_emergencia_ppm=7_207)
    bruto = fu.proyectar(_entrada(**base))
    neto = fu.proyectar(_entrada(**base, retencion_ppm=70_000))
    # Noviembre desde el 16: 15 de 30 días -> mitad de 72.070 = 36.035; neto del 7 %: 36.035 - 2.522 = 33.513
    assert bruto.meses[0].rendimiento == 36_035
    assert neto.meses[0].rendimiento == 33_513
    assert neto.rendimientos < bruto.rendimientos


def test_tope_en_m4_y_sobrante_a_inversion():
    from app.core.dinero import ea_a_mensual_ppm
    base = dict(deudas=[], emergencia=9_000_000, neto_quincena=1_000_000, gasto_basico=1_000_000, meses=4,
                meta_m4=10_000_000)
    sin = fu.proyectar(_entrada(**base))
    con = fu.proyectar(_entrada(**base, tope_emergencia=10_000_000, rend_inversion_ppm=ea_a_mensual_ppm(100_000)))
    # Sobra 1 M al mes: en noviembre el fondo llega a 10 M (M4); desde diciembre todo va a la inversión
    assert [m.emergencia for m in con.meses] == [10_000_000] * 4
    assert con.meses[0].inversion == 0 and con.meses[1].inversion == 1_000_000
    assert con.meses[2].inversion == 1_000_000 + 7_974 + 1_000_000  # 10 % E.A. = 0,7974 % mensual
    assert con.mes_inicio_inversion == "2026-12" and con.mes_m4 == "2026-11"
    assert any("variable y sin garantía" in a for a in con.avisos)
    assert con.meses[-1].patrimonio > sin.meses[-1].patrimonio  # rinde la inversión
    assert sin.meses[-1].emergencia == 13_000_000  # sin tope, el fondo sigue creciendo
