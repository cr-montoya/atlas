"""Spec openspec/changes/v1-competencia: lector de la sección del torneo, cuenta regresiva, pesajes, checklist,
resumen para IA y vault intacto."""

import json
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import competencia as comp
from app.modules.rendimiento import resumen_ia, rutas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
HOY = date(2026, 10, 19)

SECCION = """---
type: training
---

# Planificación semanal (ficticia)

{antes}## Hacia el torneo XYZ (2026-11-07) · [U 2026-10-19 | alta]

- [M] Torneo: 2026-11-07 08:00 · Coliseo de Prueba · [S99 | alta]
- [H] Pesaje: 2026-11-06 17:00 a 18:00 · ropa interior · [S99, U 2026-10-19 | alta]
- [M] Límite: 78 kg · [S99 | alta]

- [H] Disponibilidad: lo que sea · [U 2026-10-19 | alta]
{validacion}
### Plan día por día

| Fecha | Judo y BJJ | Fuerza | Cardio | Notas |
| --- | --- | --- | --- | --- |
| 2026-10-19 | BJJ no-gi | Tests (hecho) | - | Controlar con la derecha |
| 2026-10-20 | BJJ gi | Centro Uno normal | - | - |
| 2026-10-26 | Club | Movilidad | - | Pesaje en casa en la mañana |
| 2026-11-05 | - | - | - | Pesaje en casa en la mañana: meta 77,5 kg o menos |
| 2026-11-06 | - | - | - | Pesaje oficial 17:00 a 18:00 |
| 2026-11-07 | Torneo, 08:00 | - | - | - |
{fila_extra}
### Guion de combate

- [O] **Si me lanzan, caigo:** ukemi y acepto el punto · [U 2026-10-19 | alta]
- [O] **Antes de cada combate:** tres respiraciones largas y la palabra "generar acciones" · [IA 2026-10-19]

### Checklist del día

- [O] Documento de identidad
- [O] Judogi
- [O] Kinesiotape
{tras_checklist}
## Vigente: octubre 2026

- [H] Otra cosa
"""

SUELTOS = "\n- [O] Peso: 77 kg, sin corte; ajustar con Laura · [IA 2026-10-19]\n- [O] Ukemi a diario · [IA 2026-10-19]\n"

OBJETIVOS = ("\n| Objetivo | Fecha | Estado | Fuente |\n| --- | --- | --- | --- |\n"
             "| **Torneo de BJJ, Open 2026:** categoría Adultos, división de -77 kg. | 2026-06-13 | No compitió | S02 |\n"
             "| **Torneo de judo, Juegos de Prueba 2026 (Liga):** categoría Mayores novatos (21 a 30 años), "
             "división de 70 a 78 kg. Inscrito | 2026-11-07 | Inscrito | S99 |\n")


def _escribir(boveda: Path, texto: str | None = None, **partes) -> None:
    valores = {"antes": "", "validacion": "", "fila_extra": "", "tras_checklist": SUELTOS} | partes
    (boveda / comp.PLAN).write_text(texto if texto is not None else SECCION.format(**valores), encoding="utf-8")
    vault.limpiar_cache()


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    _escribir(destino)
    with (destino / vault.OBJETIVOS).open("a", encoding="utf-8") as f:
        f.write(OBJETIVOS)
    vault.limpiar_cache()
    return destino


@pytest.fixture
def config(tmp_path, boveda):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db",
                  exports_path=tmp_path / "exports", vault_path=boveda, fotos_path=tmp_path / "fotos")


@pytest.fixture
def momento(monkeypatch):
    """Fija la fecha y la hora de la app; por defecto 2026-10-19 a las 9:00."""
    def fijar(dt: datetime):
        monkeypatch.setattr(comp, "ahora", lambda: dt)
        monkeypatch.setattr(rutas, "hoy", lambda: dt.date())
    fijar(datetime(2026, 10, 19, 9, 0))
    return fijar


@pytest.fixture(autouse=True)
def _momento_por_defecto(momento):
    return momento


def _c(boveda, hoy=HOY):
    return comp.vigente(boveda, hoy).competencia


def _cuenta_html(html: str, cual: str) -> str:
    i = html.index(f'id="k-{cual}"')
    return html[i:html.index("</section>", i)]


# Lector ---------------------------------------------------------------------

