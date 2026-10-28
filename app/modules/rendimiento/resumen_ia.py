"""Resumen de rendimiento para que la sesión del Life Brain lo lea sin que el usuario escriba un prompt.

Escribe exports/rendimiento-ia.json (schema "1", ver docs/rendimiento-ia.md) y exports/rendimiento-ia.md.
La app nunca escribe en las notas canónicas del vault: la ingesta la hace la sesión del Life Brain.
Las fotos solo aparecen con su fecha y su pose, nunca su contenido.
Uso: uv run python -m app.modules.rendimiento.resumen_ia
"""

import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from app.core.resumen import escribir_par, sobre

from . import actividades as act
from . import consultas as q
from . import evaluaciones as ev
from . import competencia, logica, nutricion, semanas, vault

SCHEMA_VERSION = "1"
UNIDADES = ("Cargas en gramos (80 kg = 80000); duraciones en segundos; distancias en metros; FC en lpm; "
            "RPE en décimas (8,5 = 85); valores de test en milésimas de su unidad (44,20 cm = 47100); "
            "molestia del hombro de 0 a 10.")
DIAS = 90


def _series(con: sqlite3.Connection, sesion_id: int, peso_corporal_g: int | None) -> list[dict]:
    salida = []
    for b in q.bloques(con, sesion_id, peso_corporal_g):
        salida.append({
            "ejercicio": b.ejercicio["nombre"], "grupo": b.ejercicio["grupo"], "tipo_carga": b.ejercicio["tipo_carga"],
            "carga_el_hombro": bool(b.ejercicio["carga_hombro"]), "carga_total_g": b.carga_g,
            "series": [{"reps": s["reps"], "carga_g": s["carga_g"], "rpe_x10": s["rpe_x10"]} for s in b.series],
        })
    return salida


def _combate(con: sqlite3.Connection, sesion_id: int) -> list[dict]:
    return [{
        "tipo": b.bloque["tipo"], "duracion_s": b.bloque["duracion_s"], "rounds": b.bloque["rounds"], "rival": b.rivales,
        "entradas": [{"tecnica": e["tecnica"], "familia": e["familia"], "situacion": e["situacion"],
                      "resultado": e["resultado"], "detalle": e["detalle"]} for e in b.entradas],
    } for b in q.bloques_combate(con, sesion_id)]


def construir(con: sqlite3.Connection, boveda: Path, hoy: date) -> dict:
    desde = (hoy - timedelta(days=DIAS)).isoformat()
    todas_act = act.todas(con, boveda)
    por_clave = {a.clave: a for a in todas_act}
    pc = q.peso_corporal_g(con, boveda)
    sesiones = []
    for s in q.sesiones_entre(con, desde, hoy.isoformat()):
        a = por_clave.get(s["clave_importada"]) if s["clave_importada"] else None
        item = {
            "id": s["id"], "fecha": s["fecha"], "tipo": s["tipo"], "disciplina": s["disciplina"],
            "duracion_s": s["duracion_s"], "molestia_hombro": s["molestia_hombro"], "sensaciones": s["sensaciones"],
            "notas": s["notas"],
            "reloj": {"fuente": a.fuente, "deporte": a.deporte, "hora": a.hora, "duracion_s": a.duracion_s,
                      "fc_media": a.fc_media, "fc_max": a.fc_max} if a else None,
        }
        if s["tipo"] == "fuerza":
            item["ejercicios"] = _series(con, s["id"], pc)
            item["carga_total_g"] = q.carga_total_sesion(con, s["id"], pc)
        if s["tipo"] == "combate":
            item["bloques"] = _combate(con, s["id"])
        sesiones.append(item)

    notas = q.anotaciones(con)
    anotadas = [{"clave": k, "disciplina": n["disciplina"], "es_entrenamiento": n["es_entrenamiento"],
                 "sensaciones": n["sensaciones"], "molestia_hombro": n["molestia_hombro"], "notas": n["notas"]}
                for k, n in notas.items() if k.split("|")[1] >= desde]

    tests = [{"tipo": m.tipo, "fecha": m.fecha, "fecha_precision": m.precision, "fecha_aproximada": m.aproximada,
              "metodo": m.metodo, "evaluador": m.evaluador, "protocolo": m.protocolo, "notas": m.notas, "origen": m.origen,
              "valores": [{"medida": v.medida, "valor_mil": v.valor_mil, "unidad": v.unidad, "direccion": v.direccion}
                          for v in m.valores.values()]}
             for m in ev.todas(con, boveda) if m.origen != "vault"]  # lo del vault ya está en el vault

    actual = logica.semana_iso(hoy)
    sa = semanas.resumen(con, boveda, actual, todas_act)
    sp = semanas.resumen(con, boveda, logica.semana_anterior(actual), todas_act)
    resumen_semanas = [{"semana": w.semana, "sesiones": w.sesiones, "minutos_s": w.minutos_s, "carga_g": w.carga_g,
                        "zonas_s": w.zonas_s, "zonas_estimadas": w.zonas_estimadas, "sueno_s": w.sueno_s,
                        "hrv_ms": w.hrv_ms, "fc_reposo": w.fc_reposo, "pasos": w.pasos,
                        "molestia_promedio_mil": w.molestia_mil} for w in (sp, sa)]

    hitos = [{"nombre": h.nombre, "inicio": h.inicio.isoformat(), "fin": h.fin.isoformat(), "aproximado": h.aproximado,
              "texto": h.texto} for h in vault.hitos(boveda)]
    fotos = _fotos(con)

    avisos = []
    molestias = [s["molestia_hombro"] for s in sesiones if s["molestia_hombro"] is not None]
    if logica.molestia_al_alza(molestias):
        avisos.append("Molestia del hombro al alza en las últimas sesiones. " + logica.AVISO_MOLESTIA + ".")
    imp = vault.importar(boveda)
    ult = imp.ultima_fecha
    if ult.get("garmin") and (hoy - date.fromisoformat(ult["garmin"])).days > 7:
        avisos.append(f"Datos de Garmin hasta {ult['garmin']}: sincronizar.")
    sin_confirmar = sum(1 for a in todas_act if not a.confirmada and a.fecha >= desde)
    if sin_confirmar:
        avisos.append(f"{sin_confirmar} sesiones de Polar sin confirmar si fueron judo o BJJ (se cuentan como la sugerida).")

    return {
        **sobre("rendimiento", hoy, SCHEMA_VERSION, UNIDADES),
        "periodo": {"desde": desde, "hasta": hoy.isoformat()},
        "sesiones": sesiones, "actividades_anotadas": anotadas, "tests": tests, "semanas": resumen_semanas,
        "metas": {"hitos": hitos, "pasos_dia": vault.meta_pasos(boveda)}, "fotos": fotos, "avisos": avisos,
        "comidas": _comidas(con, desde), "pesajes": _pesajes(con, desde),
    }


