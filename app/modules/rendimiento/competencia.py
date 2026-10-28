"""Competencia: el torneo de las secciones "## Hacia el torneo" de planificacion-semanal.md, los pesajes y el
checklist del día (openspec/changes/v1-competencia).

Del vault (solo lectura) salen las fechas, el lugar, el límite de peso, el plan día por día, el guion de
combate y los ítems del checklist. Cada línea del vault trae prefijos de clasificación ([M], [H], [O]...) y
una cita al final (" · [S29 | alta]"); el lector los quita. Mientras la sección diga "Plan en validación",
el plan, su meta y sus días de pesaje no se usan. Los pesajes y las marcas del checklist son de la app
(SQLite); las marcas se borran cuando pasa el torneo. Tono neutro y sin indicaciones médicas: la vista no
califica el peso ni sugiere nada. Un dato mal escrito en el vault nunca tumba una página: se avisa.
"""

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import logica, vault
from .logica import ValorInvalido

PLAN = Path("03_Training/planificacion-semanal.md")
CONDICIONES = {"ropa_interior": "En ropa interior", "con_ropa": "Con ropa"}
PESO_MIN_G, PESO_MAX_G = 30000, 200000
NOTA_MAX = 200
VENTANA_GRAFICA = 60     # días antes del torneo

_BULLET = re.compile(r"^\s*[-*]\s+")
_PREFIJO = re.compile(r"^(\[[A-Za-z?]+\]\s*)+")
_CITA = re.compile(r"\s*·\s*\[[^\]]*\]\s*$")
_H2 = re.compile(r"^##(?!#)\s*(.*)$")
_H3 = re.compile(r"^###(?!#)\s*(.*)$")
_HORA = r"\d{1,2}:\d{2}"


def ahora() -> datetime:
    """Única fuente de fecha y hora de la vista (hora local del servicio, TZ=America/Bogota)."""
    return datetime.now()


def norm(texto: str) -> str:
    """Para comparar: NFC, sin tildes y en minúsculas. 'Guión' -> 'guion'."""
    t = unicodedata.normalize("NFD", unicodedata.normalize("NFC", texto))
    return "".join(c for c in t if not unicodedata.combining(c)).lower().strip()


def limpiar(linea: str) -> str:
    """'- [O] **Judogi:** el azul · [U 2026-10-19 | alta]' -> '**Judogi:** el azul'."""
    t = _BULLET.sub("", linea.strip())
    return _CITA.sub("", _PREFIJO.sub("", t.strip())).strip()


def _es_bullet(linea: str) -> bool:
    return bool(_BULLET.match(linea))


@dataclass(frozen=True)
class DiaPlan:
    fecha: date
    combate: str
    fuerza: str
    cardio: str
    notas: str

    @property
    def pesaje_casa(self) -> bool:
        return "pesaje en casa" in norm(self.notas)

    @property
    def meta_g(self) -> int | None:
        """'Pesaje en casa en la mañana: meta 77,5 kg o menos' -> 77500."""
        m = re.search(r"meta:?\s+(\d{2,3}(?:[.,]\d+)?)\s*kg", self.notas, re.I)
        return logica.parse_kg(m.group(1)) if m else None


@dataclass(frozen=True)
class Tarjeta:
    titulo: str
    texto: str


@dataclass(frozen=True)
class Competencia:
    nombre: str
    detalle: str                      # "Judo · Mayores novatos · 70 a 78 kg", si está en objetivos-deportivos.md
    torneo: datetime
    lugar: str
    pesaje_inicio: datetime
    pesaje_fin: datetime
    pesaje_condicion: str
    limite_g: int                     # 0 = sin límite en el vault
    en_validacion: bool
    plan: tuple[DiaPlan, ...]
    guion: tuple[Tarjeta, ...]
    checklist: tuple[str, ...]
    avisos: tuple[str, ...] = ()

    @property
    def clave(self) -> str:
        return self.torneo.date().isoformat()

    @property
    def plan_visible(self) -> tuple[DiaPlan, ...]:
        return () if self.en_validacion else self.plan

    def dia(self, d: date) -> DiaPlan | None:
        return next((p for p in self.plan_visible if p.fecha == d), None)

    @property
    def meta_peso(self) -> DiaPlan | None:
        """El día del plan aprobado con una meta de peso en las notas (la última, si hay varias)."""
        con_meta = [p for p in self.plan_visible if p.meta_g]
        return con_meta[-1] if con_meta else None


