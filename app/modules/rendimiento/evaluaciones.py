"""Tests del gimnasio: une los del vault y los de la app, arma series, compara fechas y calcula el radar."""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import logica, vault

NOMBRES_TIPO = {
    "cmj": "CMJ", "antropometria": "Antropometría", "dinamometria": "Dinamometría manual",
    "carga_velocidad": "Curva carga-velocidad", "caminata_6min": "Test de 6 min en banda",
    "rm": "1RM o estimado", "sprint": "Sprint", "movilidad": "Movilidad", "otro": "Otro",
}

# Dimensiones del radar: (tipo, medida, nombre corto)
RADAR = (("cmj", "CMJ", "CMJ"), ("dinamometria", "Mano dominante", "Dina."), ("caminata_6min", "Distancia", "6 min"),
         ("carga_velocidad", "VMP 45 kg", "VMP 45"), ("sprint", "Tiempo", "Sprint"), ("rm", "Carga", "1RM"))


@dataclass(frozen=True)
class Valor:
    medida: str
    valor_mil: int
    unidad: str
    direccion: str


@dataclass
class Medicion:
    tipo: str
    fecha: str
    precision: str = "dia"
    aproximada: bool = False
    metodo: str | None = None
    evaluador: str | None = None
    protocolo: str | None = None
    notas: str | None = None
    origen: str = "app"
    test_id: int | None = None
    valores: dict[str, Valor] = field(default_factory=dict)

    @property
    def mes(self) -> str:
        return self.fecha[:7]

    @property
    def nombre(self) -> str:
        return NOMBRES_TIPO.get(self.tipo, self.tipo)


def _de_bd(con: sqlite3.Connection) -> list[Medicion]:
    salida = {}
    for t in con.execute("SELECT * FROM tests ORDER BY fecha, id"):
        salida[t["id"]] = Medicion(t["tipo"], t["fecha"], t["fecha_precision"], bool(t["fecha_aproximada"]), t["metodo"],
                                   t["evaluador"], t["protocolo"], t["notas"], t["origen"] or "app", t["id"])
    for v in con.execute("SELECT * FROM test_valores ORDER BY id"):
        if v["test_id"] in salida:
            salida[v["test_id"]].valores[v["medida"]] = Valor(v["medida"], v["valor_mil"], v["unidad"], v["direccion"])
    return list(salida.values())


def _de_vault(boveda: Path) -> list[Medicion]:
    return [Medicion(t.tipo, t.fecha, t.fecha_precision, t.fecha_aproximada, t.metodo, t.evaluador, None, None,
                     "vault", None, {x.medida: Valor(x.medida, x.valor_mil, x.unidad, x.direccion) for x in t.valores})
            for t in vault.tests(boveda)]


def todas(con: sqlite3.Connection, boveda: Path) -> list[Medicion]:
    """Tests de la app y del vault. Un test del vault se oculta si la app ya tiene ese tipo y método
    en la misma fecha (o en el mismo mes, si el vault solo da el mes): la carga detallada manda."""
    propias = _de_bd(con)
    salida = list(propias)
    for m in _de_vault(boveda):
        repetido = any(p.tipo == m.tipo and (p.metodo or None) == (m.metodo or None)
                       and (p.fecha == m.fecha or (m.precision == "mes" and p.mes == m.mes)) for p in propias)
        if not repetido:
            salida.append(m)
    return sorted(salida, key=lambda m: (m.fecha, m.tipo, m.origen))


def serie(mediciones: list[Medicion], tipo: str, medida: str, metodo: str | None = None) -> list[tuple[Medicion, Valor]]:
    """Valores de una medida en el tiempo. En antropometría solo se junta el mismo método."""
    puntos = []
    for m in mediciones:
        if m.tipo != tipo or medida not in m.valores:
            continue
        if tipo == "antropometria" and (m.metodo or None) != (metodo or None):
            continue
        puntos.append((m, m.valores[medida]))
    return puntos


def mejor(puntos: list[tuple[Medicion, Valor]]) -> tuple[Medicion, Valor] | None:
    if not puntos:
        return None
    direccion = puntos[0][1].direccion
    if direccion == "neutra":
        return None
    clave = (lambda p: p[1].valor_mil) if direccion == "mas" else (lambda p: -p[1].valor_mil)
    return max(puntos, key=clave)


