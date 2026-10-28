"""Requirements: Comidas al inbox del vault, plan vigente y metas (fase 4)."""

import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Config
from app.main import crear_app
from app.modules.rendimiento import nutricion as nu
from app.modules.rendimiento import rutas, vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"
HOY = date(2026, 10, 17)


@pytest.fixture
def boveda(tmp_path):
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    vault.limpiar_cache()
    return destino


@pytest.fixture
def config(tmp_path, boveda):
    return Config(pin=PIN, secreto="secreto-de-prueba", db_path=tmp_path / "prueba.db",
                  exports_path=tmp_path / "exports", vault_path=boveda, fotos_path=tmp_path / "fotos")


@pytest.fixture(autouse=True)
def hoy_fijo(monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: HOY)


@pytest.fixture
def escribiendo(config, datos):
    """La app con BRAIN_ESCRIBIR_COMIDAS=1."""
    app = crear_app(replace(config, escribir_comidas=True))
    with TestClient(app) as c:
        assert c.post("/login", data={"pin": PIN}, follow_redirects=False).status_code == 303
        yield c


def _vault_snapshot(boveda: Path) -> dict[str, bytes]:
    return {str(p.relative_to(boveda)): p.read_bytes() for p in boveda.rglob("*") if p.is_file()}


# Plan vigente --------------------------------------------------------------

def test_plan_vigente_por_momento(boveda):
    plan = nu.plan_vigente(boveda)
    assert plan.archivo == "plan-nutricional-2026-08.md"  # el de 2025 es historical
    assert plan.profesional == "Nutricionista de Prueba" and plan.control == "1.ª semana de nov 2026"
    assert plan.liquidos_ml == 3000 and plan.pasos == 8000
    m = {x.clave: x for x in plan.momentos}
    assert m["almuerzo"].intercambios == (("carbohidrato", 2), ("carne", 1), ("grasa", 2), ("verdura", 1))
    assert m["media_manana"].intercambios == (("fruta", 2),) and "unirse al desayuno" in m["media_manana"].nota
    assert m["media_tarde"].intercambios == (("fruta", 1), ("proteína", 1)) and m["media_tarde"].nota == "más proteína en polvo"
    assert m["cena"].nota == "alternativa de 5 porciones de proteína"
    assert m["desayuno"].ejemplo.startswith("3 huevos revueltos")


def test_sin_plan_se_puede_registrar(cliente, con, boveda):
    for p in (boveda / "04_Nutrition").glob("plan-*.md"):
        p.unlink()
    vault.limpiar_cache()
    r = cliente.get("/rendimiento/comidas")
    assert r.status_code == 200 and "No encontré un plan nutricional vigente" in r.text
    cliente.post("/rendimiento/comidas/2026-10-17/almuerzo", data={"texto": "arroz con pollo"})
    assert nu.dia(con, "2026-10-17").comidas["almuerzo"].texto == "arroz con pollo"


# Registro rápido -----------------------------------------------------------

def test_lo_del_plan_en_un_toque(cliente, con):
    r = cliente.post("/rendimiento/comidas/2026-10-17/almuerzo", data={"accion": "plan", "hora": "13:10"},
                     headers={"HX-Request": "true"})
    assert r.status_code == 200 and "Según el plan" in r.text and 'id="c-almuerzo"' in r.text
    c = nu.dia(con, "2026-10-17").comidas["almuerzo"]
    assert c.segun_plan and c.hora == "13:10"
    assert c.intercambios == {"carbohidrato": 2, "carne": 1, "grasa": 2, "verdura": 1}


def test_con_sus_palabras_e_intercambios(cliente, con):
    cliente.post("/rendimiento/comidas/2026-10-17/cena",
                 data={"texto": "arepa | con atún", "i_carbohidrato": "2", "i_carne": "1", "i_grasa": ""})
    c = nu.dia(con, "2026-10-17").comidas["cena"]
    assert c.texto == "arepa | con atún" and c.intercambios == {"carbohidrato": 2, "carne": 1} and not c.segun_plan


@pytest.mark.parametrize("datos_form, mensaje", [
    ({}, "Escribe qué comiste o marca los intercambios"),
    ({"texto": "x", "hora": "25:00"}, "La hora va como 13:30"),
    ({"i_fruta": "40"}, "Los intercambios van de 0 a 12"),
])
def test_errores_legibles(cliente, datos_form, mensaje):
    r = cliente.post("/rendimiento/comidas/2026-10-17/desayuno", data=datos_form, headers={"HX-Request": "true"})
    assert r.status_code == 422 and mensaje in r.text


def test_quitar_registro_y_no_futuro(cliente, con):
    cliente.post("/rendimiento/comidas/2026-10-17/extra", data={"texto": "helado"})
    cliente.post("/rendimiento/comidas/2026-10-17/extra", data={"accion": "borrar"})
    assert "extra" not in nu.dia(con, "2026-10-17").comidas
    cliente.post("/rendimiento/comidas/2026-12-01/almuerzo", data={"texto": "futuro"})
    assert nu.dia(con, "2026-10-17").comidas["almuerzo"].texto == "futuro"  # una fecha futura cae en hoy


def test_agua_en_vasos(cliente, con):
    for _ in range(3):
        r = cliente.post("/rendimiento/comidas/2026-10-17", data={"agua": "1"}, headers={"HX-Request": "true"})
    assert "0,6 de 3 L" in r.text
    cliente.post("/rendimiento/comidas/2026-10-17", data={"agua": "-1"})
    assert nu.dia(con, "2026-10-17").agua_vasos == 2


