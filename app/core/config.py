"""Configuración desde variables de entorno y el archivo .env (sin dependencias extra)."""

import os
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def cargar_env(ruta: Path = RAIZ / ".env") -> None:
    """BRAIN_DEMO nunca se toma de un .env: un archivo no puede activar ni desactivar la demo."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        if clave.strip() == "BRAIN_DEMO":
            continue
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Config:
    pin: str
    secreto: str
    db_path: Path
    dias_sesion: int = 30
    exports_path: Path = RAIZ / "exports"
    vault_path: Path = Path.home() / "Documents" / "vault"
    fotos_path: Path = RAIZ / "data" / "fotos"
    escribir_comidas: bool = False
    claude_cmd: str = "claude"        # comando de Claude Code para los trabajos de fondo
    tiempo_max_s: int = 900           # tiempo máximo de un trabajo de fondo
    sincronizar_al_arrancar: bool = False  # el servicio lo activa (BRAIN_SINCRONIZAR_AL_ARRANCAR, por defecto 1)
    codex_cmd: str = "codex"          # Codex CLI para la imagen proyectada
    codex_home: Path = Path.home() / ".codex"
    tiempo_max_imagen_s: int = 3600   # tope total de un trabajo de imagen (análisis, imagen y verificación por pose)
    whisper_modelo: str = "small"     # faster-whisper para el registro por voz; debe estar ya en el caché
    modelo_voz: str = "opus"          # modelo de Claude que interpreta el relato
    tiempo_max_voz_s: int = 120       # tope de la llamada a Claude de un relato
    demo: bool = False                # BRAIN_DEMO=1: instancia con datos ficticios, sin servicios externos
    cookie: str = "brain_sesion"      # nombre de la cookie de sesión (la demo usa otro)
    datos_demo: Path | None = None    # carpeta de datos de la demo (por defecto RAIZ/demo/datos)


def variable(nombre: str, defecto: str = "") -> str:
    """Lee BRAIN_<nombre> y, si no existe, FINANZAS_<nombre> (nombres de antes de la app multi-módulo)."""
    return os.environ.get(f"BRAIN_{nombre}") or os.environ.get(f"FINANZAS_{nombre}") or defecto


# ---------- Demo ----------

COOKIE_DEMO = "atlas_demo_sesion"


def raiz_real() -> Path:
    """La carpeta de la app real; la demo nunca corre desde ahí ni lee nada de ahí."""
    return Path(os.environ.get("BRAIN_RAIZ_REAL") or Path.home() / "Documents" / "finanzas-personales").expanduser().resolve()


def protegidas() -> list[Path]:
    real, casa = raiz_real(), Path.home()
    return [p.resolve() for p in (real / "data", real / "exports", real / "backups", real / ".env",
                                  casa / "Documents" / "vault", casa / ".codex", casa / ".claude",
                                  casa / ".claude.json", casa / "caddy-raiz.crt")]


def datos_demo(raiz: Path = RAIZ) -> Path:
    return (raiz / "demo" / "datos").resolve()


def _dentro(ruta: Path, carpeta: Path) -> bool:
    return ruta == carpeta or carpeta in ruta.parents


def es_demo() -> bool:
    return os.environ.get("BRAIN_DEMO") == "1"


def exigir_raiz_demo(raiz: Path = RAIZ) -> None:
    if _dentro(raiz.resolve(), raiz_real()):
        raise RuntimeError("La demo corre desde su propio worktree, no desde la app real")


def validar_demo(cfg: Config) -> None:
    """Falla si alguna ruta de datos, ya resuelta (con enlaces simbólicos), apunta a datos reales o sale de demo/datos."""
    datos = (cfg.datos_demo or datos_demo()).expanduser().resolve()
    if any(_dentro(datos, p) or _dentro(p, datos) for p in protegidas()):
        raise RuntimeError(f"La carpeta de datos de la demo apunta a datos reales: {datos}")
    malas = []
    for nombre in ("db_path", "vault_path", "fotos_path", "exports_path", "codex_home"):
        ruta = Path(getattr(cfg, nombre)).expanduser().resolve()
        if any(_dentro(ruta, p) or _dentro(p, ruta) for p in protegidas()) or not _dentro(ruta, datos):
            malas.append(f"{nombre} ({ruta})")
    if malas:
        raise RuntimeError("La demo apunta a datos reales o fuera de demo/datos: " + ", ".join(malas))


def _ruta_demo(nombre: str, raiz: Path) -> Path:
    valor = os.environ.get(nombre if nombre == "CODEX_HOME" else f"BRAIN_{nombre}")
    if not valor:
        raise RuntimeError(f"La demo necesita {nombre if nombre == 'CODEX_HOME' else 'BRAIN_' + nombre} en su .env")
    ruta = Path(valor).expanduser()
    return ruta if ruta.is_absolute() else raiz / ruta


def leer_config_demo(raiz: Path = RAIZ) -> Config:
    """La configuración de la demo: el .env es el del worktree de la demo, las rutas son obligatorias y lo externo,
    apagado. No cae a los valores por defecto, que apuntan a la app real."""
    exigir_raiz_demo(raiz)
    cargar_env(raiz / ".env")
    pin, secreto = os.environ.get("BRAIN_PIN"), os.environ.get("BRAIN_SECRETO")
    if not pin or not secreto:
        raise RuntimeError("Faltan BRAIN_PIN o BRAIN_SECRETO en el .env de la demo.")
    cfg = Config(
        pin=pin, secreto=secreto,
        db_path=_ruta_demo("DB", raiz), vault_path=_ruta_demo("VAULT", raiz), fotos_path=_ruta_demo("FOTOS", raiz),
        exports_path=_ruta_demo("EXPORTS", raiz), codex_home=_ruta_demo("CODEX_HOME", raiz),
        escribir_comidas=False, sincronizar_al_arrancar=False, demo=True,
        cookie=os.environ.get("BRAIN_COOKIE") or COOKIE_DEMO, datos_demo=datos_demo(raiz),
    )
    validar_demo(cfg)
    return cfg


def leer_config() -> Config:
    if es_demo():
        return leer_config_demo()
    cargar_env()
    pin = variable("PIN")
    secreto = variable("SECRETO")
    if not pin or not secreto:
        raise RuntimeError(
            "Faltan BRAIN_PIN o BRAIN_SECRETO (o los antiguos FINANZAS_PIN y FINANZAS_SECRETO)."
            " Copia .env.example a .env y complétalo."
        )
    return Config(
        pin=pin,
        secreto=secreto,
        db_path=Path(variable("DB", str(RAIZ / "data" / "finanzas.db"))),
        exports_path=Path(variable("EXPORTS", str(RAIZ / "exports"))),
        vault_path=Path(variable("VAULT", str(Path.home() / "Documents" / "vault"))).expanduser(),
        fotos_path=Path(variable("FOTOS", str(RAIZ / "data" / "fotos"))),
        escribir_comidas=os.environ.get("BRAIN_ESCRIBIR_COMIDAS") == "1",
        claude_cmd=os.environ.get("BRAIN_CLAUDE", "claude"),
        tiempo_max_s=int(os.environ.get("BRAIN_TIEMPO_MAX", "900")),
        sincronizar_al_arrancar=os.environ.get("BRAIN_SINCRONIZAR_AL_ARRANCAR", "1") == "1",
        codex_cmd=os.environ.get("BRAIN_CODEX", "codex"),
        codex_home=Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser(),
        tiempo_max_imagen_s=int(os.environ.get("BRAIN_TIEMPO_MAX_IMAGEN", "3600")),
        whisper_modelo=os.environ.get("BRAIN_WHISPER_MODELO", "small"),
        modelo_voz=os.environ.get("BRAIN_MODELO_VOZ", "opus"),
        tiempo_max_voz_s=int(os.environ.get("BRAIN_TIEMPO_MAX_VOZ", "120")),
    )
