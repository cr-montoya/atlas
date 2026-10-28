"""Requirement: Lectura de datos de sensores (lectores del vault, solo lectura)."""

import hashlib
import shutil
from datetime import date
from pathlib import Path

import pytest

from app.modules.rendimiento import vault as v

DATOS = Path(__file__).parent / "datos" / "vault"


@pytest.fixture
def boveda(tmp_path):
    """Copia del vault ficticio, para poder tocarla sin ensuciar tests/datos."""
    destino = tmp_path / "vault"
    shutil.copytree(DATOS, destino)
    v.limpiar_cache()
    return destino


def _por_clave(imp, fuente, fecha, hora):
    return next(a for a in imp.actividades if a.clave == f"{fuente}|{fecha}|{hora}")


def test_perfil_generico_de_polar_queda_visible_pero_fuera(boveda):
    imp = v.importar(boveda)
    a = _por_clave(imp, "polar", "2026-01-17", "02:10:00")
    assert a.deporte == "Polar Flow sport 127"
    assert a.entrenamiento is False and v.AVISO_NO_ENTRENAMIENTO in a.avisos
    polar = [x for x in imp.actividades if x.fuente == "polar"]
    assert len(polar) == 76
    assert sum(1 for x in polar if x.entrenamiento) == 75
    assert "Polar: 75 sesiones de entrenamiento (1 probablemente no es entrenamiento)." in imp.avisos


def test_generico_con_fc_y_hora_normales_si_cuenta(boveda):
    a = v._reglas(v.Actividad("polar", "2026-01-20", "18:00:00", "Polar Flow sport 3", "otro", 3600, fc_media=120))
    assert a.entrenamiento is True and v.AVISO_NO_ENTRENAMIENTO not in a.avisos


@pytest.mark.parametrize("original,fecha,hora", [("Kickboxing", "2026-01-13", "19:40:00"),
                                                  ("Kickbiking", "2026-01-15", "19:35:00")])
def test_kickboxing_y_kickbiking_son_muay_thai(boveda, original, fecha, hora):
    a = _por_clave(v.importar(boveda), "polar", fecha, hora)
    assert a.disciplina == "muaythai" and a.nombre == "Muay Thai"
    assert f"etiqueta original: {original}" in a.avisos


def test_judo_de_polar_es_judo_o_bjj_con_sugerencia(boveda):
    imp = v.importar(boveda)
    con_nota = _por_clave(imp, "polar", "2026-01-12", "18:10:00")  # lunes con nota "Bjj"
    martes = _por_clave(imp, "polar", "2026-01-06", "18:05:00")
    assert con_nota.disciplina == "judo_bjj" and con_nota.nombre == "Judo o BJJ, sin confirmar"
    assert con_nota.sugerencia == "bjj"  # manda la nota aunque sea lunes
    assert martes.sugerencia == "bjj"     # martes sin nota
    sabado = v._reglas(v.Actividad("polar", "2026-01-17", "12:00:00", "Judo", "judo_bjj", 3600, fc_media=140))
    assert sabado.sugerencia == "judo"


def test_senal_dudosa_en_combate(boveda):
    a = _por_clave(v.importar(boveda), "polar", "2026-01-06", "18:05:00")
    assert a.fc_media == 92 and a.fc_dudosa is True
    assert "FC dudosa (posible pérdida de señal)" in a.avisos
    caminata = v._reglas(v.Actividad("garmin", "2026-02-05", "08:00:00", "Caminata", "caminata", 750, fc_media=98))
    assert caminata.fc_dudosa is False


def test_decimales_con_coma_de_garmin(boveda):
    imp = v.importar(boveda)
    fuerza = _por_clave(imp, "garmin", "2026-02-03", "12:17:00")
    caminadora = _por_clave(imp, "garmin", "2026-02-03", "13:19:00")
    assert fuerza.duracion_s == 2478  # 41,3 min
    assert caminadora.distancia_m == 2910  # 2,91 km
    assert fuerza.distancia_m is None  # "-"
    assert _por_clave(imp, "garmin", "2026-02-05", "08:00:00").distancia_m == 850