def _pesajes(con: sqlite3.Connection, desde: str) -> list[dict]:
    """Pesajes en casa de la vista Competencia, tal como los registró: el peso es [M] y la nota [H] en el .md."""
    existe = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pesajes'").fetchone()
    if not existe:
        return []
    return [{"fecha": p.fecha, "hora": p.hora or None, "peso_g": p.peso_g, "condicion": p.condicion or None, "nota": p.nota or None}
            for p in competencia.pesajes(con, desde)]


def _fotos(con: sqlite3.Connection) -> list[dict]:
    """Solo fecha y pose (fase 2; tabla fotos_cuerpo, porque finanzas ya usa "fotos"). Nunca la imagen ni su ruta."""
    existe = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'fotos_cuerpo'").fetchone()
    if not existe:
        return []
    return [{"fecha": r["fecha"], "pose": r["pose"]} for r in con.execute("SELECT fecha, pose FROM fotos_cuerpo ORDER BY fecha")]


def _comidas(con: sqlite3.Connection, desde: str) -> list[dict]:
    """Comidas registradas (fase 4), tal como las escribió: [H]. Sin estimaciones."""
    existe = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'comidas_registro'").fetchone()
    return nutricion.ultimos(con, desde) if existe else []


def _kg(g) -> str:
    return logica.fmt_kg(g)


