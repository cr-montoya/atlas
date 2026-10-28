"""Fotos del cuerpo: guardar sin metadatos, con permisos 600 y miniatura; consultas y comparación.

Las imágenes nunca salen del portátil (salvo el envío explícito y confirmado a Codex para la imagen proyectada) y nunca van al
resumen para IA: allí solo aparecen la fecha y la pose.
"""

import io
import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

POSES = {"frente": "Frente", "perfil_derecho": "Perfil derecho", "espalda": "Espalda"}
LADO_MAX = 2000        # px del lado largo de la foto guardada
LADO_MINI = 480        # px del lado largo de la miniatura
MAX_BYTES = 25 * 1024 * 1024
MINIATURAS = "miniaturas"


class FotoInvalida(ValueError):
    """La foto no se pudo guardar; el mensaje dice cómo arreglarlo."""


@dataclass(frozen=True)
class Foto:
    id: int
    fecha: str
    pose: str
    archivo: str
    ancho: int
    alto: int

    @property
    def nombre_pose(self) -> str:
        return POSES[self.pose]


def _carpeta(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    mini = base / MINIATURAS
    mini.mkdir(exist_ok=True)
    os.chmod(mini, 0o700)
    return base


def _guardar_jpeg(img: Image.Image, ruta: Path, calidad: int) -> None:
    """JPEG sin EXIF (ni GPS, ni modelo de cámara, ni fecha), escrito con permisos 600 de forma atómica."""
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=calidad, optimize=True, progressive=True)  # sin exif=: no se copia nada
    tmp = ruta.with_name(f".{ruta.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(buf.getvalue())
    os.chmod(tmp, 0o600)
    os.replace(tmp, ruta)


MAX_LOTE = 20        # fotos por subida desde la galería o los archivos
EXIF_IFD, FECHA_ORIGINAL, FECHA_DIGITAL, FECHA_ARCHIVO = 0x8769, 0x9003, 0x9004, 0x0132


def fecha_tomada(datos: bytes, hoy: date | None = None) -> str | None:
    """La fecha en que se tomó la foto según su EXIF (DateTimeOriginal y, si no, las otras), antes de que
    se descarte el EXIF al guardar. None si no la trae o no es creíble (antes de 2000 o en el futuro)."""
    try:
        exif = Image.open(io.BytesIO(datos)).getexif()
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    sub = exif.get_ifd(EXIF_IFD) if exif else {}
    for valor in (sub.get(FECHA_ORIGINAL), sub.get(FECHA_DIGITAL), exif.get(FECHA_ARCHIVO) if exif else None):
        if not valor:
            continue
        try:
            d = date(int(str(valor)[0:4]), int(str(valor)[5:7]), int(str(valor)[8:10]))
        except ValueError:
            continue
        if date(2000, 1, 1) <= d <= (hoy or date.today()):
            return d.isoformat()
    return None


def procesar(datos: bytes) -> Image.Image:
    if not datos:
        raise FotoInvalida("Elige una foto.")
    if len(datos) > MAX_BYTES:
        raise FotoInvalida("La foto pesa más de 25 MB. Tómala de nuevo con menos resolución.")
    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise FotoInvalida("No pude leer la foto. Usa JPEG o PNG; en el iPhone: Ajustes, Cámara, Formatos, "
                           "Más compatible.") from None
    img = ImageOps.exif_transpose(img)  # aplica la orientación antes de descartar el EXIF
    img = img.convert("RGB")
    img.thumbnail((LADO_MAX, LADO_MAX))
    return img


def guardar(con: sqlite3.Connection, base: Path, fecha: str, pose: str, datos: bytes, notas: str = "") -> Foto:
    if pose not in POSES:
        raise FotoInvalida("Elige la pose: frente, perfil derecho o espalda.")
    try:
        date.fromisoformat(fecha)
    except ValueError:
        raise FotoInvalida("La fecha va como 2026-10-17.") from None
    img = procesar(datos)
    carpeta = _carpeta(base)
    nombre = f"{fecha}_{pose}.jpg"
    _guardar_jpeg(img, carpeta / nombre, 88)
    mini = img.copy()
    mini.thumbnail((LADO_MINI, LADO_MINI))
    _guardar_jpeg(mini, carpeta / MINIATURAS / nombre, 80)
    with con:
        con.execute("INSERT INTO fotos_cuerpo (fecha, pose, archivo, ancho, alto, notas) VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT (fecha, pose) DO UPDATE SET archivo = excluded.archivo, ancho = excluded.ancho,"
                    " alto = excluded.alto, notas = excluded.notas, creada = datetime('now')",
                    (fecha, pose, nombre, img.width, img.height, notas.strip() or None))
    return foto_por(con, fecha, pose)


def _fila(r: sqlite3.Row) -> Foto:
    return Foto(r["id"], r["fecha"], r["pose"], r["archivo"], r["ancho"], r["alto"])


def foto(con: sqlite3.Connection, foto_id: int) -> Foto | None:
    r = con.execute("SELECT * FROM fotos_cuerpo WHERE id = ?", (foto_id,)).fetchone()
    return _fila(r) if r else None


def foto_por(con: sqlite3.Connection, fecha: str, pose: str) -> Foto | None:
    r = con.execute("SELECT * FROM fotos_cuerpo WHERE fecha = ? AND pose = ?", (fecha, pose)).fetchone()
    return _fila(r) if r else None


def de_pose(con: sqlite3.Connection, pose: str) -> list[Foto]:
    return [_fila(r) for r in con.execute("SELECT * FROM fotos_cuerpo WHERE pose = ? ORDER BY fecha", (pose,))]


def ultima(con: sqlite3.Connection, pose: str) -> Foto | None:
    r = con.execute("SELECT * FROM fotos_cuerpo WHERE pose = ? ORDER BY fecha DESC LIMIT 1", (pose,)).fetchone()
    return _fila(r) if r else None


def conteo_por_pose(con: sqlite3.Connection) -> dict[str, int]:
    return {r[0]: r[1] for r in con.execute("SELECT pose, COUNT(*) FROM fotos_cuerpo GROUP BY pose")}


def ruta(base: Path, f: Foto, miniatura: bool = False) -> Path:
    return base / (MINIATURAS if miniatura else "") / f.archivo


def borrar(con: sqlite3.Connection, base: Path, foto_id: int) -> None:
    f = foto(con, foto_id)
    if f is None:
        return
    for p in (ruta(base, f), ruta(base, f, True)):
        p.unlink(missing_ok=True)
    with con:
        con.execute("DELETE FROM fotos_cuerpo WHERE id = ?", (foto_id,))
