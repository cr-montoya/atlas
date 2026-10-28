"""Consultas SQL de rendimiento (sqlite3, SQL a mano)."""

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import logica, vault

PASO_KG_G = 2500   # los controles de más y menos mueven 2,5 kg
REPS_DEFECTO = 8


class ErrorDatos(ValueError):
    """Dato que no existe o no se puede guardar; el mensaje es legible para el usuario."""


# Catálogo -------------------------------------------------------------------

def ejercicios(con: sqlite3.Connection, activos: bool = True) -> list[sqlite3.Row]:
    sql = "SELECT * FROM ejercicios" + (" WHERE activo = 1" if activos else "") + " ORDER BY grupo, nombre"
    return con.execute(sql).fetchall()


def ejercicio(con: sqlite3.Connection, ejercicio_id: int) -> sqlite3.Row:
    r = con.execute("SELECT * FROM ejercicios WHERE id = ?", (ejercicio_id,)).fetchone()
    if r is None:
        raise ErrorDatos("Ese ejercicio no existe en el catálogo.")
    return r


def ejercicio_por_nombre(con: sqlite3.Connection, nombre: str) -> sqlite3.Row:
    r = con.execute("SELECT * FROM ejercicios WHERE nombre = ?", (nombre,)).fetchone()
    if r is None:
        raise ErrorDatos(f"No encontré «{nombre}» en el catálogo.")
    return r


def ejercicios_recientes(con: sqlite3.Connection, limite: int = 6) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT e.* FROM ejercicios e JOIN series s ON s.ejercicio_id = e.id JOIN sesiones se ON se.id = s.sesion_id"
        " WHERE e.activo = 1 GROUP BY e.id ORDER BY MAX(se.fecha) DESC, MAX(s.id) DESC LIMIT ?", (limite,)).fetchall()


def crear_ejercicio(con: sqlite3.Connection, nombre: str, grupo: str, tipo_carga: str, carga_hombro: bool) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ErrorDatos("Escribe el nombre del ejercicio.")
    try:
        with con:
            return con.execute(
                "INSERT INTO ejercicios (nombre, grupo, tipo_carga, carga_hombro) VALUES (?, ?, ?, ?)",
                (nombre, grupo, tipo_carga, int(carga_hombro))).lastrowid
    except sqlite3.IntegrityError:
        raise ErrorDatos(f"Ya existe un ejercicio llamado «{nombre}».") from None


def editar_ejercicio(con: sqlite3.Connection, ejercicio_id: int, grupo: str, tipo_carga: str,
                     carga_hombro: bool, activo: bool) -> None:
    with con:
        con.execute("UPDATE ejercicios SET grupo = ?, tipo_carga = ?, carga_hombro = ?, activo = ? WHERE id = ?",
                    (grupo, tipo_carga, int(carga_hombro), int(activo), ejercicio_id))


# Sesiones -------------------------------------------------------------------

def crear_sesion(con: sqlite3.Connection, fecha: str, tipo: str, disciplina: str, hora: str | None = None) -> int:
    with con:
        return _insertar_sesion(con, fecha, tipo, disciplina, hora)


def _insertar_sesion(con: sqlite3.Connection, fecha: str, tipo: str, disciplina: str, hora: str | None = None, *,
                     duracion_s: int | None = None, molestia: int | None = None, sensaciones: int | None = None,
                     notas: str = "", clave_importada: str | None = None, guardada: bool = False) -> int:
    """Sin commit: para escribir varias cosas en una sola transacción (registro por voz)."""
    if molestia is not None and not 0 <= molestia <= 10:
        raise ErrorDatos("La molestia del hombro va de 0 a 10.")
    if sensaciones is not None and not 1 <= sensaciones <= 5:
        raise ErrorDatos("Las sensaciones van de 1 a 5.")
    return con.execute(
        "INSERT INTO sesiones (fecha, hora, tipo, disciplina, duracion_s, molestia_hombro, sensaciones, notas,"
        " clave_importada, guardada) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (fecha, hora, tipo, disciplina, duracion_s, molestia, sensaciones, (notas or "").strip() or None,
         clave_importada, int(guardada))).lastrowid


