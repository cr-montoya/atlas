"""Rutas de tests del gimnasio: evolución, curva carga-velocidad, dinamometría, radar, comparación y registro."""

import re
import sqlite3
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from . import consultas as q
from . import evaluaciones as ev
from . import logica, rutas
from .consultas import ErrorDatos
from .logica import ValorInvalido
from .rutas import Con, render

router = APIRouter(prefix="/rendimiento")

# Campos del formulario por tipo de test: (medida, unidad, dirección)
FORMULARIOS = {
    "cmj": [("CMJ", "cm", "mas")],
    "dinamometria": [("Mano dominante", "kg", "mas"), ("Mano no dominante", "kg", "mas")],
    "carga_velocidad": [(f"VMP {k} kg", "m/s", "mas") for k in (15, 25, 35, 45, 55, 65)],
    "caminata_6min": [("Distancia", "km", "mas")],
    "antropometria": [("Peso", "kg", "neutra"), ("% graso", "%", "menos"), ("Masa muscular", "kg", "mas"),
                      ("Suma 6 pliegues", "mm", "menos"), ("Perímetro cintura", "cm", "neutra"),
                      ("Perímetro cadera", "cm", "neutra")],
    "rm": [("Carga", "kg", "mas")],
    "sprint": [("Tiempo", "s", "menos")],
    "movilidad": [],
    "otro": [],
}


def _clave(m: ev.Medicion) -> str:
    return f"{m.tipo}|{m.fecha}|{m.origen}|{m.test_id or ''}"


def _ctx(request: Request, con: sqlite3.Connection, **extra) -> dict:
    meds = ev.todas(con, rutas._boveda(request))
    cmj = ev.serie(meds, "cmj", "CMJ")
    dina = ev.serie(meds, "dinamometria", "Mano dominante")
    seis = ev.serie(meds, "caminata_6min", "Distancia")
    pesos = ev.serie(meds, "antropometria", "Peso", _metodo_reciente(meds))
    cintura = ev.serie(meds, "antropometria", "Perímetro cintura", _metodo_reciente(meds, "Perímetro cintura"))

    def puntos(serie):
        return [{"fecha": m.fecha, "precision": m.precision, "aprox": m.aproximada, "v": v.valor_mil} for m, v in serie]

    def resumen(serie):
        if not serie:
            return None
        ultimo = serie[-1]
        anterior = serie[-2] if len(serie) > 1 else None
        top = ev.mejor(serie)
        d = logica.delta(anterior[1].valor_mil, ultimo[1].valor_mil, ultimo[1].direccion) if anterior else None
        frente_mejor = (logica.delta(top[1].valor_mil, ultimo[1].valor_mil, ultimo[1].direccion)
                        if top and top[0] is not ultimo[0] else None)
        return {"ultimo": ultimo, "anterior": anterior, "mejor": top, "delta": d, "frente_mejor": frente_mejor,
                "n": len(serie)}

    por_tipo: dict[str, list[ev.Medicion]] = {}
    for m in meds:
        if m.valores:
            por_tipo.setdefault(m.tipo, []).append(m)
    tipo_comp = "cmj" if "cmj" in por_tipo else next(iter(por_tipo), None)
    lista = por_tipo.get(tipo_comp, []) if tipo_comp else []
    ma, mb = (lista[-2], lista[-1]) if len(lista) > 1 else (None, None)
    return {
        "tipo_comp": tipo_comp, "lista_comp": lista, "ma": ma, "mb": mb, "comp": ev.comparar(ma, mb) if ma else None,
        "seccion": "tests", "meds": meds, "cmj": resumen(cmj), "dina": resumen(dina), "seis": resumen(seis),
        "peso": resumen(pesos), "cintura": resumen(cintura),
        "graficas": {"cmj": puntos(cmj), "dina": puntos(dina), "seis": puntos(seis), "peso": puntos(pesos),
                     "cintura": puntos(cintura), "curvas": ev.curvas_carga_velocidad(meds)},
        "radar": ev.radar(meds), "por_tipo": por_tipo, "clave": _clave, "NOMBRES_TIPO": ev.NOMBRES_TIPO,
        **extra,
    }


