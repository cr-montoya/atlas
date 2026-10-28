"""Lectores del vault Life Brain, solo lectura, con las reglas de calidad del spec.

Lee los CSV de Polar y de salud diaria de Garmin, la tabla Markdown de actividades de Garmin,
las zonas de cardio-y-zonas.md, los CMJ de marcas-y-pruebas.md, composicion-corporal.md y los
hitos de objetivos-deportivos.md. Nunca escribe en el vault. Cada archivo se cachea por su
fecha de modificación y tamaño, así que un archivo nuevo o editado se vuelve a leer solo.
"""

import csv
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

POLAR = Path("03_Training/imports/polar")
GARMIN = Path("03_Training/imports/garmin")
ZONAS = Path("03_Training/cardio-y-zonas.md")
MARCAS = Path("03_Training/marcas-y-pruebas.md")
OBJETIVOS = Path("03_Training/objetivos-deportivos.md")
COMPOSICION = Path("04_Nutrition/composicion-corporal.md")

NOMBRES = {
    "fuerza": "Fuerza", "judo": "Judo", "bjj": "BJJ", "judo_bjj": "Judo o BJJ, sin confirmar",
    "muaythai": "Muay Thai", "caminata": "Caminata", "caminadora": "Caminadora", "carrera": "Carrera",
    "ciclismo": "Ciclismo", "cardio": "Cardio", "otro": "Otro",
}
COMBATE = {"judo", "bjj", "judo_bjj", "muaythai"}

POLAR_DEPORTES = {
    "Judo": "judo_bjj", "Kickboxing": "muaythai", "Kickbiking": "muaythai",
    "Strength training": "fuerza", "Walking": "caminata", "Running": "carrera",
    "Treadmill running": "caminadora", "Indoor cycling": "ciclismo",
    "Stair workout": "cardio", "Circuit training": "cardio",
}
GARMIN_TIPOS = {
    "Fuerza": "fuerza", "Caminata": "caminata", "Caminadora": "caminadora", "Carrera": "carrera",
    "Ciclismo": "ciclismo", "Ciclismo en interior": "ciclismo", "Cardio": "cardio",
    "Judo": "judo_bjj", "Muay Thai": "muaythai", "Kickboxing": "muaythai", "BJJ": "bjj",
}
# Etiquetas que en realidad son Muay Thai (decisión del usuario, 2026-10-17).
MUAY_THAI_ORIGINAL = {"Kickboxing", "Kickbiking"}
GENERICO_POLAR = re.compile(r"Polar Flow sport \d+")
FC_DUDOSA = 100          # lpm: FC media menor en combate = posible pérdida de señal
SOLAPE_DUPLICADO = 0.8   # fracción de la sesión más corta

AVISO_NO_ENTRENAMIENTO = "probablemente no es entrenamiento"
AVISO_FC_DUDOSA = "FC dudosa (posible pérdida de señal)"
AVISO_JUDO_BJJ = "Judo o BJJ, sin confirmar"


@dataclass(frozen=True)
class Actividad:
    fuente: str              # polar | garmin
    fecha: str               # AAAA-MM-DD
    hora: str                # HH:MM:SS
    deporte: str             # etiqueta original del dispositivo
    disciplina: str
    duracion_s: int
    distancia_m: int | None = None
    fc_media: int | None = None
    fc_max: int | None = None
    kcal: int | None = None
    nota: str = ""
    avisos: tuple[str, ...] = ()
    sugerencia: str | None = None     # para "judo_bjj": judo o bjj
    entrenamiento: bool = True
    fc_dudosa: bool = False
    tambien_en: str | None = None     # la otra fuente si estaba en los dos dispositivos
    archivo: str = ""
    zonas_s: tuple[int, ...] | None = None  # segundos en Z1..Z5 si la sincronización los trajo
    confirmada: bool = True           # False: "Judo" de Polar que se cuenta como la disciplina sugerida

    @property
    def clave(self) -> str:
        return f"{self.fuente}|{self.fecha}|{self.hora}"

    @property
    def inicio(self) -> datetime:
        return datetime.fromisoformat(f"{self.fecha}T{self.hora}")

    @property
    def fin(self) -> datetime:
        return self.inicio + timedelta(seconds=self.duracion_s)

    @property
    def nombre(self) -> str:
        return NOMBRES.get(self.disciplina, self.deporte)