def sesion(con: sqlite3.Connection, sesion_id: int) -> sqlite3.Row:
    r = con.execute("SELECT * FROM sesiones WHERE id = ?", (sesion_id,)).fetchone()
    if r is None:
        raise ErrorDatos("Esa sesión no existe.")
    return r


def borrador(con: sqlite3.Connection, fecha: str, tipo: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM sesiones WHERE fecha = ? AND tipo = ? AND guardada = 0 ORDER BY id DESC LIMIT 1",
                       (fecha, tipo)).fetchone()


def guardar_sesion(con: sqlite3.Connection, sesion_id: int, *, duracion_s: int | None, molestia: int | None,
                   sensaciones: int | None, notas: str, clave_importada: str | None) -> None:
    if molestia is not None and not 0 <= molestia <= 10:
        raise ErrorDatos("La molestia del hombro va de 0 a 10.")
    if sensaciones is not None and not 1 <= sensaciones <= 5:
        raise ErrorDatos("Las sensaciones van de 1 a 5.")
    with con:
        con.execute("UPDATE sesiones SET duracion_s = ?, molestia_hombro = ?, sensaciones = ?, notas = ?,"
                    " clave_importada = ?, guardada = 1 WHERE id = ?",
                    (duracion_s, molestia, sensaciones, notas.strip() or None, clave_importada, sesion_id))


def borrar_sesion(con: sqlite3.Connection, sesion_id: int) -> None:
    with con:
        con.execute("DELETE FROM sesiones WHERE id = ?", (sesion_id,))


def borrar_borradores_viejos(con: sqlite3.Connection, hoy: date, dias: int = 7) -> int:
    """Al arrancar: las sesiones sin guardar de antes del rango editable, con sus series y bloques (CASCADE)."""
    with con:
        return con.execute("DELETE FROM sesiones WHERE guardada = 0 AND fecha < ?",
                           ((hoy - timedelta(days=dias)).isoformat(),)).rowcount


def sesiones_entre(con: sqlite3.Connection, desde: str, hasta: str, solo_guardadas: bool = True) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM sesiones WHERE fecha BETWEEN ? AND ?" + (" AND guardada = 1" if solo_guardadas else "")
                       + " ORDER BY fecha, hora, id", (desde, hasta)).fetchall()