@dataclass
class FilaComparacion:
    medida: str
    unidad: str
    a: int | None
    b: int | None
    delta: logica.Delta | None


@dataclass
class Comparacion:
    a: Medicion
    b: Medicion
    metodo_distinto: bool
    filas: list[FilaComparacion]


def comparar(a: Medicion, b: Medicion) -> Comparacion:
    """Deltas de cada medida de B frente a A. Si el método es distinto, no se calculan deltas."""
    distinto = a.tipo == "antropometria" and (a.metodo or None) != (b.metodo or None)
    filas = []
    for medida in list(dict.fromkeys([*a.valores, *b.valores])):
        va, vb = a.valores.get(medida), b.valores.get(medida)
        base = va or vb
        d = None if distinto or va is None or vb is None else logica.delta(va.valor_mil, vb.valor_mil, base.direccion)
        filas.append(FilaComparacion(medida, base.unidad, va.valor_mil if va else None, vb.valor_mil if vb else None, d))
    return Comparacion(a, b, distinto, filas)


@dataclass
class DimensionRadar:
    nombre: str
    medida: str
    unidad: str
    anterior: tuple[str, int] | None   # (fecha, valor_mil)
    ultima: tuple[str, int]
    mejor_mil: int
    pct_anterior: int | None           # 0 a 100, 100 = mejor marca propia
    pct_ultima: int


def _pct(valor: int, mejor_valor: int, direccion: str) -> int:
    if valor <= 0 or mejor_valor <= 0:
        return 0
    return round(100 * (valor / mejor_valor if direccion == "mas" else mejor_valor / valor))


def radar(mediciones: list[Medicion]) -> list[DimensionRadar]:
    """Una dimensión por test con al menos dos fechas: la anterior y la última, contra la mejor marca propia."""
    dims = []
    for tipo, medida, corto in RADAR:
        puntos = serie(mediciones, tipo, medida)
        if len(puntos) < 2:
            continue
        top = mejor(puntos)
        if top is None:
            continue
        (ma, va), (mb, vb) = puntos[-2], puntos[-1]
        dims.append(DimensionRadar(corto, medida, vb.unidad, (ma.fecha, va.valor_mil), (mb.fecha, vb.valor_mil),
                                   top[1].valor_mil, _pct(va.valor_mil, top[1].valor_mil, vb.direccion),
                                   _pct(vb.valor_mil, top[1].valor_mil, vb.direccion)))
    return dims


def curvas_carga_velocidad(mediciones: list[Medicion]) -> list[dict]:
    """Una curva por fecha: [{fecha, puntos: [(carga_kg, vmp_mil)]}], de la más vieja a la más nueva."""
    curvas = []
    for m in mediciones:
        if m.tipo != "carga_velocidad":
            continue
        puntos = []
        for medida, v in m.valores.items():
            try:
                carga = int(medida.removeprefix("VMP ").removesuffix(" kg"))
            except ValueError:
                continue
            puntos.append((carga, v.valor_mil))
        if puntos:
            curvas.append({"fecha": m.fecha, "puntos": sorted(puntos)})
    return curvas


MEDIDAS_FOTO = (("antropometria", "Peso"), ("antropometria", "Perímetro cintura"), ("antropometria", "% graso"),
                ("antropometria", "Suma 6 pliegues"))


def medidas_cercanas(mediciones: list[Medicion], fecha: str, max_dias: int = 45) -> list[dict]:
    """Para cada medida de MEDIDAS_FOTO, la medición más cercana a la fecha (hasta max_dias), con su método."""
    from datetime import date
    objetivo = date.fromisoformat(fecha)
    salida = []
    for tipo, medida in MEDIDAS_FOTO:
        mejor_d, elegida = None, None
        for m in mediciones:
            if m.tipo != tipo or medida not in m.valores:
                continue
            d = abs((date.fromisoformat(m.fecha) - objetivo).days)
            if d <= max_dias and (mejor_d is None or d < mejor_d):
                mejor_d, elegida = d, m
        if elegida:
            v = elegida.valores[medida]
            salida.append({"medida": medida, "valor_mil": v.valor_mil, "unidad": v.unidad, "fecha": elegida.fecha,
                           "metodo": elegida.metodo, "dias": mejor_d})
    return salida