def test_duplicado_entre_dispositivos_cuenta_una_vez_con_fc_de_polar(boveda):
    imp = v.importar(boveda)
    del_dia = [a for a in imp.actividades if a.fecha == "2026-02-02"]
    assert len(del_dia) == 1
    unica = del_dia[0]
    assert unica.fuente == "polar" and unica.fc_media == 112 and unica.tambien_en == "garmin"
    assert any("cuentan una vez con la FC del H10" in x for x in imp.avisos)


def test_solape_menor_no_es_duplicado():
    a = v.Actividad("garmin", "2026-02-02", "07:00:00", "Caminata", "caminata", 1800)
    b = v.Actividad("polar", "2026-02-02", "07:20:00", "Walking", "caminata", 1800)
    assert len(v.deduplicar([a, b])) == 2


def _huellas(raiz: Path) -> dict[str, tuple[int, str]]:
    return {str(p): (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(raiz.rglob("*")) if p.is_file()}


def test_archivos_del_vault_intactos(boveda):
    antes = _huellas(boveda)
    v.importar(boveda)
    v.zonas(boveda), v.tests(boveda), v.hitos(boveda), v.meta_pasos(boveda)
    assert _huellas(boveda) == antes


def test_cache_relee_un_archivo_que_cambia(boveda):
    assert len(v.importar(boveda).salud) == 3
    csv = next((boveda / v.GARMIN).glob("*salud*.csv"))
    csv.write_text(csv.read_text() + "2026-02-05,7000,55,30,80,7.0,60,300,80,20,75,68,BALANCED,10,0\n")
    assert len(v.importar(boveda).salud) == 4


def test_salud_diaria_sin_sueno_es_none_no_cero(boveda):
    salud = v.importar(boveda).salud
    assert salud["2026-02-02"].sueno_s == 7 * 3600 + 15 * 60
    assert salud["2026-02-04"].sueno_s is None and salud["2026-02-04"].hrv_ms is None
    assert salud["2026-02-04"].pasos == 9000


def test_ultima_fecha_por_fuente(boveda):
    ult = v.importar(boveda).ultima_fecha
    assert ult["garmin"] == "2026-02-05"
    assert ult["polar"] > "2026-05-01"


def test_zonas_de_polar(boveda):
    tabla = v.zonas(boveda)
    assert tabla[0] == (1, 97, 117) and tabla[-1] == (5, 175, 195)
    assert [v.zona_de(fc, tabla) for fc in (90, 97, 130, 156, 199)] == [0, 1, 2, 4, 5]


def test_tests_del_vault_con_fecha_aproximada_y_metodos(boveda):
    ts = v.tests(boveda)
    cmj = [t for t in ts if t.tipo == "cmj"]
    assert [(t.fecha, t.fecha_precision, t.fecha_aproximada, t.valores[0].valor_mil) for t in cmj] == [
        ("2025-01-01", "mes", True, 45100), ("2025-03-01", "mes", False, 51950)]
    antro = {t.fecha: t for t in ts if t.tipo == "antropometria"}
    assert set(antro) == {"2025-08-20", "2026-08-18"}  # el peso de referencia "85-86 kg" no es un test
    x = {val.medida: val for val in antro["2026-08-18"].valores}
    assert antro["2026-08-18"].metodo == "Antropometría, Yuhasz (Centro Uno)"
    assert antro["2025-08-20"].metodo == "Documento nutricional D04"
    assert (x["Peso"].valor_mil, x["% graso"].valor_mil, x["Suma 6 pliegues"].valor_mil) == (83250, 14300, 92000)
    assert x["Masa muscular"].valor_mil == 35859
    assert x["Perímetro cintura"].direccion == "neutra" and x["Pliegue tríceps"].valor_mil == 12000


def test_hitos_y_meta_de_pasos(boveda):
    viaje, cirugia = v.hitos(boveda)
    assert (viaje.inicio, viaje.fin) == (date(2026, 12, 6), date(2026, 12, 16))
    assert (cirugia.inicio, cirugia.fin, cirugia.aproximado) == (date(2027, 1, 1), date(2027, 3, 31), True)
    assert cirugia.texto == "primer trimestre de 2027"
    assert v.meta_pasos(boveda) == 8000


def test_vault_ausente_avisa(tmp_path):
    imp = v.importar(tmp_path / "no-existe")
    assert imp.actividades == [] and "No encontré el vault" in imp.avisos[0]