def test_pantalla_del_dia_y_semana(cliente, con):
    cliente.post("/rendimiento/comidas/2026-10-13/almuerzo", data={"accion": "plan"})
    cliente.post("/rendimiento/comidas/2026-10-17/cena", data={"texto": "arepa", "i_carbohidrato": "1", "i_carne": "2"})
    r = cliente.get("/rendimiento/comidas")
    assert r.status_code == 200
    assert "Plan: 2 carbohidrato, 1 carne, 2 grasa, 1 verdura" in r.text
    assert "2 de 30 comidas registradas hasta hoy, en 2 días" in r.text  # lunes 12 a sábado 17
    assert "Almuerzo del 13 oct 2026: lo del plan" in r.text and "Cena del 17 oct 2026: registrada" in r.text
    assert "Queda solo en la app" in r.text and "—" not in r.text
    assert "3/2" in r.text  # carne: 1 del plan + 2 marcadas frente a 1 + 1 del plan


def test_navegacion(cliente):
    assert 'href="/rendimiento/comidas"' in cliente.get("/rendimiento/registrar").text
    portada = cliente.get("/rendimiento/analisis").text
    assert 'href="/rendimiento/metas"' in portada and 'href="/rendimiento/comidas#semana"' in portada
    assert "Nutrición y metas" not in cliente.get("/rendimiento/mas").text


# Comidas al inbox del vault (BRAIN_ESCRIBIR_COMIDAS) ----------------------

def test_apagado_no_escribe_en_el_vault(cliente, boveda):
    antes = _vault_snapshot(boveda)
    cliente.post("/rendimiento/comidas/2026-10-17/almuerzo", data={"accion": "plan"})
    assert _vault_snapshot(boveda) == antes


def test_dia_nuevo_en_el_inbox(escribiendo, boveda):
    antes = _vault_snapshot(boveda)
    escribiendo.post("/rendimiento/comidas/2026-10-17/almuerzo", data={"texto": "arroz, pollo", "hora": "13:10",
                                                                        "i_carbohidrato": "2"})
    ruta = boveda / "00_Inbox/comidas/2026-W42/2026-10-17.md"
    texto = ruta.read_text()
    assert "| 13:10 | Almuerzo | arroz, pollo; intercambios: 2 carbohidrato |" in texto
    for vacia in ("| | Desayuno | |", "| | Media mañana | |", "| | Media tarde | |", "| | Cena | |", "| | Extra | |"):
        assert vacia in texto
    assert texto.startswith("# Comidas 2026-10-17") and nu.MARCA in texto
    # La única escritura: ese archivo, sin tocar nada más
    despues = _vault_snapshot(boveda)
    assert set(despues) - set(antes) == {"00_Inbox/comidas/2026-W42/2026-10-17.md"}
    assert all(despues[k] == v for k, v in antes.items())


def test_reescribe_su_archivo_y_respeta_el_escrito_a_mano(escribiendo, boveda, con):
    escribiendo.post("/rendimiento/comidas/2026-10-17/almuerzo", data={"accion": "plan"})
    escribiendo.post("/rendimiento/comidas/2026-10-17/cena", data={"texto": "arepa con atún | queso"})
    escribiendo.post("/rendimiento/comidas/2026-10-17", data={"agua": "1"})
    texto = (boveda / "00_Inbox/comidas/2026-W42/2026-10-17.md").read_text()
    assert "según el plan" in texto and "arepa con atún / queso" in texto and "1 vasos de agua" in texto
    a_mano = boveda / "00_Inbox/comidas/2026-W42/2026-10-16.md"
    a_mano.write_text("# Comidas 2026-10-16\n\nescrito a mano\n")
    r = escribiendo.post("/rendimiento/comidas/2026-10-16/desayuno", data={"texto": "huevos"}, follow_redirects=True)
    assert a_mano.read_text() == "# Comidas 2026-10-16\n\nescrito a mano\n"
    assert nu.dia(con, "2026-10-16").vault_estado == "manual"
    assert "ya lo escribiste a mano: la app no lo sobrescribe" in r.text


def test_resumen_para_ia_con_comidas(cliente, config):
    cliente.post("/rendimiento/comidas/2026-10-17/almuerzo", data={"accion": "plan", "texto": "arroz"})
    js = json.loads((config.exports_path / "rendimiento-ia.json").read_text())
    assert js["comidas"][0]["momento"] == "almuerzo" and js["comidas"][0]["segun_plan"]
    md = (config.exports_path / "rendimiento-ia.md").read_text()
    assert "- [H] 2026-10-17 Almuerzo: arroz; según el plan; intercambios: 2 carbohidrato" in md


# Metas ---------------------------------------------------------------------

def test_metas(cliente, con):
    cliente.post("/rendimiento/comidas/2026-10-17", data={"agua": "1"})
    r = cliente.get("/rendimiento/metas")
    assert r.status_code == 200
    for texto in ("Pasos", "Líquidos hoy", "Muay Thai o BJJ", "Comidas registradas", "Cuenta regresiva", "Viaje a la costa",
                  "Sin pasos en los últimos 7 días", "Sin meta numérica"):
        assert texto in r.text
    assert "50" in r.text  # faltan 50 días para la costa (2026-12-06)
    assert 'aria-label="Líquidos registrados hoy, meta 3 L: 0,2 L"' in r.text
    assert "—" not in r.text


def test_metas_de_pasos_con_datos(cliente, monkeypatch):
    monkeypatch.setattr(rutas, "hoy", lambda: date(2026, 2, 10))  # el CSV de salud de prueba es de febrero
    r = cliente.get("/rendimiento/metas")
    assert "Garmin incluye los del entrenamiento" in r.text and "Pasos promedio de los últimos 7 días, meta 8000" in r.text
