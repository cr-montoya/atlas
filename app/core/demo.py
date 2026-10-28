"""Modo demo: la instancia con datos ficticios no toca servicios ni datos reales.

Toda acción externa (Garmin y Polar, claude -p, Codex, Whisper, escribir en el vault) pasa por `exigir_externo`,
que en la demo lanza `NoDisponibleEnDemo`; `main.py` la convierte en una página 409 con el aviso.
"""

from app.core.config import Config

AVISO = "No disponible en la demo: aquí no se conecta con Garmin, Polar, Claude ni Codex."


class NoDisponibleEnDemo(Exception):
    pass


def exigir_externo(cfg: Config, que: str) -> None:
    if cfg.demo:
        raise NoDisponibleEnDemo(que)