def test_datos_del_torneo_y_nombre(boveda):
    c = _c(boveda)
    assert c.nombre == "Juegos de Prueba 2026" and c.detalle == "Judo · Mayores novatos · 70 a 78 kg"
    assert c.torneo == datetime(2026, 11, 7, 8, 0) and c.lugar == "Coliseo de Prueba"
    assert c.pesaje_inicio == datetime(2026, 11, 6, 17, 0) and c.pesaje_fin == datetime(2026, 11, 6, 18, 0)
    assert c.pesaje_condicion == "ropa interior" and c.limite_g == 78000 and c.avisos == ()


@pytest.mark.parametrize("cambio", [
    ("17:00 a 18:00", "17:00-18:00"), ("17:00 a 18:00", "17:00 – 18:00"),
    ("- [M] Torneo:", "* [m] Torneo:"), ("- [M] Torneo:", "- [M][H] **Torneo:**"),
    ("Límite: 78", "Limite: 78"), ("## Hacia el torneo XYZ", "## hacia el Torneo XYZ"),
    ("### Guion de combate", "### Guión de combate"), ("### Checklist del día", "### Checklist del día del torneo"),
])
def test_variantes_toleradas(boveda, cambio):
    _escribir(boveda, SECCION.format(antes="", validacion="", fila_extra="", tras_checklist=SUELTOS).replace(*cambio))
    c = _c(boveda)
    assert c.torneo == datetime(2026, 11, 7, 8, 0) and c.pesaje_fin == datetime(2026, 11, 6, 18, 0)
    assert c.limite_g == 78000 and len(c.guion) == 2 and len(c.checklist) == 3 and c.avisos == ()


def test_crlf_bom_y_horas_sin_cero(boveda):
    texto = SECCION.format(antes="", validacion="", fila_extra="", tras_checklist=SUELTOS).replace("17:00 a 18:00", "7:00 a 7:30")
    (boveda / comp.PLAN).write_bytes(b"\xef\xbb\xbf" + texto.replace("\n", "\r\n").encode("utf-8"))
    vault.limpiar_cache()
    c = _c(boveda)
    assert c.pesaje_inicio == datetime(2026, 11, 6, 7, 0) and c.pesaje_fin == datetime(2026, 11, 6, 7, 30)
    assert len(c.plan) == 6 and len(c.checklist) == 3


@pytest.mark.parametrize("cambio,clave", [
    (("2026-11-07 08:00 · Coliseo", "2026-11-07 24:00 · Coliseo"), "Torneo"),
    (("2026-11-07 08:00 · Coliseo", "2026-11-31 08:00 · Coliseo"), "Torneo"),
    (("17:00 a 18:00", "18:00 a 17:00"), "Pesaje"),
])
def test_datos_invalidos_no_tumban_paginas(boveda, cliente, cambio, clave):
    _escribir(boveda, SECCION.format(antes="", validacion="", fila_extra="", tras_checklist=SUELTOS).replace(*cambio))
    hoy, metas, vista = (cliente.get(u) for u in ("/rendimiento", "/rendimiento/metas", "/rendimiento/competencia"))
    assert hoy.status_code == metas.status_code == vista.status_code == 200
    assert "Juegos de Prueba" not in hoy.text and "Juegos de Prueba" not in metas.text
    assert f"No pude leer la línea {clave} de planificacion-semanal.md" in vista.text and cambio[1] in vista.text


def test_partes_sin_leer(boveda, cliente):
    texto = SECCION.format(antes="", validacion="", fila_extra="| 2026-10-21 | solo | tres |", tras_checklist=SUELTOS)
    i = texto.index("### Guion de combate")
    _escribir(boveda, texto[:i] + texto[texto.index("### Checklist del día"):])
    r = cliente.get("/rendimiento/competencia")
    assert "1 fila del plan no se pudo leer" in r.text and "Sin guion de combate en la sección del torneo" in r.text
    assert "BJJ no-gi" in r.text


def test_prefijos_y_citas():
    assert comp.limpiar("- [O] **Judogi:** el azul · [U 2026-10-19 | alta]") == "**Judogi:** el azul"
    assert comp.limpiar("- [M] Torneo: 2026-11-07 08:00 · Coliseo · [S29 | alta]") == "Torneo: 2026-11-07 08:00 · Coliseo"
    assert comp.limpiar("* [m][H] Judogi") == "Judogi"


def test_plan_guion_y_checklist(boveda, cliente):
    c = _c(boveda)
    assert len(c.plan) == 6 and c.plan[0].combate == "BJJ no-gi" and c.plan[0].cardio == "" and c.plan[1].notas == ""
    assert [t.titulo for t in c.guion] == ["Si me lanzan, caigo", "Antes de cada combate"]
    assert c.checklist == ("Documento de identidad", "Judogi", "Kinesiotape")
    assert "Laura" not in cliente.get("/rendimiento/competencia").text


