"""Análisis con Claude: datos de la app y prompts para "Analiza mi semana", "Analiza mi combate" y
"Compara mis fotos". Los ejecuta trabajos.py con `claude -p` en el vault y solo con Read, Grep y Glob.

Los datos que solo están en la app (sesiones, series, combate, molestia) van dentro del prompt como JSON;
el vault aporta el contexto (objetivos, hombro, perfil) y Claude lo lee por su cuenta. Las fotos se copian a
una carpeta temporal con solo las dos elegidas, que se borra al terminar.
"""

import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from app.core.config import Config

from . import actividades as act
from . import combate, logica, resumen_ia, semanas, trabajos, vault
from . import evaluaciones as ev
from . import fotos as fx

SEMANAS_ELEGIBLES = 12
SESIONES_COMBATE = (5, 10, 20)
REFERENTES = ("Sanshiro Murao", "Shohei Ono", "Teddy Riner", "Gordon Ryan", "Marcelo Garcia", "Buakaw Banchamek")

CONTEXTO_VAULT = (
    "03_Training/objetivos-deportivos.md", "03_Training/perfil-deportivo.md", "03_Training/planificacion-semanal.md",
    "03_Training/cardio-y-zonas.md", "02_Health/lesiones.md", "02_Health/sueno-y-recuperacion.md",
)

FORMATO = """Formato de la respuesta (Markdown simple, máximo 350 palabras):
## Lo que veo
- 3 a 5 viñetas con observaciones concretas sobre los datos, con cifras.
## Qué ajustar
- 2 a 4 recomendaciones, cada una empieza con [I].
## Para hablar con tus profesionales
- 1 a 3 preguntas para el entrenador, el fisio, la nutricionista o el ortopedista, si aplica.
Sin tablas, sin título general y sin texto antes ni después de esas secciones. Si faltan datos para opinar,
dilo en vez de suponer."""


class AnalisisInvalido(ValueError):
    """Los parámetros del análisis no sirven; el mensaje dice cómo arreglarlo."""


@dataclass
class Preparado:
    prompt: str
    carpetas: list[Path] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    limpiar: Callable[[], None] = lambda: None


def _base(objetivo: str) -> str:
    notas = ", ".join(CONTEXTO_VAULT)
    return f"""Eres el analista de entrenamiento del usuario, judoka que también hace BJJ, Muay Thai y fuerza. La carpeta de
trabajo es su vault (Life Brain); sigue AGENTS.md. Tienes solo herramientas de lectura: no intentes escribir ni
editar nada. {objetivo}

Antes de responder lee lo que necesites del vault para el contexto, sobre todo: {notas}.
Si los objetivos del vault mencionan una cirugía prevista, antes de ella el objetivo es entrenar sin volver a
lesionarse; después, la rehabilitación la mandan el fisio y el ortopedista y tú
solo resumes lo que ellos indicaron.

{trabajos.REGLAS_CONTENIDO}

Unidades de los datos de la app: {resumen_ia.UNIDADES}
"""


def _json(datos) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=1, default=str)


# Semana --------------------------------------------------------------------

def semanas_elegibles(hoy: date) -> list[str]:
    return semanas.semanas_recientes(hoy, SEMANAS_ELEGIBLES)


def datos_semana(con: sqlite3.Connection, boveda: Path, semana: str, hoy: date) -> dict:
    lunes, domingo = logica.rango_semana(semana)
    todas = act.todas(con, boveda)
    imp = vault.importar(boveda)
    anterior = logica.semana_anterior(semana)
    sb = semanas.resumen(con, boveda, semana, todas, imp)
    sa = semanas.resumen(con, boveda, anterior, todas, imp)
    hasta = min(domingo, hoy)
    registradas = [s for s in resumen_ia.construir(con, boveda, hasta)["sesiones"]
                   if lunes.isoformat() <= s["fecha"] <= domingo.isoformat()]
    return {
        "semana": semana, "del": lunes.isoformat(), "al": domingo.isoformat(), "semana_anterior": anterior,
        "en_curso": lunes <= hoy <= domingo,
        "metricas": [{"grupo": m.grupo, "metrica": m.nombre, "semana_anterior": m.a, "esta_semana": m.b,
                      "escala": m.escala, "unidad": m.unidad, "direccion": m.direccion, "nota": m.nota}
                     for m in semanas.comparar(sa, sb)],
        "entrenos": [{"fecha": e.fecha, "disciplina": e.disciplina, "duracion_s": e.duracion_s, "fc_media": e.fc_media,
                      "fc_dudosa": e.fc_dudosa, "zonas_s": e.zonas_s, "molestia_hombro": e.molestia}
                     for e in sorted(sb.entrenos, key=lambda e: e.fecha)],
        "series_por_grupo": dict(sb.series_grupo), "tecnicas": dict(sb.tecnicas), "situaciones": dict(sb.situaciones),
        "sesiones_registradas_en_la_app": registradas,
    }