@dataclass(frozen=True)
class DiaSalud:
    fecha: str
    pasos: int | None = None
    fc_reposo: int | None = None
    sueno_s: int | None = None        # la noche cuenta para el día en que termina
    sueno_puntaje: int | None = None
    hrv_ms: int | None = None
    estres: int | None = None
    bb_max: int | None = None         # Body Battery del día
    bb_min: int | None = None
    bb_cargado: int | None = None
    bb_gastado: int | None = None
    hrv_estado: str | None = None     # BALANCED | UNBALANCED | LOW | POOR (NONE queda en None)
    hrv_base_baja: int | None = None  # línea base de HRV de Garmin
    hrv_base_alta: int | None = None
    profundo_min: int | None = None   # fases de sueño
    ligero_min: int | None = None
    rem_min: int | None = None
    despierto_min: int | None = None


CAMPOS_SALUD = tuple(f for f in DiaSalud.__dataclass_fields__ if f != "fecha")
RELLENO = "relleno"   # los archivos del relleno de salud llevan esta palabra en el nombre


@dataclass(frozen=True)
class ValorVault:
    medida: str
    valor_mil: int
    unidad: str
    direccion: str            # mas | menos | neutra


@dataclass(frozen=True)
class TestVault:
    tipo: str
    fecha: str
    fecha_precision: str      # dia | mes
    fecha_aproximada: bool
    metodo: str | None
    evaluador: str | None
    valores: tuple[ValorVault, ...]
    origen: str


@dataclass(frozen=True)
class Hito:
    nombre: str
    inicio: date
    fin: date
    aproximado: bool
    texto: str


@dataclass
class Importacion:
    actividades: list[Actividad] = field(default_factory=list)
    salud: dict[str, DiaSalud] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    archivos: list[str] = field(default_factory=list)
    ultima_salud_normal: str | None = None   # sin contar los archivos del relleno

    @property
    def ultima_fecha(self) -> dict[str, str | None]:
        """Última fecha con datos por fuente, para saber desde dónde sincronizar."""
        fechas: dict[str, str | None] = {"polar": None, "garmin": None}
        for a in self.actividades:
            if fechas[a.fuente] is None or a.fecha > fechas[a.fuente]:
                fechas[a.fuente] = a.fecha
        if self.ultima_salud_normal:
            # El relleno de salud no mueve la fecha desde la que sincroniza la app
            fechas["garmin"] = max(filter(None, [fechas["garmin"], self.ultima_salud_normal]))
        return fechas


# Caché por archivo ----------------------------------------------------------

_cache: dict[tuple, object] = {}


def _cacheado(ruta: Path, lector):
    st = ruta.stat()
    clave = (str(ruta), lector.__name__)
    hit = _cache.get(clave)
    marca = (st.st_mtime_ns, st.st_size)
    if hit is None or hit[0] != marca:
        hit = (marca, lector(ruta))
        _cache[clave] = hit
    return hit[1]


def limpiar_cache() -> None:
    _cache.clear()


# Números del vault ----------------------------------------------------------

def _dec(texto: str | None) -> Decimal | None:
    """'41,3' -> 41.3; '1.384' (miles) -> 1384; '-', '', '?' -> None."""
    if texto is None:
        return None
    t = texto.strip()
    if t in ("", "-", "?", "--"):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _entero(texto: str | None) -> int | None:
    d = _dec(texto)
    return None if d is None else int(d.to_integral_value())


def _mil(d: Decimal) -> int:
    return int((d * 1000).to_integral_value())


def _zonas(textos: list, factor: int) -> tuple[int, ...] | None:
    """Cinco valores de tiempo por zona (segundos o minutos con coma); None si no hay ninguno."""
    valores = [_dec(t) for t in textos]
    if all(v is None for v in valores):
        return None
    return tuple(int(((v or Decimal(0)) * factor).to_integral_value()) for v in valores)


def _distancia_m(texto: str) -> int | None:
    m = re.fullmatch(r"\s*([\d.,]+)\s*(km|m)\s*", texto or "")
    if not m:
        return None
    n = _dec(m.group(1))
    return None if n is None else int((n * (1000 if m.group(2) == "km" else 1)).to_integral_value())


# Reglas de calidad ----------------------------------------------------------