@dataclass(frozen=True)
class Lectura:
    """Lo que dejó la sección vigente: la competencia o el error de formato que la impide."""
    competencia: Competencia | None = None
    error: str = ""


# Lector ---------------------------------------------------------------------

class _Invalida(ValueError):
    pass


def _secciones(texto: str) -> list[tuple[str, list[str]]]:
    """(título, líneas) de cada sección '## Hacia el torneo …', hasta el siguiente '## '."""
    salida: list[tuple[str, list[str]]] = []
    actual: list[str] | None = None
    for linea in texto.splitlines():
        m = _H2.match(linea)
        if m:
            actual = None
            if norm(m.group(1)).startswith("hacia el torneo"):
                actual = []
                salida.append((m.group(1), actual))
        elif actual is not None:
            actual.append(linea)
    return salida


def _subsecciones(lineas: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    cabeza: list[str] = []
    subs: dict[str, list[str]] = {}
    actual = cabeza
    for linea in lineas:
        m = _H3.match(linea)
        if m:
            actual = subs.setdefault(norm(m.group(1)), [])
        else:
            actual.append(linea)
    return cabeza, subs


def _sub(subs: dict[str, list[str]], prefijo: str) -> list[str] | None:
    return next((v for k, v in subs.items() if k.startswith(prefijo)), None)


def _datos(cabeza: list[str]) -> dict[str, str]:
    """Las líneas 'Clave: valor' del bloque de datos, con la clave normalizada (torneo, pesaje, limite)."""
    datos: dict[str, str] = {}
    for linea in cabeza:
        if not _es_bullet(linea):
            continue
        m = re.match(r"([^:]{1,20}):\s*(.+)$", limpiar(linea).replace("**", ""))
        if m and norm(m.group(1)) in ("torneo", "pesaje", "limite"):
            datos.setdefault(norm(m.group(1)), m.group(2).strip())
    return datos


def _momento(fecha: str, hora: str) -> datetime:
    h, mi = hora.split(":")
    return datetime.combine(date.fromisoformat(fecha), time(int(h), int(mi)))


def _torneo(valor: str | None) -> tuple[datetime, str]:
    m = re.match(rf"(\d{{4}}-\d{{2}}-\d{{2}})\s+({_HORA})\s*(?:·\s*(.+))?$", valor or "")
    if not m:
        raise _Invalida("Torneo")
    try:
        return _momento(m.group(1), m.group(2)), (m.group(3) or "").strip()
    except ValueError:
        raise _Invalida("Torneo") from None


def _pesaje(valor: str | None) -> tuple[datetime, datetime, str]:
    m = re.match(rf"(\d{{4}}-\d{{2}}-\d{{2}})\s+({_HORA})\s*(?:a|-|–)\s*({_HORA})\s*(?:·\s*(.+))?$", valor or "")
    if not m:
        raise _Invalida("Pesaje")
    try:
        ini, fin = _momento(m.group(1), m.group(2)), _momento(m.group(1), m.group(3))
    except ValueError:
        raise _Invalida("Pesaje") from None
    if fin <= ini:
        raise _Invalida("Pesaje")
    return ini, fin, (m.group(4) or "").strip()


def _celda(texto: str) -> str:
    t = texto.strip()
    return "" if t in ("-", "–") else t


def _plan(lineas: list[str]) -> tuple[tuple[DiaPlan, ...], int]:
    """Días del plan y cuántas filas no se pudieron leer (sin contar encabezado ni separador)."""
    dias, malas = [], 0
    for linea in lineas:
        if not linea.strip().startswith("|"):
            continue
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in celdas) or norm(celdas[0]) == "fecha":
            continue
        try:
            if len(celdas) < 5:
                raise ValueError
            fecha = date.fromisoformat(celdas[0])
        except ValueError:
            malas += 1
            continue
        dias.append(DiaPlan(fecha, *(_celda(c) for c in celdas[1:5])))
    return tuple(sorted(dias, key=lambda d: d.fecha)), malas


