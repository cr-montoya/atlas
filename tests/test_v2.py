"""Escenarios de openspec/changes/v2-real-y-proyecciones/specs/finanzas/spec.md."""

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pytest

from app.core.db import conectar
from app.modules.finanzas import consultas as q
from app.modules.finanzas import real, resumen_ia, rutas
from app.modules.finanzas.logica import Linea

HOY = date(2026, 10, 17)
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.fixture(autouse=True)
def fijar_hoy(monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: HOY)


def _con(cliente):
    return conectar(cliente.app.state.config.db_path)


def _quincena(con, datos, fecha="2026-10-15", neto=4_650_000, lineas=None, tipo="quincena"):
    b = datos["b"]
    lineas = lineas or [
        Linea("Mitad del mercado", b["Casa"], 700_000),
        Linea("Ahorro", b["Ahorro"], 1_000_000),
        Linea("Libre", b["Libre"], neto - 1_700_000, "resto"),
    ]
    return q.confirmar_quincena(con, fecha, neto, datos["p15"], lineas, tipo=tipo)


def _linea(con, qid, concepto):
    return con.execute("SELECT id FROM quincena_lineas WHERE quincena_id = ? AND concepto = ?", (qid, concepto)).fetchone()[0]


# ---------- Pago real de una línea ----------