def test_checklist_sin_linea_en_blanco(boveda, cliente):
    _escribir(boveda, tras_checklist="### Notas del torneo\n" + SUELTOS)
    assert _c(boveda).checklist == ("Documento de identidad", "Judogi", "Kinesiotape")
    assert "Laura" not in cliente.get("/rendimiento/competencia").text


def test_items_repetidos(boveda, cliente):
    _escribir(boveda, tras_checklist="- [O] Judogi\n" + SUELTOS)
    assert _c(boveda).checklist == ("Documento de identidad", "Judogi", "Kinesiotape")
    assert "0 de 3" in cliente.get("/rendimiento/competencia").text


def test_varias_secciones(boveda):
    vieja = ("## Hacia el torneo Open (2026-06-13)\n\n- [M] Torneo: 2026-06-13 09:00 · Otro lugar\n"
             "- [H] Pesaje: 2026-06-12 17:00 a 18:00\n\n")
    _escribir(boveda, antes=vieja)
    assert _c(boveda).torneo.date() == date(2026, 11, 7)
    assert _c(boveda, date(2026, 11, 8)).torneo.date() == date(2026, 11, 7)
    assert _c(boveda, date(2026, 5, 1)).nombre == "Open 2026"   # la fila de objetivos con esa fecha


def test_sin_seccion(boveda, cliente):
    _escribir(boveda, "# Planificación\n\n## Vigente\n\n- nada\n")
    assert comp.vigente(boveda, HOY) == comp.Lectura()
    r = cliente.get("/rendimiento/competencia")
    assert r.status_code == 200
    assert 'No hay una competencia en planificacion-semanal.md (sección "Hacia el torneo" con las líneas Torneo y Pesaje)' in r.text


# Decisión 1a ----------------------------------------------------------------

@pytest.mark.parametrize("linea", ["- [?] Plan en validación con el usuario", "- [?] plan en validacion",
                                   "- Plan en validación", "- [?] Plan en validación"])
def test_plan_en_validacion(boveda, cliente, linea):
    _escribir(boveda, validacion=linea + "\n")
    cliente.post("/rendimiento/competencia/pesajes", data={"fecha": "2026-10-19", "peso": "77", "condicion": "ropa_interior"})
    c = _c(boveda)
    assert c.en_validacion and c.meta_peso is None and c.dia(HOY) is None
    r = cliente.get("/rendimiento/competencia")
    assert "Plan en validación." in r.text and "BJJ no-gi" not in r.text and "metaFecha" not in r.text
    assert "Si me lanzan, caigo" in r.text and "Documento de identidad" in r.text


def test_plan_aprobado(cliente):
    r = cliente.get("/rendimiento/competencia")
    assert "BJJ no-gi" in r.text and 'class="chip-hoy"' in r.text and "Ver los 6 días" in r.text


# Cuenta regresiva -----------------------------------------------------------

def test_faltan_dias(cliente):
    r = cliente.get("/rendimiento/competencia")
    assert ">18<" in _cuenta_html(r.text, "pesaje") and ">19<" in _cuenta_html(r.text, "torneo")
    hoy = cliente.get("/rendimiento")
    assert "pesaje en 18 días, torneo en 19 días" in hoy.text and 'href="/rendimiento/competencia"' in hoy.text
    metas = cliente.get("/rendimiento/metas")
    assert '<a class="fila-hito fila-enlace" href="/rendimiento/competencia"><span>Juegos de Prueba 2026' in metas.text
    assert '<a class="fila-hito fila-enlace" href="/rendimiento/competencia"><span>Juegos de Prueba 2026' in hoy.text


@pytest.mark.parametrize("hora,texto", [((9, 0), "Hoy, a las 17:00"), ((17, 30), "En curso"), ((19, 0), "Ya pasó")])
def test_dia_del_pesaje(cliente, momento, hora, texto):
    momento(datetime(2026, 11, 6, *hora))
    assert texto in _cuenta_html(cliente.get("/rendimiento/competencia").text, "pesaje")
    assert f"pesaje {texto.lower()}" in cliente.get("/rendimiento").text


@pytest.mark.parametrize("hora,texto", [((7, 0), "Hoy, a las 08:00"), ((10, 0), "Hoy")])
def test_dia_del_torneo(cliente, momento, hora, texto):
    momento(datetime(2026, 11, 7, *hora))
    bloque = _cuenta_html(cliente.get("/rendimiento/competencia").text, "torneo")
    assert f'cuenta-texto">{texto}</p>' in bloque