def _guion(lineas: list[str]) -> tuple[Tarjeta, ...]:
    tarjetas = []
    for linea in lineas:
        if not _es_bullet(linea):
            continue
        m = re.match(r"\*\*(.+?):?\*\*:?\s*(.*)$", limpiar(linea))
        if m:
            tarjetas.append(Tarjeta(m.group(1).rstrip(":").strip(), m.group(2).strip()))
    return tuple(tarjetas)


def _checklist(lineas: list[str]) -> tuple[str, ...]:
    """La primera lista de la subsección, sin repetidos; termina en la primera línea en blanco."""
    items: list[str] = []
    for linea in lineas:
        if _es_bullet(linea):
            item = limpiar(linea).replace("**", "")
            if item and item not in items:
                items.append(item)
        elif items and not linea.strip():
            break
    return tuple(items)


def _validacion(lineas: list[str]) -> bool:
    return any(_es_bullet(l) and norm(limpiar(l)).startswith("plan en validacion") for l in lineas)


def _titulo_corto(titulo: str) -> str:
    t = re.sub(r"\s*\(.*$", "", _CITA.sub("", titulo)).strip()
    return (t[0].upper() + t[1:]) if t else "Competencia"


def _leer_seccion(titulo: str, lineas: list[str]) -> Competencia:
    cabeza, subs = _subsecciones(lineas)
    datos = _datos(cabeza)
    torneo, lugar = _torneo(datos.get("torneo"))
    p_ini, p_fin, condicion = _pesaje(datos.get("pesaje"))
    try:
        limite = logica.parse_kg(datos.get("limite", ""))
    except ValorInvalido:
        limite = 0
    plan, malas = _plan(_sub(subs, "plan dia por dia") or [])
    guion = _sub(subs, "guion de combate")
    checklist = _sub(subs, "checklist del dia")
    avisos = []
    if malas:
        avisos.append(f"{malas} fila{'s' if malas != 1 else ''} del plan no se {'pudieron' if malas != 1 else 'pudo'} leer")
    if guion is None:
        avisos.append("Sin guion de combate en la sección del torneo")
    if checklist is None:
        avisos.append("Sin checklist del día en la sección del torneo")
    return Competencia(
        nombre=_titulo_corto(titulo), detalle="", torneo=torneo, lugar=lugar, pesaje_inicio=p_ini, pesaje_fin=p_fin,
        pesaje_condicion=condicion, limite_g=limite, en_validacion=_validacion(lineas), plan=plan,
        guion=_guion(guion or []), checklist=_checklist(checklist or []), avisos=tuple(avisos),
    )


def leer(ruta: Path) -> tuple[tuple[Competencia | str, ...], ...]:
    """Cada sección: (competencia,) o (error,)."""
    texto = ruta.read_text(encoding="utf-8-sig")
    salida = []
    for titulo, lineas in _secciones(texto):
        try:
            salida.append((_leer_seccion(titulo, lineas),))
        except _Invalida as err:
            clave = str(err)
            linea = next((limpiar(l) for l in lineas if norm(limpiar(l).replace("**", "")).startswith(norm(clave))), "")
            salida.append((f"No pude leer la línea {clave} de planificacion-semanal.md"
                           + (f": «{linea}»" if linea else " (no está)"),))
    return tuple(salida)