def _reglas(a: Actividad) -> Actividad:
    avisos = list(a.avisos)
    cambios: dict = {}
    if GENERICO_POLAR.fullmatch(a.deporte):
        cambios["disciplina"] = "otro"
        hora = int(a.hora[:2])
        if (a.fc_media is not None and a.fc_media < 60) or hora < 5:
            cambios["entrenamiento"] = False
            avisos.append(AVISO_NO_ENTRENAMIENTO)
    if a.deporte in MUAY_THAI_ORIGINAL:
        avisos.append(f"etiqueta original: {a.deporte}")
    disciplina = cambios.get("disciplina", a.disciplina)
    if disciplina == "judo_bjj":
        if "bjj" in a.nota.lower():
            cambios["sugerencia"] = "bjj"
        else:
            cambios["sugerencia"] = "bjj" if date.fromisoformat(a.fecha).weekday() in (1, 3) else "judo"
        avisos.append(AVISO_JUDO_BJJ)
    if disciplina in COMBATE and a.fc_media is not None and a.fc_media < FC_DUDOSA:
        cambios["fc_dudosa"] = True
        avisos.append(AVISO_FC_DUDOSA)
    return replace(a, avisos=tuple(avisos), **cambios)


def _solape(a: Actividad, b: Actividad) -> float:
    corta = min(a.duracion_s, b.duracion_s)
    if corta <= 0:
        return 0.0
    s = (min(a.fin, b.fin) - max(a.inicio, b.inicio)).total_seconds()
    return max(s, 0) / corta


def deduplicar(actividades: list[Actividad]) -> list[Actividad]:
    """Una actividad en Garmin y en Polar que se solapan más del 80 % cuenta una vez, con la FC del H10."""
    polar = [a for a in actividades if a.fuente == "polar"]
    salida, usadas = [], set()
    for a in actividades:
        if a.fuente != "garmin":
            continue
        par = next((p for p in polar if p.fecha == a.fecha and _solape(a, p) > SOLAPE_DUPLICADO), None)
        if par is None:
            salida.append(a)
        else:
            usadas.add(par.clave)
    for p in polar:
        salida.append(replace(p, tambien_en="garmin") if p.clave in usadas else p)
    return sorted(salida, key=lambda x: (x.fecha, x.hora))


# Lectores -------------------------------------------------------------------

def leer_polar_csv(ruta: Path) -> tuple[Actividad, ...]:
    filas = []
    with ruta.open(encoding="utf-8", newline="") as fh:
        for f in csv.DictReader(fh):
            deporte = (f.get("sport_polar") or "").strip()
            if not f.get("date") or not deporte:
                continue
            a = Actividad(
                fuente="polar", fecha=f["date"].strip(), hora=f["start"].strip(), deporte=deporte,
                disciplina=POLAR_DEPORTES.get(deporte, "otro"),
                duracion_s=_entero(f.get("duration_s")) or 0,
                distancia_m=_entero(f.get("distance_m")),
                fc_media=_entero(f.get("hr_avg")), fc_max=_entero(f.get("hr_max")),
                kcal=_entero(f.get("kcal")), nota=(f.get("note") or "").strip(), archivo=ruta.name,
                zonas_s=_zonas([f.get(f"z{i}_s") for i in range(1, 6)], 1),
            )
            filas.append(_reglas(a))
    return tuple(filas)


def leer_garmin_actividades(ruta: Path) -> tuple[Actividad, ...]:
    """Tabla Markdown de actividades de Garmin; decimales con coma ("41,3" min, "2,91 km")."""
    filas = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not re.match(r"\|\s*\d{4}-\d{2}-\d{2}\s*\|", linea):
            continue
        c = [x.strip() for x in linea.strip().strip("|").split("|")]
        if len(c) < 10:
            continue
        fecha, _dia, hora, tipo, dur, _mov, dist, fcm, fcx, kcal = c[:10]
        minutos = _dec(dur) or Decimal(0)
        hora = hora if re.fullmatch(r"\d{2}:\d{2}:\d{2}", hora) else f"{hora}:00"
        a = Actividad(
            fuente="garmin", fecha=fecha, hora=hora, deporte=tipo, disciplina=GARMIN_TIPOS.get(tipo, "otro"),
            duracion_s=int((minutos * 60).to_integral_value()), distancia_m=_distancia_m(dist),
            fc_media=_entero(fcm), fc_max=_entero(fcx), kcal=_entero(kcal), archivo=ruta.name,
            zonas_s=_zonas(c[10:15], 60) if len(c) >= 15 else None,
        )
        filas.append(_reglas(a))
    return tuple(filas)


