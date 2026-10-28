"""Carga datos iniciales desde data/seed.local.toml (ignorado) o data/seed.example.toml.

Uso: uv run python -m app.modules.finanzas.seed [--reiniciar]
Sobre una base vacía carga todo; sobre una con datos solo completa lo que falte (v2: fondos,
eventos, escenario, tasas). --reiniciar borra la base primero.
"""

import sqlite3
import sys
import tomllib
from pathlib import Path

from app.core.config import RAIZ, leer_config
from app.core.db import conectar, migrar
from app.core.dinero import parse_centavos, parse_cop, parse_moneda, parse_tasa

from . import consultas, real
from .logica import Linea

SEED_LOCAL = RAIZ / "data" / "seed.local.toml"
SEED_EJEMPLO = RAIZ / "data" / "seed.example.toml"


def _monto(valor, moneda: str = "COP") -> int:
    return parse_moneda(str(valor), moneda)


def cargar(con: sqlite3.Connection, datos: dict) -> None:
    ids_bolsillo = {b["nombre"]: consultas.crear_bolsillo(con, b["nombre"], b["tipo"])
                    for b in datos.get("bolsillos", [])}
    ids_deuda, monedas = {}, {}
    for d in datos.get("deudas", []):
        ids_deuda[d["nombre"]] = consultas.crear_deuda(con, d["nombre"], d["moneda"], _monto(d["saldo"], d["moneda"]))
        monedas[d["nombre"]] = d["moneda"]
    ids_cuenta = {c["nombre"]: consultas.crear_cuenta(con, c["nombre"]) for c in datos.get("cuentas", [])}
    for m in datos.get("metas", []):
        consultas.crear_meta(con, m["nombre"], parse_cop(str(m["objetivo"])),
                             [ids_cuenta[c] for c in m["cuentas"]])
    for p in datos.get("plantillas", []):
        with con:
            pid = con.execute("INSERT INTO plantillas (nombre) VALUES (?)", (p["nombre"],)).lastrowid
        lineas = []
        for l in p.get("lineas", []):
            monto = str(l["monto"])
            modo = monto if monto in ("resto", "pedir") else "fijo"
            lineas.append(Linea(
                concepto=l["concepto"],
                bolsillo_id=ids_bolsillo[l["bolsillo"]],
                monto=parse_cop(monto) if modo == "fijo" else None,
                modo=modo,
                deuda_id=ids_deuda[l["deuda"]] if l.get("deuda") else None,
            ))
        consultas.guardar_lineas_plantilla(con, pid, lineas)
    # Abonos históricos: alimentan el promedio; el saldo cargado ya los descuenta.
    for a in datos.get("abonos", []):
        moneda = monedas[a["deuda"]]
        consultas.abonar(
            con, ids_deuda[a["deuda"]], str(a["fecha"]), _monto(a["monto"], moneda),
            trm=parse_centavos(str(a["trm"])) if a.get("trm") else None,
            costo_cop=parse_cop(str(a["costo_cop"])) if a.get("costo_cop") else None,
            nota=a.get("nota", ""), afecta_saldo=False,
        )
    for f in datos.get("fotos", []):
        saldos = {ids_cuenta[n]: parse_cop(str(v), permitir_negativo=True) for n, v in f.get("cuentas", {}).items()}
        sd = {ids_deuda[n]: _monto(v, monedas[n]) for n, v in f.get("deudas", {}).items()}
        consultas.guardar_foto(con, str(f["fecha"]), parse_centavos(str(f["trm"])), saldos, sd)
    completar(con, datos)


def _opcional_cop(valor) -> int | None:
    return None if valor in (None, "") else parse_cop(str(valor))