def leer_objetivos(ruta: Path) -> dict[str, tuple[str, str]]:
    """Fecha ISO -> (nombre, detalle) de las filas '**Torneo de …**' de objetivos-deportivos.md."""
    salida: dict[str, tuple[str, str]] = {}
    for linea in ruta.read_text(encoding="utf-8-sig").splitlines():
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) < 2 or "**Torneo de" not in celdas[0] or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", celdas[1]):
            continue
        m = re.search(r"\*\*Torneo de (\w+), (.+?)\s*(?:\([^)]*\))?:\*\*", celdas[0])
        if not m:
            continue
        detalle = ""
        cat = re.search(r"categoría\s+(.+?)\s*(?:\([^)]*\))?,\s*división de\s+(.+?)\.", celdas[0])
        if cat:
            detalle = f"{m.group(1).capitalize()} · {cat.group(1).strip()} · {cat.group(2).strip()}"
        salida[celdas[1]] = (m.group(2).strip(), detalle)
    return salida


def vigente(boveda: Path, hoy: date) -> Lectura:
    """La próxima competencia (fecha igual o posterior a hoy); si no hay, la última que ya pasó."""
    ruta = boveda / PLAN
    if not ruta.is_file():
        return Lectura()
    leidas = [x[0] for x in vault._cacheado(ruta, leer)]
    validas = sorted((c for c in leidas if isinstance(c, Competencia)), key=lambda c: c.torneo)
    errores = [e for e in leidas if isinstance(e, str)]
    proximas = [c for c in validas if c.torneo.date() >= hoy]
    if proximas:
        c = proximas[0]
    elif errores:
        return Lectura(error=errores[0])
    elif validas:
        c = validas[-1]
    else:
        return Lectura()
    objetivos = boveda / vault.OBJETIVOS
    nombre = vault._cacheado(objetivos, leer_objetivos).get(c.clave) if objetivos.is_file() else None
    return Lectura(replace(c, nombre=nombre[0], detalle=nombre[1]) if nombre else c)


def activa(c: Competencia | None, hoy: date) -> bool:
    """La vista activa, el aviso en Hoy y el hito se muestran hasta el día del torneo."""
    return c is not None and hoy <= c.torneo.date()


# Cuenta regresiva -----------------------------------------------------------

def cuenta(inicio: datetime, fin: datetime, momento: datetime, en_curso: str = "en curso") -> dict:
    """Días de calendario hasta el inicio; el día anterior y el mismo día, con la hora."""
    dias = (inicio.date() - momento.date()).days
    if momento > fin:
        return {"dias": None, "texto": "ya pasó", "pasado": True}
    if momento >= inicio:
        return {"dias": 0, "texto": en_curso, "pasado": False}
    if dias == 0:
        return {"dias": 0, "texto": f"hoy, a las {inicio:%H:%M}", "pasado": False}
    if dias == 1:
        return {"dias": 1, "texto": f"mañana, a las {inicio:%H:%M}", "pasado": False}
    return {"dias": dias, "texto": f"en {dias} días", "pasado": False}


def cuentas(c: Competencia, momento: datetime) -> tuple[dict, dict]:
    fin_dia = datetime.combine(c.torneo.date(), time.max)
    return cuenta(c.pesaje_inicio, c.pesaje_fin, momento), cuenta(c.torneo, fin_dia, momento, en_curso="hoy")


# Pesajes --------------------------------------------------------------------

class PesajeInvalido(ValueError):
    """El pesaje no se guardó; el mensaje dice cómo arreglarlo."""


@dataclass(frozen=True)
class Pesaje:
    fecha: str
    hora: str
    peso_g: int
    condicion: str
    nota: str


def pesajes(con: sqlite3.Connection, desde: str | None = None) -> list[Pesaje]:
    filas = con.execute("SELECT fecha, hora, peso_g, condicion, nota FROM pesajes WHERE fecha >= ? ORDER BY fecha",
                        (desde or "0000",)).fetchall()
    return [Pesaje(r["fecha"], r["hora"] or "", r["peso_g"], r["condicion"] or "", r["nota"] or "") for r in filas]


def _fecha_pesaje(texto: str, hoy: date) -> str:
    try:
        d = date.fromisoformat(texto.strip())
    except ValueError:
        raise PesajeInvalido("Elige una fecha válida.") from None
    if d > hoy:
        raise PesajeInvalido("La fecha no puede ser posterior a hoy.")
    return d.isoformat()