def prompt_semana(datos: dict) -> str:
    curso = " La semana está en curso: no la juzgues como completa." if datos["en_curso"] else ""
    return _base(
        f"Analiza la semana {datos['semana']} (del {datos['del']} al {datos['al']}) frente a la anterior "
        f"({datos['semana_anterior']}): qué ajustar en volumen, intensidad y recuperación.{curso}"
    ) + f"""
Datos de la app (las métricas traen su dirección: "mas" es mejor si sube, "menos" si baja, "neutra" no es ni mejor
ni peor; null es sin dato, no cero):
```json
{_json(datos)}
```

{FORMATO}"""


# Combate -------------------------------------------------------------------

def datos_combate(con: sqlite3.Connection, n: int, disciplina: str | None) -> dict:
    filtro = " AND disciplina = ?" if disciplina else ""
    params = (disciplina, n) if disciplina else (n,)
    filas = con.execute("SELECT * FROM sesiones WHERE tipo = 'combate' AND guardada = 1" + filtro
                        + " ORDER BY fecha DESC, id DESC LIMIT ?", params).fetchall()
    sesiones = [{"fecha": s["fecha"], "disciplina": s["disciplina"], "duracion_s": s["duracion_s"],
                 "molestia_hombro": s["molestia_hombro"], "notas": s["notas"], "bloques": resumen_ia._combate(con, s["id"])}
                for s in reversed(filas)]
    if not sesiones:
        return {"sesiones": [], "patrones": None}
    p = combate.patrones(con, sesiones[0]["fecha"], sesiones[-1]["fecha"], disciplina)
    patrones = {
        "tecnicas": [{"tecnica": t.nombre, "familia": t.familia, "veces": t.veces, "funciono": t.funciono,
                      "no_funciono": t.no_funciono} for t in p["tecnicas"]],
        "situaciones": p["situaciones"], "situaciones_resultado": p["situaciones_resultado"],
        "familias": p["familias"], "rivales": p["rivales"], "minutos_por_bloque": p["bloques_min"],
    }
    return {"sesiones": sesiones, "patrones": patrones}


def prompt_combate(datos: dict, n: int, disciplina: str | None, referente: str) -> str:
    cual = vault.NOMBRES.get(disciplina, disciplina) if disciplina else "combate (judo, BJJ y Muay Thai)"
    ref = (f" Compara su estilo con el de {referente}, solo con lo que sepas con confianza de cómo compite; si no "
           f"conoces bien su estilo, dilo y no lo inventes. Marca la comparación con [I].") if referente else ""
    return _base(
        f"Analiza los patrones técnico-tácticos de sus últimas {n} sesiones de {cual}: qué repite, qué le funciona, "
        f"qué no le funciona y qué le falta trabajar, según lo que registró en cada sesión.{ref}"
    ) + f"""
Datos de la app (bloques de trabajo con sus técnicas, situaciones, resultado "funciono", "no_funciono" o
"trabajada" y tipo de rival):
```json
{_json(datos)}
```

{FORMATO}"""


# Fotos ---------------------------------------------------------------------

def _medidas(meds: list, fecha: str) -> list[dict]:
    return [{"medida": m["medida"], "valor": logica.fmt_decimal(m["valor_mil"]), "unidad": m["unidad"],
             "fecha": m["fecha"], "metodo": m["metodo"]} for m in ev.medidas_cercanas(meds, fecha)]


def fotos_elegidas(con: sqlite3.Connection, a: int | None, b: int | None) -> tuple[fx.Foto, fx.Foto]:
    fa, fb = fx.foto(con, a) if a else None, fx.foto(con, b) if b else None
    if not fa or not fb:
        raise AnalisisInvalido("Elige dos fotos.")
    if fa.id == fb.id:
        raise AnalisisInvalido("Elige dos fechas distintas.")
    if fa.pose != fb.pose:
        raise AnalisisInvalido("Las dos fotos deben ser de la misma pose.")
    return (fa, fb) if fa.fecha <= fb.fecha else (fb, fa)


