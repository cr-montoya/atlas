"""Escenarios de openspec/changes/v1-bolsillos/specs/finanzas/spec.md."""

import re
from datetime import date

import pytest

from app.modules.finanzas import consultas as q
from app.modules.finanzas import rutas
from tests.conftest import PIN

RUTAS_DATOS = ["/", "/quincena", "/deudas", "/metas", "/fotos/nueva", "/mas", "/bolsillos",
               "/plantillas/15", "/exportar", "/exportar/2026-10-resumen-finanzas.md", "/quincena/1",
               "/deudas/1"]


@pytest.fixture(autouse=True)
def fijar_hoy(monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: date(2026, 10, 17))


# ---------- Acceso con PIN ----------

def test_pin_correcto_entra_al_tablero(anonimo, datos):
    r = anonimo.post("/login", data={"pin": PIN}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.cookies.get("finanzas_sesion") or anonimo.cookies.get("finanzas_sesion")
    assert cookie
    assert "max-age=2592000" in r.headers["set-cookie"].lower()  # 30 días
    assert "httponly" in r.headers["set-cookie"].lower()
    t = anonimo.get("/")
    assert t.status_code == 200 and "Patrimonio neto" in t.text


def test_pin_incorrecto_muestra_error_y_no_hay_datos(anonimo, datos):
    r = anonimo.post("/login", data={"pin": "0000"})
    assert r.status_code == 401 and "PIN incorrecto" in r.text
    for ruta in RUTAS_DATOS:
        s = anonimo.get(ruta, follow_redirects=False)
        assert s.status_code == 303, ruta
        assert s.headers["location"] == "/login"
        assert "Educa" not in s.text and "9.637.784" not in s.text
    h = anonimo.post("/quincena/cuadre", data={"neto": "1"}, headers={"HX-Request": "true"})
    assert h.status_code == 401 and h.headers["HX-Redirect"] == "/login" and h.text == ""


def test_cookie_manipulada_no_sirve(anonimo, datos):
    anonimo.cookies.set("finanzas_sesion", "usuario.falso.firma")
    assert anonimo.get("/", follow_redirects=False).status_code == 303


def test_bloqueo_tras_intentos(anonimo, datos):
    from app.core import auth
    auth._intentos.clear()
    for _ in range(5):
        anonimo.post("/login", data={"pin": "0000"})
    assert anonimo.post("/login", data={"pin": PIN}).status_code == 429
    auth._intentos.clear()


# ---------- Bolsillos ----------

def test_crear_bolsillo_aparece_en_plantillas_y_reparto(cliente, datos):
    r = cliente.post("/bolsillos", data={"nombre": "Viaje a la costa", "tipo": "ahorro"})
    assert r.status_code == 200 and "Viaje a la costa" in r.text
    assert "Viaje a la costa" in cliente.get("/plantillas/15").text
    assert "Viaje a la costa" in cliente.get("/quincena/linea-nueva").text


def test_bolsillo_tipo_invalido(cliente):
    r = cliente.post("/bolsillos", data={"nombre": "X", "tipo": "otro"})
    assert r.status_code == 422 and "Elige un tipo" in r.text


# ---------- Plantillas y reparto ----------

def _numeros(html: str) -> list[str]:
    return re.findall(r'name="monto"[^>]*value="([^"]*)"', html)


def test_reparto_cuadrado_plantilla_15(cliente, datos):
    r = cliente.post("/quincena/propuesta", data={"fecha": "2026-10-15", "neto": "4.650.000", "plantilla_id": datos["p15"]})
    assert r.status_code == 200
    montos = _numeros(r.text)
    assert montos[-1] == "2.143.418"  # Libre = neto menos las demás
    assert "Cuadra: 0" in r.text
    assert "Casa" in r.text and "Total por bolsillo" in r.text
    assert re.search(r'<button type="submit" class="primario"\s*>Confirmar reparto', r.text)


def test_plantilla_30_pide_factura_antes_del_resto(cliente, datos):
    f = cliente.get("/quincena/pedidos", params={"plantilla_id": datos["p30"]})
    assert "Factura Tarjeta Uno" in f.text
    r = cliente.post("/quincena/propuesta", data={"fecha": "2026-10-30", "neto": "4.650.000", "plantilla_id": datos["p30"]})
    assert r.status_code == 422 and "antes de calcular el resto" in r.text
    linea = q.lineas_plantilla(cliente.app.state and _con(cliente), datos["p30"])[1]
    r = cliente.post("/quincena/propuesta", data={
        "fecha": "2026-10-30", "neto": "4.650.000", "plantilla_id": datos["p30"],
        f"pedido_{linea.plantilla_linea_id}": "1.200.000"})
    assert r.status_code == 200
    assert _numeros(r.text) == ["700.000", "1.200.000", "0", "2.750.000"]


def _con(cliente):
    from app.core.db import conectar
    return conectar(cliente.app.state.config.db_path)


def _form_editor(datos, montos, neto="4.650.000", trm=None):
    b = datos["b"]
    filas = [("Educa", b["Casa"], "fijo", datos["d"]["educa"]), ("Mercado", b["Casa"], "fijo", ""),
             ("Ahorro", b["Ahorro"], "fijo", ""), ("Libre", b["Libre"], "resto", "")]
    data = [("fecha", "2026-10-15"), ("plantilla_id", str(datos["p15"])), ("neto", neto)]
    for (c, bid, modo, deuda), m in zip(filas, montos):
        data += [("concepto", c), ("bolsillo_id", str(bid)), ("modo", modo), ("deuda_id", str(deuda)), ("monto", m)]
    if trm:
        data.append(("trm", trm))
    return data


def test_reparto_descuadrado_desactiva_confirmar(cliente, datos):
    r = cliente.post("/quincena/cuadre", content=_url(_form_editor(datos, ["226.582", "700.000", "1.000.000", "2.765.620"])),
                     headers={"HX-Request": "true", "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200
    assert "Sobran" in r.text and "42.202" in r.text
    assert "disabled" in r.text
    assert "-" not in re.search(r"Sobran.*?</p>", r.text, re.S).group(0)
    r = cliente.post("/quincena/cuadre", content=_url(_form_editor(datos, ["226.582", "700.000", "1.000.000", "1.000.000"])),
                     headers={"HX-Request": "true", "Content-Type": "application/x-www-form-urlencoded"})
    assert "Faltan" in r.text and "1.723.418" in r.text and "disabled" in r.text


def _url(pares):
    from urllib.parse import urlencode
    return urlencode(pares)


def test_confirmar_descuadrado_no_guarda(cliente, datos):
    r = cliente.post("/quincena/confirmar", content=_url(_form_editor(datos, ["226.582", "700.000", "1.000.000", "1"])),
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 422 and "no da el neto" in r.text
    assert _con(cliente).execute("SELECT COUNT(*) FROM quincenas").fetchone()[0] == 0


def test_quincena_confirmada_guarda_y_abona(cliente, datos):
    montos = ["226.582", "700.000", "1.000.000", "2.723.418"]
    r = cliente.post("/quincena/confirmar", content=_url(_form_editor(datos, montos)),
                     headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.status_code == 303
    detalle = cliente.get(r.headers["location"])
    assert "Reparto confirmado" in detalle.text and "Abonos creados" in detalle.text
    con = _con(cliente)
    assert con.execute("SELECT COUNT(*) FROM quincena_lineas").fetchone()[0] == 4
    assert con.execute("SELECT saldo FROM deudas WHERE id = ?", (datos["d"]["educa"],)).fetchone()[0] == 9637784 - 226582
    mov = con.execute("SELECT * FROM movimientos_deuda").fetchall()
    assert len(mov) == 1 and mov[0]["monto"] == 226582 and mov[0]["quincena_id"]
    assert "15 oct 2026" in cliente.get("/quincena").text  # historial


def test_linea_a_deuda_usd_convierte_con_trm(cliente, datos):
    b = datos["b"]
    data = [("fecha", "2026-10-30"), ("plantilla_id", str(datos["p30"])), ("neto", "1.000.000"),
            ("concepto", "Tarjeta"), ("bolsillo_id", str(b["Tarjeta Uno"])), ("modo", "pedir"), ("deuda_id", str(datos["d"]["tarjeta"])), ("monto", "831.896"),
            ("concepto", "Libre"), ("bolsillo_id", str(b["Libre"])), ("modo", "resto"), ("deuda_id", ""), ("monto", "168.104")]
    sin_trm = cliente.post("/quincena/confirmar", content=_url(data), headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert sin_trm.status_code == 422 and "TRM" in sin_trm.text
    r = cliente.post("/quincena/confirmar", content=_url(data + [("trm", "3.199,60")]),
                     headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.status_code == 303
    con = _con(cliente)
    assert con.execute("SELECT saldo FROM deudas WHERE id = ?", (datos["d"]["tarjeta"],)).fetchone()[0] == 157700
    m = con.execute("SELECT * FROM movimientos_deuda").fetchone()
    assert (m["monto"], m["trm"], m["costo_cop"]) == (26000, 319960, 831896)


# ---------- Deudas ----------

def test_abono_en_usd(cliente, datos):
    did = datos["d"]["tarjeta"]
    r = cliente.post(f"/deudas/{did}/abono", data={"fecha": "2026-10-15", "monto": "260,00", "trm": "3.199,60"})
    assert r.status_code == 200 and "Abono registrado" in r.text
    assert "1.577,00" in r.text
    m = _con(cliente).execute("SELECT * FROM movimientos_deuda WHERE deuda_id = ?", (did,)).fetchone()
    assert m["costo_cop"] == 831896 and m["trm"] == 319960 and m["tipo"] == "abono"


def test_abono_usd_sin_trm(cliente, datos):
    r = cliente.post(f"/deudas/{datos['d']['tarjeta']}/abono", data={"fecha": "2026-10-15", "monto": "10"})
    assert r.status_code == 422 and "TRM" in r.text


def test_abono_mayor_al_saldo(cliente, datos):
    r = cliente.post(f"/deudas/{datos['d']['tarjeta_cop']}/abono", data={"fecha": "2026-10-15", "monto": "300.000"})
    assert r.status_code == 422 and "supera el saldo" in r.text


def test_ajuste_por_extracto(cliente, datos):
    did = datos["d"]["educa"]
    r = cliente.post(f"/deudas/{did}/ajuste", data={"fecha": "2026-10-20", "saldo": "9.700.000"})
    assert r.status_code == 200 and "9.700.000" in r.text
    con = _con(cliente)
    assert con.execute("SELECT saldo FROM deudas WHERE id = ?", (did,)).fetchone()[0] == 9700000
    m = con.execute("SELECT * FROM movimientos_deuda WHERE deuda_id = ?", (did,)).fetchone()
    assert m["tipo"] == "ajuste" and m["monto"] == 9700000 - 9637784


def test_fecha_estimada_de_cero(cliente, datos, con):
    sin = cliente.get("/deudas").text
    assert "Sin abonos en los últimos 60 días" in sin
    q.abonar(con, datos["d"]["educa"], "2026-09-30", 226582, afecta_saldo=False)
    q.abonar(con, datos["d"]["educa"], "2026-10-15", 226582, afecta_saldo=False)
    html = cliente.get(f"/deudas/{datos['d']['educa']}").text
    assert "En cero hacia el" in html and "43 quincenas" in html and "Pocos datos" not in html


def test_fecha_estimada_usd_muestra_cop_y_pocos_datos(cliente, datos, con):
    q.abonar(con, datos["d"]["tarjeta"], "2026-10-15", 26000, trm=319961, costo_cop=831899, afecta_saldo=False)
    html = cliente.get(f"/deudas/{datos['d']['tarjeta']}").text
    assert "831.899" in html  # promedio por quincena en COP a la última TRM
    assert "Pocos datos" in html
    assert "15 de febrero" in html or "lunes 15 de febrero" in html


# ---------- Metas, foto y patrimonio ----------

def _foto(cliente, datos, nu="12.000.000", banc="401.000", fidu="452.000", deudas=None, fecha="2026-10-15", trm="3.197,65"):
    data = {"fecha": fecha, "trm": trm, f"cuenta_{datos['c']['Nu']}": nu,
            f"cuenta_{datos['c']['Banco Uno']}": banc, f"cuenta_{datos['c']['Fondo Uno']}": fidu}
    for k, v in (deudas or {}).items():
        data[f"deuda_{datos['d'][k]}"] = v
    return cliente.post("/fotos", data=data, follow_redirects=False)


def test_meta_escalon_1(cliente, datos):
    assert _foto(cliente, datos).status_code == 303
    html = cliente.get("/metas").text
    assert "71 %" in html and "Faltan 5.000.000" in html
    assert 'aria-valuenow="71"' in html


def test_patrimonio_negativo_en_rojo_con_serie(cliente, datos):
    # Deudas que suman 15.787.784 COP: todo en COP para que no dependa de la TRM
    _foto(cliente, datos, fecha="2026-09-30", deudas={"tarjeta": "0", "tarjeta_cop": "0", "educa": "15.000.000"})
    _foto(cliente, datos, deudas={"tarjeta": "0", "tarjeta_cop": "6.150.000", "educa": "9.637.784"})
    html = cliente.get("/").text
    assert re.search(r'class="cifra-hero neg">-2.934.784<', html)
    assert "grafica-patrimonio" in html and "echarts" in html
    assert "2026-09-30" in html and "2026-10-15" in html  # serie histórica


def test_foto_convierte_usd_con_trm_indicada(cliente, datos):
    _foto(cliente, datos, deudas={"tarjeta": "100,00", "tarjeta_cop": "0", "educa": "0"}, trm="4.000,00")
    html = cliente.get("/metas").text
    assert "-400.000" in html  # deudas en COP


# ---------- Tablero ----------

def test_tablero_orden_y_celular(cliente, datos):
    html = cliente.get("/").text
    orden = [html.index(t) for t in ['id="t-pago"', 'id="t-deudas"', 'id="t-metas"', 'id="t-patrimonio"', 'id="t-ultimo"']]
    assert orden == sorted(orden)
    assert 'name="viewport" content="width=device-width, initial-scale=1' in html
    assert "13 días" in html and "viernes 30 de octubre" in html.lower()
    css = cliente.get("/static/app.css").text
    assert "min-height: 48px" in css and "min-height: 44px" in css


# ---------- Exportar ----------

def test_exportar_octubre(cliente, datos, con):
    q.abonar(con, datos["d"]["tarjeta"], "2026-10-15", 26000, trm=319961, costo_cop=831899, afecta_saldo=False)
    _foto(cliente, datos)
    vista = cliente.get("/exportar", params={"mes": "2026-10"})
    assert vista.status_code == 200 and "2026-10-resumen-finanzas.md" in vista.text
    r = cliente.get("/exportar/2026-10-resumen-finanzas.md")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="2026-10-resumen-finanzas.md"'
    md = r.text
    hechos = [l for l in md.splitlines() if l.startswith("- ")]
    assert hechos and all(l.startswith("- [M] ") for l in hechos)
    assert all(l.endswith("[app finanzas 2026-10-17 | alta]") for l in hechos)
    assert "\u2014" not in md
    assert "Abono a Tarjeta USD el 2026-10-15: 260,00 USD con TRM 3.199,61 (costo 831.899 COP)" in md
    assert "Patrimonio neto" in md and "6 meses de básicos" in md
    assert not re.search(r"\d{8,}", md.replace(".", "x"))  # nada que parezca número de cuenta


def test_exportar_mes_invalido(cliente):
    assert cliente.get("/exportar/2026-13.md").status_code == 400


def test_sin_raya_larga_en_paginas(cliente, datos):
    for ruta in ["/", "/quincena", "/deudas", "/metas", "/mas", "/bolsillos", "/plantillas/15", "/exportar", "/fotos/nueva"]:
        assert "\u2014" not in cliente.get(ruta).text, ruta