def guardar_pesaje(con: sqlite3.Connection, hoy: date, fecha: str, hora: str, peso: str, condicion: str, nota: str) -> None:
    fecha = _fecha_pesaje(fecha, hoy)
    try:
        peso_g = logica.parse_kg(peso)
    except ValorInvalido:
        peso_g = 0
    if not PESO_MIN_G <= peso_g <= PESO_MAX_G:
        raise PesajeInvalido("Escribe el peso en kg, por ejemplo 77,4.")
    hora = hora.strip()
    if hora:
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", hora)
        if not m:
            raise PesajeInvalido("Escribe la hora como 7:10 o 07:10.")
        hora = f"{int(m.group(1)):02d}:{m.group(2)}"
    if condicion not in CONDICIONES:
        raise PesajeInvalido("Elige si fue en ropa interior o con ropa.")
    con.execute("""INSERT INTO pesajes (fecha, hora, peso_g, condicion, nota) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (fecha) DO UPDATE SET hora = excluded.hora, peso_g = excluded.peso_g,
                   condicion = excluded.condicion, nota = excluded.nota, actualizado = datetime('now')""",
                (fecha, hora or None, peso_g, condicion, nota.strip()[:NOTA_MAX] or None))
    con.commit()


def borrar_pesaje(con: sqlite3.Connection, fecha: str) -> bool:
    """Borra el pesaje de esa fecha si la fecha es válida y tiene pesaje."""
    try:
        fecha = date.fromisoformat(fecha.strip()).isoformat()
    except ValueError:
        return False
    cur = con.execute("DELETE FROM pesajes WHERE fecha = ?", (fecha,))
    con.commit()
    return cur.rowcount > 0


def frente_al_limite(peso_g: int, limite_g: int) -> str:
    """Texto neutro: '1 kg por debajo del límite', '0,04 kg por encima del límite'."""
    dif = limite_g - peso_g
    if dif == 0:
        return "justo en el límite"
    lado = "por debajo del" if dif > 0 else "por encima del"
    return f"{logica.fmt_decimal(abs(dif), 2)} kg {lado} límite"


def proximo_pesaje_casa(c: Competencia, hoy: date) -> date | None:
    """El siguiente día del plan con 'pesaje en casa'; sin plan aprobado, el siguiente lunes o jueves."""
    oficial = c.pesaje_inicio.date()
    if c.plan_visible:
        dias = [p.fecha for p in c.plan_visible if p.pesaje_casa and hoy <= p.fecha < oficial]
        return dias[0] if dias else None
    d = hoy
    while d < oficial:
        if d.weekday() in (0, 3):
            return d
        d += timedelta(days=1)
    return None


# Checklist ------------------------------------------------------------------

def borrar_marcas_pasadas(con: sqlite3.Connection, hoy: date) -> None:
    """Decisión 2a: las marcas de un torneo que ya pasó se borran (solo escribe si hay algo que borrar)."""
    if con.execute("SELECT 1 FROM checklist_competencia WHERE competencia < ? LIMIT 1", (hoy.isoformat(),)).fetchone():
        con.execute("DELETE FROM checklist_competencia WHERE competencia < ?", (hoy.isoformat(),))
        con.commit()


def marcas(con: sqlite3.Connection, c: Competencia) -> set[str]:
    return {r["item"] for r in con.execute("SELECT item FROM checklist_competencia WHERE competencia = ?", (c.clave,))}


def marcar(con: sqlite3.Connection, c: Competencia, item: str, marcado: bool) -> None:
    if item not in c.checklist:
        return
    if marcado:
        con.execute("INSERT OR IGNORE INTO checklist_competencia (competencia, item) VALUES (?, ?)", (c.clave, item))
    else:
        con.execute("DELETE FROM checklist_competencia WHERE competencia = ? AND item = ?", (c.clave, item))
    con.commit()
