"""Sensaciones y molestia del hombro en sesiones del reloj; confirmación de "Judo o BJJ" y reclasificación."""

import shutil
from pathlib import Path

import pytest

from app.core.config import Config
from app.modules.rendimiento import actividades as act
from app.modules.rendimiento import vault
from tests.conftest import PIN

DATOS = Path(__file__).parent / "datos" / "vault"


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


CAMINATA = "polar|2026-02-02|07:00:00"
JUDO_LUNES = "polar|2026-01-12|18:10:00"
GENERICO = "polar|2026-01-17|02:10:00"


def test_lista_de_actividades_del_reloj(cliente):
    r = cliente.get("/rendimiento/actividades")
    assert r.status_code == 200
    assert "Actividades del reloj" in r.text and "sin confirmar si fue judo o BJJ" in r.text
    assert "Judo o BJJ, sin confirmar" not in r.text  # solo existen judo y BJJ
    todas = cliente.get("/rendimiento/actividades?todas=1").text
    assert "probablemente no es entrenamiento" in todas


def test_sensaciones_y_molestia_en_caminata(cliente, con, boveda):
    r = cliente.post("/rendimiento/actividad", data={"clave": CAMINATA, "sensaciones": "4", "molestia": "2", "notas": "suave"},
                     follow_redirects=False)
    assert r.status_code == 303
    nota = con.execute("SELECT * FROM anotaciones_importadas WHERE clave = ?", (CAMINATA,)).fetchone()
    assert (nota["sensaciones"], nota["molestia_hombro"], nota["notas"]) == (4, 2, "suave")
    assert "Guardado." in cliente.get(r.headers["location"]).text


def test_confirmar_judo_o_bjj_sobrevive_reimportacion(cliente, con, boveda):
    pagina = cliente.get("/rendimiento/actividad", params={"clave": JUDO_LUNES}).text
    assert "¿Fue judo o BJJ?" in pagina and "la nota de Polar dice BJJ" in pagina
    cliente.post("/rendimiento/actividad", data={"clave": JUDO_LUNES, "disciplina": "bjj"})
    csv = next((boveda / vault.POLAR).glob("*.csv"))
    csv.write_text(csv.read_text() + "2026-07-01,18:00:00,Walking,1800,2000,110,130,150,,\n")  # nueva importación
    vault.limpiar_cache()
    a = act.por_clave(con, boveda, JUDO_LUNES)
    assert a.disciplina == "bjj" and vault.AVISO_JUDO_BJJ not in a.avisos


def test_reclasificar_lo_que_no_parecia_entrenamiento(cliente, con, boveda):
    assert act.por_clave(con, boveda, GENERICO).entrenamiento is False
    pagina = cliente.get("/rendimiento/actividad", params={"clave": GENERICO}).text
    assert "¿Fue entrenamiento?" in pagina
    cliente.post("/rendimiento/actividad", data={"clave": GENERICO, "es_entrenamiento": "1", "disciplina": "cardio"})
    a = act.por_clave(con, boveda, GENERICO)
    assert a.entrenamiento is True and a.disciplina == "cardio"


def test_valores_fuera_de_rango(cliente):
    r = cliente.post("/rendimiento/actividad", data={"clave": CAMINATA, "sensaciones": "9"})
    assert r.status_code == 422 and "Las sensaciones van de 1 a 5." in r.text


def test_molestia_en_cada_tipo_de_sesion(cliente, con):
    """Fuerza y combate guardan la molestia en la sesión; el reloj, en la anotación."""
    for tipo in ("fuerza", "combate"):
        r = cliente.post("/rendimiento/sesiones", data={"tipo": tipo}, follow_redirects=False)
        sid = int(r.headers["location"].rsplit("/", 1)[1])
        assert "Molestia del hombro (opcional)" in cliente.get(f"/rendimiento/sesiones/{sid}").text
        cliente.post(f"/rendimiento/sesiones/{sid}/guardar", data={"molestia": "5"})
        assert con.execute("SELECT molestia_hombro FROM sesiones WHERE id = ?", (sid,)).fetchone()[0] == 5
    assert "Molestia del hombro (opcional)" in cliente.get("/rendimiento/actividad", params={"clave": CAMINATA}).text


def test_sin_confirmar_se_cuenta_como_la_sugerida(con, boveda):
    lunes = act.por_clave(con, boveda, JUDO_LUNES)        # lunes con nota "Bjj"
    martes = act.por_clave(con, boveda, "polar|2026-01-06|18:05:00")
    assert (lunes.disciplina, lunes.confirmada) == ("bjj", False)
    assert (martes.disciplina, martes.confirmada) == ("bjj", False)
    assert all(a.disciplina != "judo_bjj" for a in act.todas(con, boveda))


def test_confirmar_por_semana(cliente, con, boveda):
    pendientes = act.sin_confirmar(con, boveda)
    pagina = cliente.get("/rendimiento/confirmar").text
    assert "¿Judo o BJJ?" in pagina and f"Confirmar {len(pendientes)} sesiones" in pagina
    datos = {f"d:{JUDO_LUNES}": "judo", "d:polar|2026-01-06|18:05:00": "bjj"}
    r = cliente.post("/rendimiento/confirmar", data=datos, follow_redirects=False)
    assert r.headers["location"].endswith("ok=2")
    assert act.por_clave(con, boveda, JUDO_LUNES).disciplina == "judo" and act.por_clave(con, boveda, JUDO_LUNES).confirmada
    assert len(act.sin_confirmar(con, boveda)) == len(pendientes) - 2
    assert "Confirmadas 2 sesiones." in cliente.get(r.headers["location"]).text