def markdown(d: dict) -> str:
    f = d["fuente"]
    out = ["---", "type: training", f"updated: {d['hoy']}", "sources: [app rendimiento]",
           f"schema_version: {d['schema_version']}", "---", "",
           f"# Rendimiento para IA, {d['hoy']}", "",
           f"Generado por la app de rendimiento. Datos del {d['periodo']['desde']} al {d['periodo']['hasta']}.", ""]
    out += ["## Sesiones registradas en la app", ""]
    if not d["sesiones"]:
        out.append("- Sin sesiones registradas en el período.")
    for s in d["sesiones"]:
        cab = f"- [M] {s['fecha']} {vault.NOMBRES.get(s['disciplina'], s['disciplina'])}"
        if s["duracion_s"]:
            cab += f", {logica.fmt_duracion(s['duracion_s'])}"
        if s.get("carga_total_g") is not None:
            cab += f", carga total {_kg(s['carga_total_g'])}"
        if s["molestia_hombro"] is not None:
            cab += f", molestia del hombro {s['molestia_hombro']}/10"
        if s["reloj"]:
            r = s["reloj"]
            cab += f", reloj {r['fuente']} ({r['deporte']}, FC media {r['fc_media']}, máx {r['fc_max']})"
        out.append(cab + f" · {f}")
        for e in s.get("ejercicios", []):
            series = ", ".join(f"{x['reps']}x{logica.fmt_carga(x['carga_g'])}" + (f" RPE {logica.fmt_rpe(x['rpe_x10'])}" if x["rpe_x10"] else "")
                               for x in e["series"])
            out.append(f"  - [M] {e['ejercicio']}: {series} kg · {f}")
        for b in s.get("bloques", []):
            partes = []
            for en in b["entradas"]:
                nombre = en["tecnica"] or (q.SITUACIONES.get(en["situacion"]) if en["situacion"] else None) or en["detalle"]
                txt = nombre or ""
                if en["resultado"] != "trabajada":
                    txt += f" ({q.RESULTADOS[en['resultado']].lower()}"
                    txt += f": {en['detalle']})" if en["detalle"] and en["detalle"] != nombre else ")"
                partes.append(txt)
            extra = []
            if b["duracion_s"]:
                extra.append(logica.fmt_duracion(b["duracion_s"]))
            if b["rounds"]:
                extra.append(f"{b['rounds']} rounds")
            if b["rival"]:
                extra.append("rival " + ", ".join(b["rival"]))
            out.append(f"  - [M] {q.TIPOS_BLOQUE[b['tipo']]}" + (f" ({', '.join(extra)})" if extra else "")
                       + (": " + "; ".join(partes) if partes else "") + f" · {f}")
        if s["notas"]:
            out.append(f"  - [M] Notas: {s['notas']} · {f}")
    if d["actividades_anotadas"]:
        out += ["", "## Correcciones y sensaciones sobre actividades del reloj", ""]
        for a in d["actividades_anotadas"]:
            partes = [f"{k} {v}" for k, v in (("disciplina", a["disciplina"]), ("sensaciones", a["sensaciones"]),
                                               ("molestia del hombro", a["molestia_hombro"])) if v is not None]
            if a["es_entrenamiento"] is not None:
                partes.append("cuenta como entrenamiento" if a["es_entrenamiento"] else "no es entrenamiento")
            if a["notas"]:
                partes.append(f"notas: {a['notas']}")
            out.append(f"- [M] {a['clave']}: " + "; ".join(partes) + f" · {f}")
    if d["tests"]:
        out += ["", "## Tests", ""]
        for t in d["tests"]:
            vals = ", ".join(f"{v['medida']} {logica.fmt_decimal(v['valor_mil'])}{(' ' + v['unidad']) if v['unidad'] else ''}"
                             for v in t["valores"])
            out.append(f"- [M] {t['fecha']} {ev.NOMBRES_TIPO.get(t['tipo'], t['tipo'])}"
                       + (f" ({t['metodo']})" if t["metodo"] else "") + (f": {vals}" if vals else "")
                       + (f". {t['notas']}" if t["notas"] else "") + f" · {f}")
    out += ["", "## Semanas", ""]
    for w in d["semanas"]:
        out.append(f"- [M] {w['semana']}: {w['sesiones']} sesiones, {logica.fmt_duracion(w['minutos_s'])}"
                   + (f", carga total {_kg(w['carga_g'])}" if w["carga_g"] is not None else "")
                   + (f", sueño promedio {logica.fmt_duracion(w['sueno_s'])}" if w["sueno_s"] else ", sueño sin dato")
                   + (f", FC en reposo {w['fc_reposo']}" if w["fc_reposo"] else "") + f" · {f}")
    if d.get("comidas"):
        out += ["", "## Comidas registradas en la app", ""]
        for c in d["comidas"]:
            partes = [c["texto"]] if c["texto"] else []
            if c["segun_plan"]:
                partes.append("según el plan")
            if c["intercambios"]:
                partes.append("intercambios: " + ", ".join(f"{n} {g}" for g, n in c["intercambios"].items()))
            out.append(f"- [H] {c['fecha']} {nutricion.MOMENTOS[c['momento']]}" + (f" {c['hora']}" if c["hora"] else "")
                       + ": " + "; ".join(partes) + f" · {f}")
    if d.get("pesajes"):
        out += ["", "## Pesajes en casa (vista Competencia)", ""]
        for x in d["pesajes"]:
            cond = competencia.CONDICIONES.get(x["condicion"], "").lower()
            out.append(f"- [M] {x['fecha']}" + (f" {x['hora']}" if x["hora"] else "") + f": {_kg(x['peso_g'])}"
                       + (f", {cond}" if cond else "") + f" · {f}")
            if x["nota"]:
                out.append(f"- [H] {x['fecha']}, nota del pesaje: {x['nota']} · {f}")
    if d["fotos"]:
        out += ["", "## Fotos (solo fecha y pose)", ""] + [f"- [M] {x['fecha']} {x['pose']} · {f}" for x in d["fotos"]]
    if d["avisos"]:
        out += ["", "## Avisos", ""] + [f"- {a}" for a in d["avisos"]]
    return "\n".join(out) + "\n"


def escribir(con: sqlite3.Connection, carpeta: Path, boveda: Path, hoy: date) -> tuple[Path, Path]:
    datos = construir(con, boveda, hoy)
    return escribir_par(carpeta, "rendimiento-ia", datos, markdown(datos))


def main() -> int:
    from app.core.config import leer_config
    from app.core.db import conectar, migrar
    cfg = leer_config()
    con = conectar(cfg.db_path)
    migrar(con)
    js, md = escribir(con, cfg.exports_path, cfg.vault_path, date.today())
    print(f"Escrito {js} y {md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