def preparar_fotos(con: sqlite3.Connection, cfg: Config, params: dict) -> Preparado:
    fa, fb = fotos_elegidas(con, params.get("a"), params.get("b"))
    origen = [fx.ruta(cfg.fotos_path, f) for f in (fa, fb)]
    if not all(p.is_file() for p in origen):
        raise AnalisisInvalido("No encontré el archivo de una de las fotos en data/fotos.")
    carpeta = Path(tempfile.mkdtemp(prefix="fotos-ia-", dir=cfg.db_path.parent))
    os.chmod(carpeta, 0o700)
    copias = []
    for etiqueta, f, src in (("antes", fa, origen[0]), ("despues", fb, origen[1])):
        destino = carpeta / f"{etiqueta}_{f.fecha}_{f.pose}.jpg"
        shutil.copyfile(src, destino)
        os.chmod(destino, 0o600)
        copias.append(destino)
    meds = ev.todas(con, cfg.vault_path)
    datos = {"pose": fa.nombre_pose,
             "antes": {"fecha": fa.fecha, "archivo": str(copias[0]), "medidas_cercanas": _medidas(meds, fa.fecha)},
             "despues": {"fecha": fb.fecha, "archivo": str(copias[1]), "medidas_cercanas": _medidas(meds, fb.fecha)}}
    prompt = _base(
        f"Compara dos fotos de su cuerpo, pose {fa.nombre_pose.lower()}, del {fa.fecha} (antes) y del {fb.fecha} "
        "(después). Lee las dos imágenes con Read. Haz observaciones visibles (postura, simetría, volumen aparente "
        "por zona, definición), no diagnósticos: no estimes porcentaje graso ni peso a partir de la imagen, y "
        "advierte si la luz, la distancia o el encuadre cambian lo que se ve. Relaciona lo que ves con las medidas "
        "más cercanas a cada fecha, si las hay, sin mezclar métodos distintos."
    ) + f"""
Fotos y medidas (las medidas vienen de los tests; "metodo" distinto = no son comparables entre sí):
```json
{_json(datos)}
```

{FORMATO}"""
    enviado = datetime.now().strftime("%Y-%m-%d a las %H:%M")
    extra = {"fotos": {"pose": fa.pose, "a": fa.id, "b": fb.id, "fecha_a": fa.fecha, "fecha_b": fb.fecha},
             "envio": f"Fotos de {fa.nombre_pose.lower()} del {fa.fecha} y del {fb.fecha} enviadas a Anthropic "
                      f"(Claude) el {enviado}, con tu confirmación."}
    return Preparado(prompt, [carpeta], extra, lambda: shutil.rmtree(carpeta, ignore_errors=True))


# Despacho y resultado ------------------------------------------------------

def preparar(con: sqlite3.Connection, cfg: Config, tipo: str, params: dict) -> Preparado:
    hoy = date.fromisoformat(params["hoy"]) if params.get("hoy") else date.today()
    if tipo == "analisis_semana":
        semana = params.get("semana") or logica.semana_iso(hoy)
        return Preparado(prompt_semana(datos_semana(con, cfg.vault_path, semana, hoy)))
    if tipo == "analisis_combate":
        n = int(params.get("n") or 10)
        disciplina = params.get("disciplina") or None
        datos = datos_combate(con, n, disciplina)
        if not datos["sesiones"]:
            raise AnalisisInvalido("No hay sesiones de combate registradas para analizar. Registra una en Registrar, Combate.")
        return Preparado(prompt_combate(datos, n, disciplina, (params.get("referente") or "").strip()))
    if tipo == "comparar_fotos":
        return preparar_fotos(con, cfg, params)
    raise AnalisisInvalido(f"Tipo de análisis desconocido: {tipo}")


def limpiar_texto(texto: str) -> str:
    """La interfaz nunca muestra la raya larga, aunque el modelo la use."""
    return (texto.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").strip())


def resultado(stdout: str) -> dict:
    """Texto y métricas de `claude -p --output-format json`; un error de Claude sale como excepción legible."""
    try:
        sobre = json.loads(stdout)
    except ValueError:
        texto = stdout.strip()
        if not texto:
            raise RuntimeError("Claude no devolvió nada.") from None
        return {"texto": limpiar_texto(texto)}
    if not isinstance(sobre, dict):
        raise RuntimeError("Claude devolvió una respuesta que no entiendo.")
    texto = str(sobre.get("result") or "")
    if sobre.get("is_error") or sobre.get("subtype", "success") != "success":
        detalle = texto or sobre.get("subtype") or "sin detalle"
        raise RuntimeError("Claude respondió con error: " + str(detalle)[:500])
    if not texto.strip():
        raise RuntimeError("Claude terminó sin texto de respuesta.")
    salida = {"texto": limpiar_texto(texto)}
    for clave, nombre in (("total_cost_usd", "costo_usd"), ("duration_ms", "duracion_ms"), ("num_turns", "turnos")):
        if isinstance(sobre.get(clave), (int, float)):
            salida[nombre] = sobre[clave]
    return salida


def resumen_parametros(tipo: str, params: dict, res: dict | None = None) -> str:
    """Una línea para la interfaz: qué se analizó."""
    if tipo == "analisis_semana":
        s = params.get("semana", "")
        try:
            return semanas.Semana(s, *logica.rango_semana(s)).etiqueta
        except Exception:  # noqa: BLE001
            return s
    if tipo == "analisis_combate":
        d = vault.NOMBRES.get(params.get("disciplina") or "", "combate")
        texto = f"Últimas {params.get('n', 10)} sesiones de {d}"
        return texto + (f", frente a {params['referente']}" if params.get("referente") else "")
    if tipo == "comparar_fotos":
        f = (res or {}).get("fotos") or params
        if f.get("fecha_a"):
            return f"{fx.POSES.get(f.get('pose'), '').capitalize()}: {f['fecha_a']} y {f['fecha_b']}"
        return "Dos fotos de la misma pose"
    return ""


def semana_por_defecto(hoy: date) -> str:
    """Lunes y martes, la semana anterior (la actual casi no tiene datos); el resto, la actual."""
    return logica.semana_iso(hoy - timedelta(days=7)) if hoy.weekday() < 2 else logica.semana_iso(hoy)
