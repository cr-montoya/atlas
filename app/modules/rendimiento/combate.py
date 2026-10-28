"""Patrones técnico-tácticos de las sesiones de combate registradas en la app."""

import sqlite3
from collections import Counter
from dataclasses import dataclass

from . import consultas as q


@dataclass
class Tecnica:
    nombre: str
    familia: str
    veces: int
    funciono: int
    no_funciono: int

    @property
    def con_resultado(self) -> int:
        return self.funciono + self.no_funciono

    @property
    def pct_funciono(self) -> int | None:
        return round(100 * self.funciono / self.con_resultado) if self.con_resultado else None


def patrones(con: sqlite3.Connection, desde: str, hasta: str, disciplina: str | None = None) -> dict:
    filtro = " AND s.disciplina = ?" if disciplina else ""
    params = (desde, hasta, disciplina) if disciplina else (desde, hasta)
    sesiones = con.execute("SELECT s.* FROM sesiones s WHERE s.tipo = 'combate' AND s.guardada = 1"
                           " AND s.fecha BETWEEN ? AND ?" + filtro + " ORDER BY s.fecha", params).fetchall()
    ids = [s["id"] for s in sesiones]
    tecnicas: dict[str, Tecnica] = {}
    situaciones: Counter = Counter()
    situaciones_resultado: dict[str, list[int]] = {}
    familias: Counter = Counter()
    rivales: Counter = Counter()
    bloques_min: Counter = Counter()
    if ids:
        marcas = ",".join("?" * len(ids))
        for b in con.execute(f"SELECT * FROM combate_bloques WHERE sesion_id IN ({marcas})", ids):
            bloques_min[q.TIPOS_BLOQUE[b["tipo"]]] += (b["duracion_s"] or 0) // 60
            for r in (b["rival"] or "").split(","):
                if r.strip():
                    rivales[r.strip()] += 1
        for e in con.execute(
                "SELECT ct.*, t.nombre AS tecnica, t.familia FROM combate_tecnicas ct"
                " JOIN combate_bloques b ON b.id = ct.bloque_id LEFT JOIN tecnicas t ON t.id = ct.tecnica_id"
                f" WHERE b.sesion_id IN ({marcas})", ids):
            if e["tecnica"]:
                t = tecnicas.setdefault(e["tecnica"], Tecnica(e["tecnica"], e["familia"], 0, 0, 0))
                t.veces += 1
                t.funciono += e["resultado"] == "funciono"
                t.no_funciono += e["resultado"] == "no_funciono"
                familias[e["familia"]] += 1
            if e["situacion"]:
                nombre = q.SITUACIONES[e["situacion"]]
                situaciones[nombre] += 1
                par = situaciones_resultado.setdefault(nombre, [0, 0])
                par[0] += e["resultado"] == "funciono"
                par[1] += e["resultado"] == "no_funciono"
    ranking = sorted(tecnicas.values(), key=lambda t: (-t.veces, t.nombre))
    return {
        "sesiones": len(sesiones), "minutos": sum(s["duracion_s"] or 0 for s in sesiones) // 60,
        "tecnicas": ranking, "con_resultado": [t for t in ranking if t.con_resultado],
        "situaciones": situaciones.most_common(), "situaciones_resultado": situaciones_resultado,
        "familias": familias.most_common(), "rivales": rivales.most_common(), "bloques_min": bloques_min.most_common(),
    }