def test_despues_del_torneo(cliente, momento):
    momento(datetime(2026, 11, 8, 9, 0))
    assert "fue el 7 nov 2026" in cliente.get("/rendimiento/competencia").text
    assert "Juegos de Prueba" not in cliente.get("/rendimiento").text
    assert "Juegos de Prueba" not in cliente.get("/rendimiento/metas").text


# Pesajes --------------------------------------------------------------------

def _pesar(cliente, **datos):
    return cliente.post("/rendimiento/competencia/pesajes",
                        data={"fecha": "2026-10-19", "condicion": "ropa_interior"} | datos, follow_redirects=False)


def test_registrar_y_texto_neutro(cliente, con):
    assert _pesar(cliente, peso="77,4", hora="7:10").status_code == 303
    assert [(x.fecha, x.peso_g, x.hora, x.condicion) for x in comp.pesajes(con)] == [("2026-10-19", 77400, "07:10", "ropa_interior")]
    r = cliente.get("/rendimiento/competencia")
    assert "0,6 kg por debajo del límite" in r.text and "g-pesajes-datos" in r.text


def test_cerca_del_limite(cliente):
    _pesar(cliente, peso="77,96")
    r = cliente.get("/rendimiento/competencia").text
    assert ">77,96<" in r and "0,04 kg por debajo del límite" in r and " 0 kg" not in r
    _pesar(cliente, peso="78,04")
    r = cliente.get("/rendimiento/competencia").text
    assert ">78,04<" in r and "0,04 kg por encima del límite" in r and " 0 kg" not in r


def test_reemplazar_y_sin_clases_de_estado(cliente, con):
    _pesar(cliente, peso="77,4")
    _pesar(cliente, peso="78,4")
    assert [x.peso_g for x in comp.pesajes(con)] == [78400]
    r = cliente.get("/rendimiento/competencia").text
    seccion = r[r.index('id="pesajes"'):r.index('id="t-guion"')]
    assert "0,4 kg por encima del límite" in seccion
    for clase in ("delta neg", "delta pos", "--negativo", "--positivo", 'class="aviso'):
        assert clase not in seccion


@pytest.mark.parametrize("datos,mensaje", [
    ({"peso": "7"}, "Escribe el peso en kg"), ({"peso": "abc"}, "Escribe el peso en kg"),
    ({"peso": "77", "hora": "7am"}, "Escribe la hora"), ({"peso": "77", "hora": "99:99"}, "Escribe la hora"),
    ({"peso": "77", "condicion": "desnudo"}, "Elige si fue en ropa interior o con ropa"),
    ({"peso": "77", "fecha": "2026-12-01"}, "La fecha no puede ser posterior a hoy"),
])
def test_valores_invalidos(cliente, con, datos, mensaje):
    r = _pesar(cliente, nota="tras dormir", **datos)
    assert r.status_code == 422 and mensaje in r.text and comp.pesajes(con) == []
    assert 'value="tras dormir"' in r.text and "location" not in r.headers


def test_nota_recortada(cliente, con):
    _pesar(cliente, peso="77", nota="x" * 500)
    assert len(comp.pesajes(con)[0].nota) == 200


def test_borrar(cliente, con):
    _pesar(cliente, peso="77", fecha="2026-10-17")
    _pesar(cliente, peso="77,2")
    for fecha in ("2026-10-17", "", "2026-12-01", "basura"):
        cliente.post("/rendimiento/competencia/pesajes", data={"accion": "borrar", "fecha": fecha})
    assert [x.fecha for x in comp.pesajes(con)] == ["2026-10-19"]


def test_proximo_pesaje_en_casa(boveda):
    c = _c(boveda)
    assert comp.proximo_pesaje_casa(c, date(2026, 10, 19)) == date(2026, 10, 26)
    assert comp.proximo_pesaje_casa(c, date(2026, 11, 6)) is None


def test_meta_y_ventana_de_la_grafica(cliente, boveda):
    c = _c(boveda)
    assert c.meta_peso.fecha == date(2026, 11, 5) and c.meta_peso.meta_g == 77500
    _pesar(cliente, peso="77,1", fecha="2026-08-01")   # más de 60 días antes del torneo
    _pesar(cliente, peso="77,3")
    r = cliente.get("/rendimiento/competencia").text
    datos = json.loads(r[r.index('id="g-pesajes-datos">') + 21:r.index("</script>", r.index('id="g-pesajes-datos"'))])
    assert [p["fecha"] for p in datos] == ["2026-10-19"]
    assert "Todos los pesajes (2)" in r and "meta: 77500" in r and '"2026-11-05"' in r
    assert "y la meta de 77,5 kg el 5 nov 2026" in r