def completar(con: sqlite3.Connection, datos: dict) -> list[str]:
    """Agrega lo de v2 que falte (bolsillos, tasas, fondos, eventos, escenario, líneas de plantilla)
    sin tocar lo que ya existe. Sirve para una base cargada antes de v2."""
    hecho = []
    ids_b = {b["nombre"]: b["id"] for b in consultas.bolsillos(con)}
    for b in datos.get("bolsillos", []):
        if b["nombre"] not in ids_b:
            ids_b[b["nombre"]] = consultas.crear_bolsillo(con, b["nombre"], b["tipo"])
            hecho.append(f"bolsillo {b['nombre']}")
    ids_d = {d["nombre"]: d for d in consultas.deudas(con)}
    for d in datos.get("deudas", []):
        actual = ids_d.get(d["nombre"])
        if actual and actual["tasa_mensual_ppm"] is None and actual["cuota_mensual"] == 0 and ("tasa" in d or "cuota" in d):
            real.actualizar_deuda(con, actual["id"], parse_tasa(str(d["tasa"])) if d.get("tasa") else None,
                                  parse_cop(str(d.get("cuota") or "0")), d.get("prepagar", True))
            hecho.append(f"tasa y cuota de {d['nombre']}")
    for c in datos.get("cuentas", []):
        fila = con.execute("SELECT * FROM cuentas WHERE nombre = ?", (c["nombre"],)).fetchone()
        if fila and fila["rendimiento_ea_ppm"] is None and c.get("rendimiento_ea"):
            real.guardar_rendimiento(con, fila["id"], parse_tasa(str(c["rendimiento_ea"])), c.get("rendimiento_nota", ""))
            hecho.append(f"rendimiento de {c['nombre']}")
    ids_f = {f["nombre"]: f["id"] for f in con.execute("SELECT id, nombre FROM fondos")}
    for f in datos.get("fondos", []):
        if f["nombre"] in ids_f:
            continue
        fid = real.guardar_fondo(
            con, f["nombre"], parse_cop(str(f.get("objetivo") or "0")), f.get("fecha_objetivo") or None,
            f.get("cada_meses"), ids_b[f["bolsillo"]], bool(f.get("estimado", False)),
            aporte_mensual=parse_cop(str(f.get("aporte_mensual") or "0")),
            aporte_proximo=_opcional_cop(f.get("aporte_proximo")))
        ids_f[f["nombre"]] = fid
        if f.get("acumulado"):
            with con:
                con.execute("INSERT INTO fondo_movimientos (fondo_id, fecha, tipo, monto, nota) VALUES (?, ?, 'aporte', ?, ?)",
                            (fid, str(f.get("acumulado_fecha") or "2026-10-17"), parse_cop(str(f["acumulado"])),
                             f.get("acumulado_nota", "Saldo inicial")))
        hecho.append(f"fondo {f['nombre']}")
    existentes = {(e["nombre"], e["fecha"]) for e in con.execute("SELECT nombre, fecha FROM eventos")}
    for e in datos.get("eventos", []):
        if (e["nombre"], str(e["fecha"])) in existentes:
            continue
        real.guardar_evento(con, e["nombre"], str(e["fecha"]), e["tipo"], _opcional_cop(e.get("monto")),
                            bool(e.get("estimado", True)), ids_d[e["deuda"]]["id"] if e.get("deuda") and e["deuda"] in ids_d else None,
                            ids_f.get(e["fondo"]) if e.get("fondo") else None, "extra" if e.get("solo_extra") else "",
                            e.get("nota", ""))
        hecho.append(f"evento {e['nombre']}")
    esc = datos.get("escenario")
    if esc and not real.escenario(con)["neto_quincena"]:
        valores = {k: (parse_cop(str(v)) if k in ("neto_quincena", "gasto_basico", "tarjeta_mes", "libre",
                                                  "ahorro_mensual", "meta_m4") else v) for k, v in esc.items()}
        real.guardar_escenario(con, valores)
        hecho.append("escenario base")
    for extra in datos.get("plantilla_agregar", []):
        p = consultas.plantilla_por_nombre(con, str(extra["plantilla"]))
        if not p:
            continue
        lineas = consultas.lineas_plantilla(con, p["id"])
        if any(l.concepto == extra["concepto"] for l in lineas):
            continue
        nueva = Linea(extra["concepto"], ids_b[extra["bolsillo"]], parse_cop(str(extra["monto"])), "fijo",
                      fondo_id=ids_f.get(extra.get("fondo")) if extra.get("fondo") else None)
        i = next((k for k, l in enumerate(lineas) if l.modo == "resto"), len(lineas))
        lineas.insert(i, nueva)
        consultas.guardar_lineas_plantilla(con, p["id"], lineas)
        hecho.append(f"línea {extra['concepto']} en la plantilla del {extra['plantilla']}")
    return hecho


def main(argv: list[str]) -> int:
    cfg = leer_config()
    ruta = SEED_LOCAL if SEED_LOCAL.exists() else SEED_EJEMPLO
    if "--reiniciar" in argv and cfg.db_path.exists():
        for sufijo in ("", "-wal", "-shm"):
            Path(str(cfg.db_path) + sufijo).unlink(missing_ok=True)
    con = conectar(cfg.db_path)
    migrar(con)
    with open(ruta, "rb") as fh:
        datos = tomllib.load(fh)
    if con.execute("SELECT COUNT(*) FROM bolsillos").fetchone()[0]:
        hecho = completar(con, datos)
        if hecho:
            print("La base ya tenía datos; agregué lo que faltaba: " + ", ".join(hecho))
        else:
            print("La base ya tiene datos y no falta nada. Para empezar de cero: make backup y --reiniciar.")
        return 0
    cargar(con, datos)
    print(f"Datos cargados desde {ruta.relative_to(RAIZ)} en {cfg.db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