HRV_ESTADOS = {"BALANCED": "equilibrada", "UNBALANCED": "desequilibrada", "LOW": "baja", "POOR": "muy baja"}


def combinar_salud(viejo: DiaSalud | None, nuevo: DiaSalud) -> DiaSalud:
    """Por campo: el valor no vacío del archivo posterior manda; un vacío nunca borra lo que otro archivo trae."""
    if viejo is None:
        return nuevo
    return replace(viejo, **{c: getattr(nuevo, c) for c in CAMPOS_SALUD if getattr(nuevo, c) is not None})


def leer_garmin_salud(ruta: Path) -> tuple[DiaSalud, ...]:
    dias = []
    with ruta.open(encoding="utf-8", newline="") as fh:
        for f in csv.DictReader(fh):
            if not f.get("day"):
                continue
            horas = _dec(f.get("sleep_h"))
            hrv = _entero(f.get("hrv_ms"))
            estado = (f.get("hrv_status") or "").strip().upper()
            # Las columnas nuevas pueden faltar (archivos viejos): f.get da None y queda sin dato, nunca 0
            dias.append(DiaSalud(
                fecha=f["day"].strip(), pasos=_entero(f.get("steps")), fc_reposo=_entero(f.get("resting_hr")),
                sueno_s=None if not horas else int((horas * 3600).to_integral_value()),
                sueno_puntaje=_entero(f.get("sleep_score")), hrv_ms=hrv or None, estres=_entero(f.get("stress_avg")),
                bb_max=_entero(f.get("body_battery_high")), bb_min=_entero(f.get("body_battery_low")),
                bb_cargado=_entero(f.get("body_battery_charged")), bb_gastado=_entero(f.get("body_battery_drained")),
                hrv_estado=estado if estado in HRV_ESTADOS else None,
                hrv_base_baja=_entero(f.get("hrv_baseline_low")), hrv_base_alta=_entero(f.get("hrv_baseline_high")),
                profundo_min=_entero(f.get("deep_min")), ligero_min=_entero(f.get("light_min")),
                rem_min=_entero(f.get("rem_min")), despierto_min=_entero(f.get("awake_min")),
            ))
    return tuple(dias)


def leer_zonas(ruta: Path) -> tuple[tuple[int, int, int], ...]:
    """Zonas de FC configuradas en Polar: ((1, 97, 117), (2, 117, 136), ...)."""
    texto = ruta.read_text(encoding="utf-8")
    m = re.search(r"Zonas de FC configuradas en Polar[^:\n]*:([^\n]*)", texto)
    if not m:
        return ()
    return tuple((int(z), int(a), int(b)) for z, a, b in re.findall(r"Z(\d)\s+(\d+)\s*-\s*(\d+)", m.group(1)))


def _fecha_vault(texto: str) -> tuple[str, str, bool] | None:
    """'~2025-01 (...)' -> ('2025-01-01', 'mes', True); '2026-08-18' -> ('2026-08-18', 'dia', False)."""
    m = re.search(r"(~)?\s*(\d{4})-(\d{2})(?:-(\d{2}))?", texto)
    if not m:
        return None
    aprox, a, mes, dia = m.groups()
    if dia:
        return f"{a}-{mes}-{dia}", "dia", bool(aprox)
    return f"{a}-{mes}-01", "mes", bool(aprox)