def claves_vinculadas(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT clave_importada FROM sesiones WHERE clave_importada IS NOT NULL")}


# Series ---------------------------------------------------------------------

@dataclass
class BloqueEjercicio:
    ejercicio: sqlite3.Row
    series: list[sqlite3.Row] = field(default_factory=list)
    carga_g: int | None = 0


def _ultima_serie(con: sqlite3.Connection, ejercicio_id: int, sesion_id: int) -> sqlite3.Row | None:
    """La última serie de ese ejercicio en esta sesión o, si no hay, en la sesión más reciente."""
    r = con.execute("SELECT * FROM series WHERE sesion_id = ? AND ejercicio_id = ? ORDER BY orden DESC LIMIT 1",
                    (sesion_id, ejercicio_id)).fetchone()
    if r:
        return r
    return con.execute(
        "SELECT s.* FROM series s JOIN sesiones se ON se.id = s.sesion_id WHERE s.ejercicio_id = ? AND s.sesion_id != ?"
        " ORDER BY se.fecha DESC, s.sesion_id DESC, s.orden DESC LIMIT 1", (ejercicio_id, sesion_id)).fetchone()


def agregar_serie(con: sqlite3.Connection, sesion_id: int, ejercicio_id: int, *, reps: int | None = None,
                  carga_g: int | None = None, rpe_x10: int | None = None, peso_corporal_g: int | None = None) -> int:
    """Agrega una serie. Sin valores, copia la serie anterior del mismo ejercicio."""
    ejercicio(con, ejercicio_id)
    previa = _ultima_serie(con, ejercicio_id, sesion_id)
    if reps is None:
        reps = previa["reps"] if previa else REPS_DEFECTO
    if carga_g is None:
        carga_g = previa["carga_g"] if previa else 0
    if rpe_x10 is None and previa and previa["sesion_id"] == sesion_id:
        rpe_x10 = previa["rpe_x10"]
    with con:
        return _insertar_serie(con, sesion_id, ejercicio_id, reps=reps, carga_g=carga_g, rpe_x10=rpe_x10,
                               peso_corporal_g=peso_corporal_g)


def _insertar_serie(con: sqlite3.Connection, sesion_id: int, ejercicio_id: int, *, reps: int, carga_g: int,
                    rpe_x10: int | None, peso_corporal_g: int | None = None) -> int:
    """Sin commit y sin copiar nada de otra serie: guarda exactamente los valores dados."""
    _validar(reps, carga_g, rpe_x10)
    orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM series WHERE sesion_id = ?", (sesion_id,)).fetchone()[0]
    return con.execute(
        "INSERT INTO series (sesion_id, ejercicio_id, orden, reps, carga_g, rpe_x10, peso_corporal_g)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sesion_id, ejercicio_id, orden, reps, carga_g, rpe_x10, peso_corporal_g)).lastrowid


def _validar(reps: int, carga_g: int, rpe_x10: int | None) -> None:
    if not 1 <= reps <= 100:
        raise ErrorDatos("Las repeticiones van de 1 a 100.")
    if not 0 <= carga_g <= 1_000_000:
        raise ErrorDatos("La carga debe estar entre 0 y 1.000 kg.")
    if rpe_x10 is not None and not 10 <= rpe_x10 <= 100:
        raise ErrorDatos("El RPE va de 1 a 10.")


def serie(con: sqlite3.Connection, serie_id: int) -> sqlite3.Row:
    r = con.execute("SELECT * FROM series WHERE id = ?", (serie_id,)).fetchone()
    if r is None:
        raise ErrorDatos("Esa serie ya no existe.")
    return r


def actualizar_serie(con: sqlite3.Connection, serie_id: int, *, reps: int, carga_g: int, rpe_x10: int | None) -> None:
    _validar(reps, carga_g, rpe_x10)
    with con:
        con.execute("UPDATE series SET reps = ?, carga_g = ?, rpe_x10 = ? WHERE id = ?", (reps, carga_g, rpe_x10, serie_id))


def ajustar_serie(con: sqlite3.Connection, serie_id: int, campo: str, paso: int) -> None:
    """Controles de más y menos: repeticiones de 1 en 1, carga de 2,5 kg en 2,5 kg, sin bajar de 1 rep ni de 0 kg."""
    s = serie(con, serie_id)
    if campo == "reps":
        actualizar_serie(con, serie_id, reps=min(max(s["reps"] + paso, 1), 100), carga_g=s["carga_g"], rpe_x10=s["rpe_x10"])
    elif campo == "carga":
        actualizar_serie(con, serie_id, reps=s["reps"], carga_g=max(s["carga_g"] + paso * PASO_KG_G, 0), rpe_x10=s["rpe_x10"])
    else:
        raise ErrorDatos("Campo desconocido.")


def borrar_serie(con: sqlite3.Connection, serie_id: int) -> None:
    with con:
        con.execute("DELETE FROM series WHERE id = ?", (serie_id,))


def quitar_ejercicio(con: sqlite3.Connection, sesion_id: int, ejercicio_id: int) -> None:
    with con:
        con.execute("DELETE FROM series WHERE sesion_id = ? AND ejercicio_id = ?", (sesion_id, ejercicio_id))


def bloques(con: sqlite3.Connection, sesion_id: int, peso_corporal_g: int | None = None) -> list[BloqueEjercicio]:
    """Series agrupadas por ejercicio, en el orden en que se agregó cada ejercicio, con su carga total."""
    salida: dict[int, BloqueEjercicio] = {}
    for s in con.execute("SELECT * FROM series WHERE sesion_id = ? ORDER BY orden", (sesion_id,)):
        b = salida.get(s["ejercicio_id"])
        if b is None:
            b = salida[s["ejercicio_id"]] = BloqueEjercicio(ejercicio(con, s["ejercicio_id"]))
        b.series.append(s)
    for b in salida.values():
        b.carga_g = carga_series(b.ejercicio["tipo_carga"], b.series, peso_corporal_g)
    return list(salida.values())


def carga_series(tipo_carga: str, series: list, peso_corporal_g: int | None) -> int | None:
    total = 0
    for s in series:
        pc = s["peso_corporal_g"] if s["peso_corporal_g"] is not None else peso_corporal_g
        c = logica.carga_serie_g(tipo_carga, s["reps"], s["carga_g"], pc)
        if c is None:
            return None
        total += c
    return total


def carga_total_sesion(con: sqlite3.Connection, sesion_id: int, peso_corporal_g: int | None = None) -> int | None:
    cargas = [b.carga_g for b in bloques(con, sesion_id, peso_corporal_g)]
    return None if any(c is None for c in cargas) else sum(cargas)


def sesion_anterior(con: sqlite3.Connection, sesion_id: int, tipo: str) -> sqlite3.Row | None:
    actual = sesion(con, sesion_id)
    return con.execute(
        "SELECT * FROM sesiones WHERE tipo = ? AND guardada = 1 AND id != ? AND fecha <= ?"
        " AND EXISTS (SELECT 1 FROM series WHERE sesion_id = sesiones.id) ORDER BY fecha DESC, id DESC LIMIT 1",
        (tipo, sesion_id, actual["fecha"])).fetchone()


def repetir_sesion(con: sqlite3.Connection, sesion_id: int, origen_id: int, peso_corporal_g: int | None = None) -> int:
    """Copia ejercicios y series de otra sesión como punto de partida. Devuelve cuántas series copió."""
    filas = con.execute("SELECT * FROM series WHERE sesion_id = ? ORDER BY orden", (origen_id,)).fetchall()
    base = con.execute("SELECT COALESCE(MAX(orden), 0) FROM series WHERE sesion_id = ?", (sesion_id,)).fetchone()[0]
    with con:
        for i, s in enumerate(filas, start=1):
            con.execute(
                "INSERT INTO series (sesion_id, ejercicio_id, orden, reps, carga_g, rpe_x10, peso_corporal_g)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (sesion_id, s["ejercicio_id"], base + i, s["reps"], s["carga_g"], s["rpe_x10"], peso_corporal_g))
    return len(filas)


# Peso corporal --------------------------------------------------------------

def peso_corporal_g(con: sqlite3.Connection, boveda: Path) -> int | None:
    """Peso más reciente: el de un test de la app o el de composicion-corporal.md, el que sea más nuevo."""
    candidatos: list[tuple[str, int]] = []
    r = con.execute("SELECT t.fecha, v.valor_mil FROM test_valores v JOIN tests t ON t.id = v.test_id"
                    " WHERE v.medida = 'Peso' AND v.unidad = 'kg' ORDER BY t.fecha DESC, t.id DESC LIMIT 1").fetchone()
    if r:
        candidatos.append((r[0], r[1]))
    for t in vault.tests(boveda):
        for val in t.valores:
            if val.medida == "Peso" and val.unidad == "kg":
                candidatos.append((t.fecha, val.valor_mil))
    if not candidatos:
        return None
    return max(candidatos)[1]  # kg en milésimas = gramos


# Anotaciones de sesiones importadas -----------------------------------------

def anotaciones(con: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {r["clave"]: r for r in con.execute("SELECT * FROM anotaciones_importadas")}


def anotar(con: sqlite3.Connection, clave: str, **campos) -> None:
    with con:
        _anotar(con, clave, **campos)


def _anotar(con: sqlite3.Connection, clave: str, **campos) -> None:
    """Sin commit."""
    permitidos = {"disciplina", "es_entrenamiento", "sensaciones", "molestia_hombro", "notas"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    columnas = ", ".join(campos)
    marcas = ", ".join("?" for _ in campos)
    actualizar = ", ".join(f"{k} = excluded.{k}" for k in campos)
    con.execute(f"INSERT INTO anotaciones_importadas (clave, {columnas}) VALUES (?, {marcas})"
                f" ON CONFLICT (clave) DO UPDATE SET {actualizar}, actualizada = datetime('now')",
                (clave, *campos.values()))


# Combate --------------------------------------------------------------------

DISCIPLINAS_COMBATE = ("judo", "bjj", "muaythai")
TIPOS_BLOQUE = {"tecnica": "Técnica", "drill": "Uchikomi o drill", "situacional": "Situacional", "randori": "Randori"}
SITUACIONES = {"agarre": "Agarre y kumikata", "entradas": "Entradas", "transiciones": "Transiciones", "defensa": "Defensa"}
RIVALES = ("más pesado", "más liviano", "zurdo", "más técnico")
RESULTADOS = {"trabajada": "Trabajada", "funciono": "Funcionó", "no_funciono": "No funcionó"}
CON_RESULTADO = ("situacional", "randori")


@dataclass
class BloqueCombate:
    bloque: sqlite3.Row
    entradas: list[sqlite3.Row] = field(default_factory=list)

    @property
    def nombre(self) -> str:
        return TIPOS_BLOQUE[self.bloque["tipo"]]

    @property
    def con_resultado(self) -> bool:
        return self.bloque["tipo"] in CON_RESULTADO

    @property
    def rivales(self) -> list[str]:
        return [x.strip() for x in (self.bloque["rival"] or "").split(",") if x.strip()]


def cambiar_disciplina(con: sqlite3.Connection, sesion_id: int, disciplina: str) -> None:
    if disciplina not in DISCIPLINAS_COMBATE:
        raise ErrorDatos("Elige judo, BJJ o Muay Thai.")
    with con:
        con.execute("UPDATE sesiones SET disciplina = ? WHERE id = ? AND tipo = 'combate'", (disciplina, sesion_id))


def crear_bloque(con: sqlite3.Connection, sesion_id: int, tipo: str, duracion_s: int | None = None,
                 rounds: int | None = None) -> int:
    with con:
        return _insertar_bloque(con, sesion_id, tipo, duracion_s, rounds)


def _insertar_bloque(con: sqlite3.Connection, sesion_id: int, tipo: str, duracion_s: int | None = None,
                     rounds: int | None = None) -> int:
    """Sin commit."""
    if tipo not in TIPOS_BLOQUE:
        raise ErrorDatos("Tipo de bloque desconocido.")
    if duracion_s is not None and not 0 <= duracion_s <= 6 * 3600:
        raise ErrorDatos("La duración del bloque va en minutos, hasta 360.")
    if rounds is not None and not 1 <= rounds <= 50:
        raise ErrorDatos("Los rounds van de 1 a 50.")
    orden = con.execute("SELECT COALESCE(MAX(orden), 0) + 1 FROM combate_bloques WHERE sesion_id = ?", (sesion_id,)).fetchone()[0]
    return con.execute("INSERT INTO combate_bloques (sesion_id, orden, tipo, duracion_s, rounds) VALUES (?, ?, ?, ?, ?)",
                       (sesion_id, orden, tipo, duracion_s, rounds)).lastrowid


def bloque_combate(con: sqlite3.Connection, bloque_id: int) -> sqlite3.Row:
    r = con.execute("SELECT * FROM combate_bloques WHERE id = ?", (bloque_id,)).fetchone()
    if r is None:
        raise ErrorDatos("Ese bloque ya no existe.")
    return r


def actualizar_bloque(con: sqlite3.Connection, bloque_id: int, *, duracion_s: int | None, rounds: int | None,
                      rivales: list[str]) -> None:
    if duracion_s is not None and not 0 <= duracion_s <= 6 * 3600:
        raise ErrorDatos("La duración del bloque va en minutos, hasta 360.")
    if rounds is not None and not 1 <= rounds <= 50:
        raise ErrorDatos("Los rounds van de 1 a 50.")
    rival = ", ".join(r for r in RIVALES if r in rivales) or None
    with con:
        con.execute("UPDATE combate_bloques SET duracion_s = ?, rounds = ?, rival = ? WHERE id = ?",
                    (duracion_s, rounds, rival, bloque_id))


def borrar_bloque(con: sqlite3.Connection, bloque_id: int) -> None:
    with con:
        con.execute("DELETE FROM combate_bloques WHERE id = ?", (bloque_id,))


def agregar_entrada(con: sqlite3.Connection, bloque_id: int, *, tecnica_id: int | None = None, situacion: str | None = None,
                    resultado: str = "trabajada", detalle: str | None = None) -> int:
    with con:
        return _insertar_entrada(con, bloque_id, tecnica_id=tecnica_id, situacion=situacion, resultado=resultado,
                                 detalle=detalle)


def _insertar_entrada(con: sqlite3.Connection, bloque_id: int, *, tecnica_id: int | None = None,
                      situacion: str | None = None, resultado: str = "trabajada", detalle: str | None = None) -> int:
    """Sin commit."""
    if tecnica_id is None and situacion is None and not (detalle or "").strip():
        raise ErrorDatos("Elige una técnica o una situación, o escribe qué trabajaste.")
    if situacion is not None and situacion not in SITUACIONES:
        raise ErrorDatos("Situación desconocida.")
    if resultado not in RESULTADOS:
        raise ErrorDatos("Resultado desconocido.")
    if tecnica_id is not None and con.execute("SELECT 1 FROM tecnicas WHERE id = ?", (tecnica_id,)).fetchone() is None:
        raise ErrorDatos("Esa técnica no existe en el catálogo.")
    return con.execute("INSERT INTO combate_tecnicas (bloque_id, tecnica_id, situacion, resultado, detalle)"
                       " VALUES (?, ?, ?, ?, ?)",
                       (bloque_id, tecnica_id, situacion, resultado, (detalle or "").strip() or None)).lastrowid


def entrada(con: sqlite3.Connection, entrada_id: int) -> sqlite3.Row:
    r = con.execute("SELECT * FROM combate_tecnicas WHERE id = ?", (entrada_id,)).fetchone()
    if r is None:
        raise ErrorDatos("Esa entrada ya no existe.")
    return r


def actualizar_entrada(con: sqlite3.Connection, entrada_id: int, *, resultado: str, detalle: str | None) -> None:
    if resultado not in RESULTADOS:
        raise ErrorDatos("Resultado desconocido.")
    with con:
        con.execute("UPDATE combate_tecnicas SET resultado = ?, detalle = ? WHERE id = ?",
                    (resultado, (detalle or "").strip() or None, entrada_id))


def borrar_entrada(con: sqlite3.Connection, entrada_id: int) -> None:
    with con:
        con.execute("DELETE FROM combate_tecnicas WHERE id = ?", (entrada_id,))


def bloques_combate(con: sqlite3.Connection, sesion_id: int) -> list[BloqueCombate]:
    salida = [BloqueCombate(b) for b in con.execute(
        "SELECT * FROM combate_bloques WHERE sesion_id = ? ORDER BY orden", (sesion_id,))]
    for b in salida:
        b.entradas = con.execute(
            "SELECT ct.*, t.nombre AS tecnica, t.familia FROM combate_tecnicas ct LEFT JOIN tecnicas t ON t.id = ct.tecnica_id"
            " WHERE ct.bloque_id = ? ORDER BY ct.id", (b.bloque["id"],)).fetchall()
    return salida


def buscar_tecnicas(con: sqlite3.Connection, disciplina: str, texto: str = "", limite: int = 12) -> list[sqlite3.Row]:
    """Sin texto: las más usadas recientemente en esa disciplina y luego el catálogo. Con texto: coincidencias."""
    texto = (texto or "").strip()
    if texto:
        patron = f"%{texto.replace('-', ' ')}%"
        return con.execute(
            "SELECT * FROM tecnicas WHERE disciplina = ? AND activo = 1 AND (replace(nombre, '-', ' ') LIKE ? OR familia LIKE ?)"
            " ORDER BY nombre LIMIT ?", (disciplina, patron, patron, limite)).fetchall()
    recientes = con.execute(
        "SELECT t.* FROM tecnicas t JOIN combate_tecnicas ct ON ct.tecnica_id = t.id JOIN combate_bloques b ON b.id = ct.bloque_id"
        " JOIN sesiones s ON s.id = b.sesion_id WHERE t.disciplina = ? AND t.activo = 1"
        " GROUP BY t.id ORDER BY MAX(s.fecha) DESC, COUNT(*) DESC LIMIT ?", (disciplina, limite)).fetchall()
    return recientes


def tecnicas_por_familia(con: sqlite3.Connection, disciplina: str) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM tecnicas WHERE disciplina = ? AND activo = 1 ORDER BY familia, nombre",
                       (disciplina,)).fetchall()


def duracion_combate(con: sqlite3.Connection, sesion_id: int) -> int | None:
    r = con.execute("SELECT SUM(duracion_s) FROM combate_bloques WHERE sesion_id = ?", (sesion_id,)).fetchone()[0]
    return r


# Tests ----------------------------------------------------------------------

def crear_test(con: sqlite3.Connection, *, tipo: str, fecha: str, precision: str = "dia", aproximada: bool = False,
               metodo: str | None = None, evaluador: str | None = None, protocolo: str | None = None,
               notas: str | None = None, valores: list[tuple[str, int, str, str]]) -> int:
    if not valores and not (notas or "").strip():
        raise ErrorDatos("Escribe al menos un valor o una nota del test.")
    with con:
        tid = con.execute(
            "INSERT INTO tests (tipo, fecha, fecha_precision, fecha_aproximada, metodo, evaluador, protocolo, notas, origen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'app')",
            (tipo, fecha, precision, int(aproximada), metodo or None, evaluador or None, protocolo or None,
             (notas or "").strip() or None)).lastrowid
        for medida, valor, unidad, direccion in valores:
            con.execute("INSERT INTO test_valores (test_id, medida, valor_mil, unidad, direccion) VALUES (?, ?, ?, ?, ?)",
                        (tid, medida, valor, unidad, direccion))
    return tid


def borrar_test(con: sqlite3.Connection, test_id: int) -> None:
    with con:
        con.execute("DELETE FROM tests WHERE id = ?", (test_id,))


def crear_tecnica(con: sqlite3.Connection, disciplina: str, familia: str, nombre: str) -> int:
    nombre, familia = nombre.strip(), familia.strip()
    if disciplina not in DISCIPLINAS_COMBATE:
        raise ErrorDatos("Elige judo, BJJ o Muay Thai.")
    if not nombre or not familia:
        raise ErrorDatos("Escribe la familia y el nombre de la técnica.")
    try:
        with con:
            return con.execute("INSERT INTO tecnicas (disciplina, familia, nombre) VALUES (?, ?, ?)",
                               (disciplina, familia, nombre)).lastrowid
    except sqlite3.IntegrityError:
        raise ErrorDatos(f"Ya existe «{nombre}» en {disciplina}.") from None


def activar_tecnica(con: sqlite3.Connection, tecnica_id: int, activo: bool) -> None:
    with con:
        con.execute("UPDATE tecnicas SET activo = ? WHERE id = ?", (int(activo), tecnica_id))