def _metodo_reciente(meds: list[ev.Medicion], medida: str = "Peso") -> str | None:
    """El método con más mediciones de esa medida (si empatan, el más reciente). Las series no se mezclan."""
    conteo: dict[str | None, tuple[int, str]] = {}
    for m in meds:
        if m.tipo == "antropometria" and medida in m.valores:
            n, _ = conteo.get(m.metodo, (0, ""))
            conteo[m.metodo] = (n + 1, m.fecha)
    return max(conteo, key=lambda k: conteo[k]) if conteo else None


@router.get("/tests")
def tests(request: Request, con: sqlite3.Connection = Con):
    return render(request, "rendimiento/tests.html", _ctx(request, con))


@router.get("/tests/comparar")
def tests_comparar(request: Request, tipo: str = "cmj", a: str = "", b: str = "", con: sqlite3.Connection = Con):
    ctx = _ctx(request, con)
    lista = ctx["por_tipo"].get(tipo, [])
    elegida = {_clave(m): m for m in lista}
    ma = elegida.get(a) or (lista[-2] if len(lista) > 1 else None)
    mb = elegida.get(b) or (lista[-1] if lista else None)
    comp = ev.comparar(ma, mb) if ma and mb and ma is not mb else None
    plantilla = "rendimiento/_comparar_tests.html" if request.headers.get("HX-Request") else "rendimiento/tests.html"
    return render(request, plantilla, {**ctx, "comp": comp, "tipo_comp": tipo, "lista_comp": lista, "ma": ma, "mb": mb})


@router.get("/tests/nuevo")
def test_nuevo(request: Request, tipo: str = "cmj"):
    if tipo not in FORMULARIOS:
        tipo = "cmj"
    return render(request, "rendimiento/test_nuevo.html", {
        "seccion": "tests", "tipo": tipo, "campos": FORMULARIOS[tipo], "NOMBRES_TIPO": ev.NOMBRES_TIPO,
        "hoy": rutas.hoy().isoformat(), "valores": {}, "error": None})


@router.post("/tests")
async def test_guardar(request: Request, con: sqlite3.Connection = Con):
    form = await request.form()
    v = {k: str(x) for k, x in form.items()}
    tipo = v.get("tipo", "")
    ctx = {"seccion": "tests", "tipo": tipo, "campos": FORMULARIOS.get(tipo, []), "NOMBRES_TIPO": ev.NOMBRES_TIPO,
           "hoy": rutas.hoy().isoformat(), "valores": v}
    try:
        if tipo not in FORMULARIOS:
            raise ErrorDatos("Elige el tipo de test.")
        fecha, precision = _fecha(v.get("fecha", ""))
        valores = []
        for i, (medida, unidad, direccion) in enumerate(FORMULARIOS[tipo]):
            texto = v.get(f"v{i}", "").strip()
            if texto:
                valores.append((medida, logica.parse_decimal_mil(texto), unidad, direccion))
        if tipo in ("otro", "rm") and v.get("medida_libre", "").strip() and v.get("valor_libre", "").strip():
            valores.append((v["medida_libre"].strip(), logica.parse_decimal_mil(v["valor_libre"]),
                            v.get("unidad_libre", "").strip(), v.get("direccion_libre", "mas")))
        q.crear_test(con, tipo=tipo, fecha=fecha, precision=precision, aproximada=v.get("aproximada") == "1",
                     metodo=v.get("metodo"), evaluador=v.get("evaluador"), protocolo=v.get("protocolo"),
                     notas=v.get("notas"), valores=valores)
    except (ErrorDatos, ValorInvalido) as err:
        return render(request, "rendimiento/test_nuevo.html", {**ctx, "error": str(err)}, 422)
    rutas.actualizar_resumen(request, con)
    return RedirectResponse(f"/rendimiento/tests?tipo={tipo}#t-{tipo}", status_code=303)


@router.post("/tests/{test_id}/borrar")
def test_borrar(request: Request, test_id: int, con: sqlite3.Connection = Con):
    q.borrar_test(con, test_id)
    rutas.actualizar_resumen(request, con)
    return RedirectResponse("/rendimiento/tests", status_code=303)


def _fecha(texto: str) -> tuple[str, str]:
    t = texto.strip()
    if re.fullmatch(r"\d{4}-\d{2}", t):
        return f"{t}-01", "mes"
    try:
        return date.fromisoformat(t).isoformat(), "dia"
    except ValueError:
        raise ErrorDatos("La fecha va como 2026-10-20 (o 2026-10 si solo sabes el mes).") from None