def _tabla(texto: str, despues_de: str) -> list[list[str]]:
    """Filas de la primera tabla Markdown que aparece después del encabezado o texto dado."""
    i = texto.find(despues_de)
    if i < 0:
        return []
    filas, dentro = [], False
    for linea in texto[i:].splitlines()[1:]:
        if linea.startswith("|"):
            dentro = True
            c = [x.strip() for x in linea.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", x) for x in c):
                continue
            filas.append(c)
        elif dentro:
            break
    return filas[1:] if filas else []


def leer_cmj(ruta: Path) -> tuple[TestVault, ...]:
    tests = []
    for fila in _tabla(ruta.read_text(encoding="utf-8"), "## Salto (CMJ)"):
        if len(fila) < 3 or "CMJ" not in fila[1]:
            continue
        f = _fecha_vault(fila[0])
        m = re.search(r"([\d.,]+)\s*cm", fila[2])
        if not f or not m:
            continue
        tests.append(TestVault(
            tipo="cmj", fecha=f[0], fecha_precision=f[1], fecha_aproximada=f[2], metodo=None,
            evaluador=fila[3] if len(fila) > 3 else None,
            valores=(ValorVault("CMJ", _mil(_dec(m.group(1))), "cm", "mas"),), origen=ruta.name,
        ))
    return tuple(tests)


PERIMETROS_DIRECCION = {"Cintura": "neutra", "Cadera": "neutra"}  # depende de la meta: sin rojo ni verde


def _metodo_composicion(texto: str) -> str:
    if "Yuhasz" in texto:
        return "Antropometría, Yuhasz (Centro Uno)"
    if "D04" in texto:
        return "Documento nutricional D04"
    return texto


def leer_composicion(ruta: Path) -> tuple[TestVault, ...]:
    """Peso y % graso por fecha y método; la antropometría completa del informe con pliegues y perímetros.

    Solo se toman filas con fecha exacta y peso y % graso numéricos: los pesos de referencia
    ("85-86 kg") o dichos de palabra no son tests.
    """
    texto = ruta.read_text(encoding="utf-8")
    tests = []
    for fila in _tabla(texto, "## Peso y composición"):
        if len(fila) < 6:
            continue
        f = _fecha_vault(fila[0])
        peso = re.fullmatch(r"([\d.,]+)\s*kg", fila[1])
        graso = re.match(r"([\d.,]+)\s*%", fila[3])
        if not f or f[1] != "dia" or not peso or not graso:
            continue
        valores = [ValorVault("Peso", _mil(_dec(peso.group(1))), "kg", "neutra"),
                   ValorVault("% graso", _mil(_dec(graso.group(1))), "%", "menos")]
        musc = re.search(r"Masa muscular[^(]*\(([\d.,]+)\s*kg\)", fila[4])
        if musc:
            valores.append(ValorVault("Masa muscular", _mil(_dec(musc.group(1))), "kg", "mas"))
        metodo = _metodo_composicion(fila[5])
        if f[0] in texto and f"## Antropometría del {f[0]}" in texto:
            valores += _antropometria(texto, f[0])
        tests.append(TestVault(
            tipo="antropometria", fecha=f[0], fecha_precision="dia", fecha_aproximada=False, metodo=metodo,
            evaluador="Centro Uno" if "Centro Uno" in fila[5] else None, valores=tuple(valores), origen=ruta.name,
        ))
    return tuple(tests)


def _antropometria(texto: str, fecha: str) -> list[ValorVault]:
    seccion = texto[texto.find(f"## Antropometría del {fecha}"):]
    fin = seccion.find("\n## ", 3)
    seccion = seccion if fin < 0 else seccion[:fin]
    valores = []
    for n, nombre in ((6, "Suma 6 pliegues"), (8, "Suma 8 pliegues")):
        m = re.search(rf"suma {n} pliegues\s*([\d.,]+)\s*mm", seccion, re.I)
        if m:
            valores.append(ValorVault(nombre, _mil(_dec(m.group(1))), "mm", "menos"))
    for sitio, mm in _tabla(seccion, "Pliegues:"):
        d = _dec(mm)
        if d is not None:
            valores.append(ValorVault(f"Pliegue {sitio.lower()}", _mil(d), "mm", "menos"))
    for medida, cm in _tabla(seccion, "Perímetros:"):
        d = _dec(cm)
        if d is not None:
            valores.append(ValorVault(f"Perímetro {medida.lower()}", _mil(d), "cm",
                                      PERIMETROS_DIRECCION.get(medida, "mas")))
    return valores


def leer_hitos(ruta: Path) -> tuple[Hito, ...]:
    texto = ruta.read_text(encoding="utf-8")
    hitos = []
    m = re.search(r"viaje a ([^:\n]+?):\s*(\d{4}-\d{2}-\d{2})\s*a\s*(\d{4}-\d{2}-\d{2})", texto, re.I)
    if m:
        hitos.append(Hito(f"Viaje a {m.group(1).strip()}", date.fromisoformat(m.group(2)), date.fromisoformat(m.group(3)),
                          False, f"del {m.group(2)} al {m.group(3)}"))
    m = re.search(r"cirug[ií]a[^\n]*?Q([1-4])\s*(\d{4})", texto, re.I)
    if m:
        q, a = int(m.group(1)), int(m.group(2))
        ini = date(a, 3 * q - 2, 1)
        fin = (date(a + (q == 4), (3 * q) % 12 + 1, 1)) - timedelta(days=1)
        nombres = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto"}
        hitos.append(Hito("Cirugía", ini, fin, True, f"{nombres[q]} trimestre de {a}"))
    return tuple(hitos)


def leer_meta_pasos(ruta: Path) -> int | None:
    m = re.search(r"mínimo\s+([\d.]+)\s+pasos", ruta.read_text(encoding="utf-8"))
    return _entero(m.group(1)) if m else None


# Punto de entrada -----------------------------------------------------------

def importar(vault: Path) -> Importacion:
    """Lee todas las actividades y la salud diaria, con reglas, duplicados y avisos."""
    imp = Importacion()
    if not vault.is_dir():
        imp.avisos.append(f"No encontré el vault en {vault}.")
        return imp
    crudas: dict[str, Actividad] = {}
    for ruta in sorted((vault / POLAR).glob("*.csv")):
        imp.archivos.append(str(ruta.relative_to(vault)))
        for a in _cacheado(ruta, leer_polar_csv):
            crudas.setdefault(a.clave, a)
    for ruta in sorted((vault / GARMIN).glob("*actividades*.md")):
        imp.archivos.append(str(ruta.relative_to(vault)))
        for a in _cacheado(ruta, leer_garmin_actividades):
            crudas.setdefault(a.clave, a)
    for ruta in sorted((vault / GARMIN).glob("*salud*.csv")):
        imp.archivos.append(str(ruta.relative_to(vault)))
        normal = RELLENO not in ruta.name
        for d in _cacheado(ruta, leer_garmin_salud):
            imp.salud[d.fecha] = combinar_salud(imp.salud.get(d.fecha), d)  # orden por nombre, campo por campo
            if normal and (imp.ultima_salud_normal is None or d.fecha > imp.ultima_salud_normal):
                imp.ultima_salud_normal = d.fecha
    imp.actividades = deduplicar(list(crudas.values()))

    polar = [a for a in imp.actividades if a.fuente == "polar"]
    if polar:
        fuera = sum(1 for a in polar if not a.entrenamiento)
        texto = f"Polar: {len(polar) - fuera} sesiones de entrenamiento"
        if fuera:
            texto += f" ({fuera} probablemente no {'es' if fuera == 1 else 'son'} entrenamiento)"
        imp.avisos.append(texto + ".")
    garmin = [a for a in imp.actividades if a.fuente == "garmin"]
    if garmin:
        imp.avisos.append(f"Garmin: {len(garmin)} actividades y {len(imp.salud)} días de salud.")
    dobles = sum(1 for a in imp.actividades if a.tambien_en)
    if dobles:
        imp.avisos.append(f"{dobles} actividades estaban en los dos dispositivos; cuentan una vez con la FC del H10.")
    return imp


def zonas(vault: Path) -> tuple[tuple[int, int, int], ...]:
    ruta = vault / ZONAS
    return _cacheado(ruta, leer_zonas) if ruta.exists() else ()


def tests(vault: Path) -> tuple[TestVault, ...]:
    salida: list[TestVault] = []
    for rel, lector in ((MARCAS, leer_cmj), (COMPOSICION, leer_composicion)):
        ruta = vault / rel
        if ruta.exists():
            salida += _cacheado(ruta, lector)
    return tuple(sorted(salida, key=lambda t: (t.fecha, t.tipo)))


def hitos(vault: Path) -> tuple[Hito, ...]:
    ruta = vault / OBJETIVOS
    return _cacheado(ruta, leer_hitos) if ruta.exists() else ()


def meta_pasos(vault: Path) -> int | None:
    ruta = vault / OBJETIVOS
    return _cacheado(ruta, leer_meta_pasos) if ruta.exists() else None


def zona_de(fc: int | None, tabla: tuple[tuple[int, int, int], ...]) -> int | None:
    """Zona de una FC media: 0 si está por debajo de Z1; la última si supera el máximo."""
    if fc is None or not tabla:
        return None
    if fc < tabla[0][1]:
        return 0
    for z, _a, b in tabla:
        if fc < b:
            return z
    return tabla[-1][0]