# Guion y checklist ----------------------------------------------------------

def test_guion_enfocable(cliente):
    r = cliente.get("/rendimiento/competencia").text
    assert 'tabindex="0" aria-label="Guion de combate"' in r
    assert "return confirm('¿Borrar el pesaje del" not in r   # sin pesajes no hay botón
    assert r.index("Si me lanzan, caigo") < r.index("Antes de cada combate") and "<p>Tres respiraciones" in r


def test_marcar_y_desmarcar(cliente, con, boveda):
    r = cliente.post("/rendimiento/competencia/checklist", data={"item": "Judogi", "marcado": "1"},
                     headers={"HX-Request": "true"})
    assert r.status_code == 200 and "1 de 3" in r.text and 'id="chk-2"' in r.text and 'hx-swap-oob="innerHTML"' in r.text
    cliente.post("/rendimiento/competencia/checklist", data={"item": "No está en la lista", "marcado": "1"})
    assert comp.marcas(con, _c(boveda)) == {"Judogi"}
    cliente.post("/rendimiento/competencia/checklist", data={"item": "Judogi", "marcado": "0"})
    assert comp.marcas(con, _c(boveda)) == set()


@pytest.mark.parametrize("ruta", ["/rendimiento", "/rendimiento/competencia"])
def test_se_reinicia_despues_del_torneo(cliente, con, boveda, momento, ruta):
    comp.marcar(con, _c(boveda), "Judogi", True)
    momento(datetime(2026, 11, 7, 7, 0))
    cliente.get("/rendimiento/competencia")
    assert con.execute("SELECT COUNT(*) FROM checklist_competencia").fetchone()[0] == 1
    momento(datetime(2026, 11, 8, 9, 0))
    cliente.get(ruta)
    assert con.execute("SELECT COUNT(*) FROM checklist_competencia").fetchone()[0] == 0


# Vault, navegación y resumen ------------------------------------------------

def test_vault_intacto(cliente, boveda):
    antes = {str(p): p.read_bytes() for p in boveda.rglob("*") if p.is_file()}
    _pesar(cliente, peso="77,4")
    _pesar(cliente, peso="77,2", fecha="2026-10-18")
    cliente.post("/rendimiento/competencia/pesajes", data={"accion": "borrar", "fecha": "2026-10-18"})
    cliente.post("/rendimiento/competencia/checklist", data={"item": "Judogi", "marcado": "1"})
    cliente.post("/rendimiento/competencia/checklist", data={"item": "Judogi", "marcado": "0"})
    for u in ("/rendimiento", "/rendimiento/metas", "/rendimiento/competencia"):
        cliente.get(u)
    assert {str(p): p.read_bytes() for p in boveda.rglob("*") if p.is_file()} == antes


def test_mas(cliente):
    assert 'href="/rendimiento/competencia"' in cliente.get("/rendimiento/mas").text


def test_resumen(cliente, con, boveda):
    _pesar(cliente, peso="77,4", nota="tras dormir")
    d = resumen_ia.construir(con, boveda, HOY)
    assert d["pesajes"] == [{"fecha": "2026-10-19", "hora": None, "peso_g": 77400, "condicion": "ropa_interior",
                             "nota": "tras dormir"}]
    md = resumen_ia.markdown(json.loads(json.dumps(d)))
    assert "- [M] 2026-10-19: 77,4 kg, en ropa interior · " in md
    assert "- [H] 2026-10-19, nota del pesaje: tras dormir · " in md


def test_ventana_del_resumen(cliente, con, boveda):
    _pesar(cliente, peso="77", fecha="2026-07-11")   # hace 100 días
    _pesar(cliente, peso="77,2", fecha="2026-10-09")
    assert [p["fecha"] for p in resumen_ia.construir(con, boveda, HOY)["pesajes"]] == ["2026-10-09"]


def test_auditoria_borrar_pesaje_pide_confirmacion(cliente):
    _pesar(cliente, peso="77,4")
    assert "return confirm('¿Borrar el pesaje del 19 oct 2026?')" in cliente.get("/rendimiento/competencia").text


def test_auditoria_enlace_registrar_tactil(cliente):
    assert '<a class="enlace-tactil" href="/rendimiento/registrar">Registrar</a>' in cliente.get("/rendimiento").text


def test_hito_de_un_dia(cliente):
    r = cliente.get("/rendimiento").text
    assert "7 de noviembre" in r and "7 al 7 de noviembre" not in r