def test_marcar_pagada_con_un_toque_y_deshacer(cliente, datos, con):
    qid = _quincena(con, datos)
    lid = _linea(con, qid, "Mitad del mercado")
    r = cliente.post(f"/lineas/{lid}/pagada", headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'aria-pressed="true"' in r.text and 'id="pvr"' in r.text and "hx-swap-oob" in r.text
    p = con.execute("SELECT * FROM pagos WHERE linea_id = ?", (lid,)).fetchone()
    assert (p["monto"], p["fecha"]) == (700_000, "2026-10-17")
    assert real.linea(con, lid)["real"] == 700_000
    cliente.post(f"/lineas/{lid}/pagada", headers={"HX-Request": "true"})
    assert con.execute("SELECT COUNT(*) FROM pagos").fetchone()[0] == 0


def test_monto_real_distinto(cliente, datos, con):
    qid = _quincena(con, datos)
    lid = _linea(con, qid, "Mitad del mercado")
    r = cliente.post(f"/lineas/{lid}/real", data={"real": "735.000"}, headers={"HX-Request": "true"})
    assert "735.000" in r.text and re.search(r'class="neg">-35.000<', r.text)
    malo = cliente.post(f"/lineas/{lid}/real", data={"real": "73.50"}, headers={"HX-Request": "true"})
    assert 'aria-invalid="true"' in malo.text


def test_pago_distinto_no_cambia_el_abono(cliente, datos, con):
    b = datos["b"]
    qid = q.confirmar_quincena(con, "2026-10-15", 1_000_000, None, [
        Linea("Educa", b["Casa"], 226_582, deuda_id=datos["d"]["educa"]),
        Linea("Libre", b["Libre"], 773_418, "resto")])
    lid = _linea(con, qid, "Educa")
    cliente.post(f"/lineas/{lid}/real", data={"real": "230.000"})
    assert con.execute("SELECT monto FROM movimientos_deuda WHERE quincena_id = ?", (qid,)).fetchone()[0] == 226_582


# ---------- Gasto rápido y plan vs real ----------

def test_gasto_rapido_tres_toques(cliente, datos, con):
    qid = _quincena(con, datos)
    r = cliente.post("/gasto", data={"monto": "48.000", "bolsillo_id": datos["b"]["Libre"], "categoria_id": "1"},
                     follow_redirects=False)
    assert r.status_code == 303
    g = con.execute("SELECT * FROM gastos").fetchone()
    assert (g["monto"], g["fecha"], g["bolsillo_id"]) == (48_000, "2026-10-17", datos["b"]["Libre"])
    libre = next(b for b in real.plan_vs_real(con, qid) if b["nombre"] == "Libre")
    assert libre["real"] == 48_000
    pagina = cliente.get("/gasto")
    assert 'inputmode="numeric"' in pagina.text and "autofocus" in pagina.text and "comida" in pagina.text


@pytest.mark.parametrize("monto", ["48.00", ""])
def test_gasto_invalido(cliente, datos, con, monto):
    r = cliente.post("/gasto", data={"monto": monto, "bolsillo_id": datos["b"]["Libre"]})
    assert r.status_code == 422 and 'role="alert"' in r.text
    assert con.execute("SELECT COUNT(*) FROM gastos").fetchone()[0] == 0


def test_libre_excedido_y_sin_registrar(cliente, datos, con):
    b = datos["b"]
    qid = _quincena(con, datos, neto=2_646_690, lineas=[
        Linea("Mercado", b["Casa"], 700_000), Linea("Ahorro", b["Ahorro"], 1_000_000),
        Linea("Libre", b["Libre"], 946_690, "resto")])
    real.crear_gasto(con, "2026-10-16", 1_100_000, b["Libre"], None)
    real.crear_gasto(con, "2026-11-02", 5_000, b["Libre"], None)  # otro periodo: no cuenta
    pvr = {x["nombre"]: x for x in real.plan_vs_real(con, qid)}
    assert pvr["Libre"]["real"] == 1_100_000 and pvr["Libre"]["diferencia"] == -153_310
    assert pvr["Casa"]["real"] is None and pvr["Casa"]["diferencia"] is None
    html = cliente.get(f"/quincena/{qid}").text
    assert "sin registrar" in html and "-153.310" in html


# ---------- Ingresos extra ----------

def test_extra_sin_plantilla_propone_una_linea(cliente, datos):
    r = cliente.post("/quincena/propuesta", data={"fecha": "2026-10-31", "neto": "3.000.000", "plantilla_id": "0", "tipo": "extra"})
    assert r.status_code == 200
    assert re.findall(r'name="monto"[^>]*value="([^"]*)"', r.text) == ["3.000.000"]
    assert "Cuadra: 0" in r.text and 'name="tipo" value="extra"' in r.text


def test_extra_a_la_black_con_trm(cliente, datos, con):
    b = datos["b"]
    data = [("fecha", "2026-10-31"), ("plantilla_id", "0"), ("tipo", "extra"), ("neto", "3.000.000"), ("trm", "3.199,61"),
            ("concepto", "Abono Tarjeta USD"), ("bolsillo_id", b["Tarjeta Uno"]), ("modo", "fijo"), ("deuda_id", datos["d"]["tarjeta"]), ("fondo_id", ""), ("monto", "2.500.000"),
            ("concepto", "Libre"), ("bolsillo_id", b["Libre"]), ("modo", "resto"), ("deuda_id", ""), ("fondo_id", ""), ("monto", "500.000")]
    r = cliente.post("/quincena/confirmar", content=urlencode(data), headers=FORM, follow_redirects=False)
    assert r.status_code == 303
    m = con.execute("SELECT * FROM movimientos_deuda").fetchone()
    assert (m["monto"], m["costo_cop"]) == (78_135, 2_500_000)  # 781,35 USD
    assert "Extra" in cliente.get("/quincena").text
    assert con.execute("SELECT tipo FROM quincenas").fetchone()[0] == "extra"


def test_cesantias_que_superan_el_saldo(cliente, datos, con):
    b = datos["b"]
    data = [("fecha", "2027-02-15"), ("plantilla_id", "0"), ("tipo", "cesantias"), ("neto", "12.000.000"),
            ("concepto", "Cesantías a Educa"), ("bolsillo_id", b["Casa"]), ("modo", "fijo"), ("deuda_id", datos["d"]["educa"]), ("fondo_id", ""), ("monto", "12.000.000")]
    r = cliente.post("/quincena/confirmar", content=urlencode(data), headers=FORM)
    assert r.status_code == 422 and "supera el saldo" in r.text
    assert con.execute("SELECT COUNT(*) FROM quincenas").fetchone()[0] == 0


# ---------- Fondos de previsión ----------

def _soat(con, datos, fecha="2027-04-15"):
    return real.guardar_fondo(con, "SOAT", 343_300, fecha, 12, datos["b"]["Ahorro"], False)


def test_soat_linea_automatica_al_aplicar_y_aporte(cliente, datos, con):
    fid = _soat(con, datos)
    assert real.fondos(con, HOY)[0]["provision"] == 28_609 and real.fondos(con, HOY)[0]["quincenas"] == 12
    lid = q.lineas_plantilla(con, datos["p30"])[1].plantilla_linea_id
    r = cliente.post("/quincena/propuesta", data={"fecha": "2026-10-30", "neto": "4.650.000", "plantilla_id": datos["p30"],
                                                  f"pedido_{lid}": "1.200.000"})
    assert "Fondo SOAT" in r.text and "28.609" in r.text
    montos = re.findall(r'name="monto"[^>]*value="([^"]*)"', r.text)
    assert montos[-1] == "2.721.391"  # Libre = neto - 700.000 - 1.200.000 - 0 - 28.609
    data = [("fecha", "2026-10-30"), ("plantilla_id", datos["p30"]), ("tipo", "quincena"), ("neto", "4.650.000")]
    fondos_ids = re.findall(r'name="fondo_id" value="([^"]*)"', r.text)
    for (c, bid, modo, deu), fo, m in zip(
            re.findall(r'name="concepto" value="([^"]*)">\s*<input type="hidden" name="bolsillo_id" value="(\d+)">\s*'
                       r'<input type="hidden" name="modo" value="(\w+)">\s*<input type="hidden" name="deuda_id" value="([^"]*)">', r.text),
            fondos_ids, montos):
        data += [("concepto", c), ("bolsillo_id", bid), ("modo", modo), ("deuda_id", deu), ("fondo_id", fo), ("monto", m)]
    ok = cliente.post("/quincena/confirmar", content=urlencode(data), headers=FORM, follow_redirects=False)
    assert ok.status_code == 303
    assert real.fondos(con, HOY)[0]["f"]["acumulado"] == 28_609
    assert con.execute("SELECT fondo_id FROM quincena_lineas WHERE concepto = 'Fondo SOAT'").fetchone()[0] == fid


def test_fondo_sin_fecha_o_sin_monto(cliente, datos, con):
    real.guardar_fondo(con, "SOAT", 343_300, None, 12, datos["b"]["Ahorro"], False)
    real.guardar_fondo(con, "Odontología", 0, "2027-03-01", None, datos["b"]["Ahorro"], True)
    assert real.lineas_fondo(con, date(2026, 10, 30)) == []
    html = cliente.get("/futuro").text
    assert "Falta la fecha" in html and "Falta el monto" in html and "estimado" in html


def test_usar_fondo_recurrente(cliente, datos, con):
    fid = real.guardar_fondo(con, "Mantenimiento moto", 200_000, "2027-01-15", 3, datos["b"]["Ahorro"], False)
    con.execute("INSERT INTO fondo_movimientos (fondo_id, fecha, tipo, monto) VALUES (?, '2027-01-01', 'aporte', 200000)", (fid,))
    con.commit()
    r = cliente.post(f"/fondos/{fid}/uso", data={"fecha": "2027-01-15", "monto": "200.000"}, follow_redirects=False)
    assert r.status_code == 303
    x = real.fondos(con, HOY)[0]
    assert x["f"]["acumulado"] == 0 and x["f"]["fecha_objetivo"] == "2027-04-15"


def test_fondo_completo_no_agrega_linea(datos, con):
    fid = _soat(con, datos)
    con.execute("INSERT INTO fondo_movimientos (fondo_id, fecha, tipo, monto) VALUES (?, '2026-10-01', 'aporte', 343300)", (fid,))
    con.commit()
    assert real.fondos(con, HOY)[0]["provision"] == 0 and real.lineas_fondo(con, date(2026, 10, 30)) == []


# ---------- Natillera ----------

def _natillera(con, datos):
    b_nat = q.crear_bolsillo(con, "Natillera", "ahorro")
    fid = real.guardar_fondo(con, "Natillera", 0, "2026-11-30", 12, b_nat, True, aporte_mensual=120_000, aporte_proximo=150_000)
    con.execute("INSERT INTO fondo_movimientos (fondo_id, fecha, tipo, monto, nota) VALUES (?, '2026-09-30', 'aporte', 1200000, '10 aportes')", (fid,))
    con.commit()
    return fid, b_nat


def test_natillera_aporte_en_plantilla_del_30_y_no_es_colchon(cliente, datos, con):
    fid, b_nat = _natillera(con, datos)
    b = datos["b"]
    qid = q.confirmar_quincena(con, "2026-10-30", 1_000_000, datos["p30"], [
        Linea("Natillera", b_nat, 120_000, fondo_id=fid), Linea("Rifa natillera", b["Casa"], 10_000),
        Linea("Libre", b["Libre"], 870_000, "resto")])
    assert qid
    nat = next(x for x in real.fondos(con, HOY) if x["f"]["nombre"] == "Natillera")
    assert nat["f"]["acumulado"] == 1_320_000 and nat["aporte_fijo"] and nat["provision"] == 0
    assert real.lineas_fondo(con, date(2026, 11, 30)) == []  # no se provisiona sola
    # Colchón y meta 1 solo con Nu
    cliente.post("/fotos", data={"fecha": "2026-10-17", "trm": "3.197,65", f"cuenta_{datos['c']['Nu']}": "12.000.000"})
    real.guardar_escenario(con, {"gasto_basico": 2_900_000})
    ind = real.indicadores(con, HOY)
    assert ind["fondo_emergencia"] == 12_000_000 and ind["colchon_decimas"] == 41
    assert q.avance_metas(con)[0]["avance"].pct == 71


def test_natillera_devolucion_cambia_aporte(cliente, datos, con):
    fid, _ = _natillera(con, datos)
    cliente.post(f"/fondos/{fid}/uso", data={"fecha": "2026-11-30", "monto": "1.200.000"})
    f = real.fondo(con, fid)
    assert (f["aporte_mensual"], f["aporte_proximo"], f["fecha_objetivo"]) == (150_000, None, "2027-11-30")


def test_plantilla_guarda_fondo_de_la_linea(cliente, datos, con):
    fid, b_nat = _natillera(con, datos)
    html = cliente.get("/plantillas/30").text
    assert "Aporta a un fondo de aporte fijo" in html and f'value="{fid}"' in html
    data = [("concepto", "Natillera"), ("bolsillo_id", b_nat), ("modo", "fijo"), ("monto", "120.000"), ("deuda_id", ""), ("fondo_id", fid),
            ("concepto", "Libre"), ("bolsillo_id", datos["b"]["Libre"]), ("modo", "resto"), ("monto", ""), ("deuda_id", ""), ("fondo_id", "")]
    cliente.post("/plantillas/30", content=urlencode(data), headers=FORM)
    assert q.lineas_plantilla(con, datos["p30"])[0].fondo_id == fid


# ---------- Proyección, escenarios, avalancha ----------

def test_futuro_muestra_proyeccion_y_avisos(cliente, datos, con):
    real.guardar_escenario(con, {"neto_quincena": 4_650_000, "gasto_basico": 2_900_000})
    real.guardar_evento(con, "Extra Freelance", "2026-10-31", "ingreso", None, True, datos["d"]["tarjeta"], None, "extra")
    html = cliente.get("/futuro").text
    assert "grafica-proyeccion" in html and "Avalancha" in html and "Bola de nieve" in html
    assert "Educa sin tasa" in html and "Extra Freelance sin monto" in html
    assert "Patrimonio proyectado" in html


def test_escenario_tarjeta_mes_en_vivo_y_guardado(cliente, datos, con):
    cliente.post("/fotos", data={"fecha": "2026-10-15", "trm": "3.197,65", f"cuenta_{datos['c']['Nu']}": "12.000.000"})
    base = {"neto_quincena": "4.650.000", "gasto_basico": "2.900.000", "libre": "500.000", "ahorro_mensual": "0",
            "meses": "24", "estrategia": "avalancha", "meta_m4": "54.000.000"}
    a = cliente.post("/futuro/proyeccion", data={**base, "tarjeta_mes": "1.000.000"}, headers={"HX-Request": "true"})
    b = cliente.post("/futuro/proyeccion", data={**base, "tarjeta_mes": "1.500.000"}, headers={"HX-Request": "true"})
    def cero(html, nombre):
        m = re.search(nombre + r" en cero</span><span class=\"monto cifra\">([^<]+)<", html)
        return m.group(1)
    assert cero(a.text, "Tarjeta USD") <= cero(b.text, "Tarjeta USD")
    r = cliente.post("/futuro/escenario", data={**base, "tarjeta_mes": "1.500.000"}, follow_redirects=False)
    assert r.status_code == 303 and real.escenario(con)["tarjeta_mes"] == 1_500_000
    js = json.loads((cliente.app.state.config.exports_path / "resumen-ia.json").read_text())
    assert js["escenario"]["tarjeta_mes"] == 1_500_000


def test_incapacidad_apagada_por_defecto_y_editable(cliente, datos, con):
    assert real.escenario(con)["incapacidad_activa"] == 0
    r = cliente.post("/futuro/escenario", data={"incapacidad_activa": "1", "incapacidad_inicio": "2027-02",
                                                "incapacidad_meses": "2", "incapacidad_pct": "66,67"}, follow_redirects=False)
    assert r.status_code == 303
    e = real.escenario(con)
    assert (e["incapacidad_activa"], e["incapacidad_inicio"], e["incapacidad_pct_ppm"]) == (1, "2027-02", 666_700)


def test_tasa_y_cuota_de_deuda(cliente, datos, con):
    r = cliente.post(f"/deudas/{datos['d']['tarjeta']}/parametros", data={"tasa": "2,1285", "cuota": "0"}, follow_redirects=False)
    assert r.status_code == 303
    assert q.deuda(con, datos["d"]["tarjeta"])["tasa_mensual_ppm"] == 21_285
    assert "2,1285" in cliente.get(f"/deudas/{datos['d']['tarjeta']}").text


# ---------- Indicadores ----------

def test_indicadores_del_spec(cliente, datos, con):
    b = datos["b"]
    real.guardar_escenario(con, {"gasto_basico": 2_900_000})
    q.confirmar_quincena(con, "2026-10-15", 4_650_000, datos["p15"], [
        Linea("Ahorro", b["Ahorro"], 1_000_000), Linea("Libre", b["Libre"], 3_650_000, "resto")])
    ind = real.indicadores(con, HOY)
    assert ind["tasa_ahorro"] == 22
    q.confirmar_quincena(con, "2026-10-30", 4_650_000, None, [Linea("Libre", b["Libre"], 4_650_000, "resto")])
    q.abonar(con, datos["d"]["educa"], "2026-10-20", 1_800_000)
    ind = real.indicadores(con, HOY)
    assert ind["deuda_ingreso"] == 19  # 1.800.000 / 9.300.000
    html = cliente.get("/").text
    for t in ['id="t-pago"', 'id="t-ind"', 'id="t-deudas"', 'id="t-metas"', 'id="t-fondos"', 'id="t-patrimonio"', 'id="t-ultimo"']:
        assert t in html
    orden = [html.index(t) for t in ['id="t-pago"', 'id="t-ind"', 'id="t-deudas"', 'id="t-metas"', 'id="t-fondos"', 'id="t-patrimonio"', 'id="t-ultimo"']]
    assert orden == sorted(orden)


# ---------- Revisión y resumen para IA ----------

def test_revision_guardada_en_resumen_y_exportar(cliente, datos, con):
    r = cliente.post("/revision", data={"mes": "2026-10", "distinto": "La Tarjeta Uno llegó en 1,4 M", "inesperado": "",
                                        "ajustar": "Subir el SOAT", "plantillas": "", "sensacion": "4"}, follow_redirects=False)
    assert r.status_code == 303
    assert real.revision(con, "2026-10")["sensacion"] == 4
    js = json.loads((cliente.app.state.config.exports_path / "resumen-ia.json").read_text())
    assert js["revision"]["distinto"] == "La Tarjeta Uno llegó en 1,4 M"
    md = cliente.get("/exportar/2026-10-resumen-finanzas.md").text
    assert "## Revisión del mes" in md and "Subir el SOAT" in md
    assert all(l.startswith("- [M] ") for l in md.splitlines() if l.startswith("- "))


def test_resumen_ia_al_confirmar_quincena(cliente, datos, con):
    b = datos["b"]
    data = [("fecha", "2026-11-15"), ("plantilla_id", "0"), ("tipo", "quincena"), ("neto", "1.000.000"),
            ("concepto", "Libre"), ("bolsillo_id", b["Libre"]), ("modo", "resto"), ("deuda_id", ""), ("fondo_id", ""), ("monto", "1.000.000")]
    assert cliente.post("/quincena/confirmar", content=urlencode(data), headers=FORM, follow_redirects=False).status_code == 303
    carpeta = cliente.app.state.config.exports_path
    js = json.loads((carpeta / "resumen-ia.json").read_text())
    assert js["schema_version"] == "1"
    for k in ("generado", "periodo", "quincenas", "plan_vs_real", "gastos", "abonos", "deudas", "fondos", "metas",
              "indicadores", "proyeccion_resumen", "escenario", "revision"):
        assert k in js, k
    assert any(x["fecha"] == "2026-11-15" for x in js["quincenas"])
    assert all(d["moneda"] in ("COP", "USD") for d in js["deudas"])
    md = (carpeta / "resumen-ia.md").read_text()
    assert "—" not in md and "—" not in (carpeta / "resumen-ia.json").read_text()
    assert all(l.endswith("[app finanzas 2026-10-17 | alta]") for l in md.splitlines() if l.startswith("- [M]"))
    assert not list(carpeta.glob(".resumen-ia*"))  # sin temporales


def test_resumen_ia_no_escribe_fuera_de_exports(datos, con, tmp_path):
    js, md = resumen_ia.escribir(con, tmp_path / "salida", HOY)
    assert js.parent == md.parent == tmp_path / "salida"
    assert oct(js.stat().st_mode)[-3:] == "600"


def test_exports_ignorado_por_git():
    assert "exports/" in (Path(__file__).parents[1] / ".gitignore").read_text().splitlines()


def test_paginas_v2_sin_raya_larga(cliente, datos):
    for ruta in ["/futuro", "/gasto", "/fondos/nuevo", "/eventos/nuevo", "/revision", "/"]:
        r = cliente.get(ruta)
        assert r.status_code == 200, ruta
        assert "—" not in r.text, ruta


def test_diferencia_solo_de_lineas_marcadas(cliente, datos, con):
    b = datos["b"]
    qid = q.confirmar_quincena(con, "2026-10-30", 1_000_000, None, [
        Linea("Mercado", b["Casa"], 700_000), Linea("Cositas", b["Casa"], 150_000), Linea("Mamá", b["Casa"], 150_000)])
    real.marcar_pago(con, _linea(con, qid, "Mercado"), "2026-10-30")
    real.marcar_pago(con, _linea(con, qid, "Cositas"), "2026-10-30", 160_000)
    casa = real.plan_vs_real(con, qid)[0]
    assert (casa["real"], casa["diferencia"], casa["marcadas"], casa["lineas"]) == (860_000, -10_000, 2, 3)
    assert "2 de 3 líneas" in cliente.get(f"/quincena/{qid}").text


def test_rendimiento_de_cuenta_y_comparacion(cliente, datos, con):
    fid = datos["c"]["Fondo Uno"]
    r = cliente.post(f"/cuentas/{fid}/rendimiento", data={"ea": "9,00", "nota": "variable, sin Fogafín"}, follow_redirects=False)
    assert r.status_code == 303
    assert "9 % E.A." in cliente.get("/bolsillos").text and "variable, sin Fogafín" in cliente.get("/bolsillos").text
    real.actualizar_deuda(con, datos["d"]["educa"], 5_811, 226_582, prepagar=False)
    comp = real.comparacion_rendimiento(con)
    f = next(x for x in comp["frases"] if x["deuda"] == "Educa")
    assert f["dif_ppm"] == 11_700 and f["texto"].startswith("Ahorrar en Fondo Uno rinde más")  # 9 % menos 7 % de retención = 8,37 %
    html = cliente.get("/futuro").text
    assert "Ahorrar o prepagar" in html and "1,17 puntos de diferencia" in html and "8,37 % E.A. neto" in html
    malo = cliente.post(f"/cuentas/{fid}/rendimiento", data={"ea": "9,123456"})
    assert malo.status_code == 422


def test_perfiles_de_gasto_libre(cliente, datos, con):
    r = cliente.post("/futuro/escenario", data={"perfil": "medio"}, follow_redirects=False)
    assert r.status_code == 303
    e = real.escenario(con)
    assert (e["tarjeta_mes"], e["libre"]) == (1_250_000, 500_000)
    html = cliente.get("/futuro").text
    assert "Punto medio" in html and "Disciplinado" in html and "Relajado" in html
    assert re.search(r'value="medio" checked', html)


def test_viaje_sale_del_fondo_de_la_prima(datos, con):
    from app.modules.finanzas import futuro as fu
    fid = real.guardar_fondo(con, "Viaje de diciembre", 0, None, None, datos["b"]["Ahorro"], True)
    real.guardar_evento(con, "Prima de diciembre", "2026-12-15", "ingreso", 3_660_417, True, None, fid)
    real.guardar_evento(con, "Viaje de diciembre", "2026-12-18", "gasto", 3_660_417, True, None, fid)
    real.guardar_escenario(con, {"neto_quincena": 1_000_000, "gasto_basico": 2_000_000, "tarjeta_mes": 0, "libre": 0})
    e, _, _ = real.entrada_proyeccion(con, HOY)
    p = fu.proyectar(e)
    dic = next(m for m in p.meses if m.clave == "2026-12")
    nov = next(m for m in p.meses if m.clave == "2026-11")
    assert dic.fondos == 0  # la prima entra al fondo y el viaje la usa entera
    assert dic.emergencia == nov.emergencia  # la prima no va al ahorro


def test_escenario_inversion_largo_plazo(cliente, datos, con):
    e = real.escenario(con)
    assert (e["topar_en_m4"], e["inversion_ea_ppm"]) == (1, 100_000)  # por defecto: topar en M4 al 10 % E.A.
    r = cliente.post("/futuro/escenario", data={"inversion_ea": "12", "meta_m4": "54.000.000"}, follow_redirects=False)
    assert r.status_code == 303
    e = real.escenario(con)
    assert (e["topar_en_m4"], e["inversion_ea_ppm"]) == (0, 120_000)  # sin la casilla, no topa
    html = cliente.get("/futuro").text
    assert "Rendimiento esperado de la inversión" in html and "variable y sin garantía" in html
