"""Fondos de previsión, orden de pago de deudas y proyección mes a mes. Funciones puras, en enteros."""

import calendar
from dataclasses import dataclass, field
from datetime import date

from app.core.dinero import div_redondeo

from .logica import dias_pago_del_mes, proximo_dia_pago

PPM = 1_000_000  # tasas en partes por millón: 1 % = 10.000


def interes(saldo: int, tasa_ppm: int | None) -> int:
    if not tasa_ppm or saldo <= 0:
        return 0
    return div_redondeo(saldo * tasa_ppm, PPM)


def sumar_meses(d: date, meses: int) -> date:
    total = d.year * 12 + d.month - 1 + meses
    anio, mes = divmod(total, 12)
    mes += 1
    return date(anio, mes, min(d.day, calendar.monthrange(anio, mes)[1]))


def mes_clave(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


# ---------- Fondos de previsión ----------

def quincenas_hasta(desde: date, hasta: date) -> int:
    """Días de pago d con desde <= d <= hasta."""
    n, d = 0, proximo_dia_pago(desde)
    while d <= hasta:
        n += 1
        d = proximo_dia_pago(d, incluir_hoy=False)
    return n


@dataclass
class EstadoFondo:
    objetivo: int
    acumulado: int
    fecha_objetivo: date | None

    @property
    def falta(self) -> int:
        return max(0, self.objetivo - self.acumulado)

    @property
    def problema(self) -> str:
        if self.objetivo <= 0:
            return "falta el monto"
        if self.fecha_objetivo is None:
            return "falta la fecha"
        return ""

    def quincenas(self, desde: date) -> int:
        if self.fecha_objetivo is None:
            return 0
        return quincenas_hasta(desde, self.fecha_objetivo)

    def provision(self, desde: date) -> int:
        """Lo que falta entre las quincenas que quedan (incluida la fecha), hacia arriba.
        Si la fecha ya pasó, todo lo que falta va en esta quincena."""
        if self.problema or self.falta == 0:
            return 0
        n = self.quincenas(desde)
        return self.falta if n <= 0 else -(-self.falta // n)


# ---------- Deudas: avalancha y bola de nieve ----------

@dataclass
class DeudaSim:
    nombre: str
    saldo: int  # en COP
    tasa_ppm: int | None = None
    cuota: int = 0
    intereses: int = 0
    mes_cero: int | None = None
    prepagar: bool = True  # False: solo cuota y abonos directos (Educa en el plan)


def orden_pago(deudas: list[DeudaSim], estrategia: str) -> list[DeudaSim]:
    vivas = [d for d in deudas if d.saldo > 0]
    if estrategia == "bola":
        return sorted(vivas, key=lambda d: (d.saldo, d.nombre))
    return sorted(vivas, key=lambda d: (-(d.tasa_ppm or 0), d.saldo, d.nombre))


def mes_de_deudas(deudas: list[DeudaSim], disponible: int, estrategia: str, mes: int,
                  solo_prepagables: bool = False) -> tuple[int, dict[str, int]]:
    """Un mes: interés sobre el saldo inicial, cuotas mínimas y luego el resto según la estrategia.
    Con solo_prepagables, el sobrante solo va a las deudas marcadas para prepagar.
    Devuelve lo que sobró del disponible y lo abonado a cada deuda."""
    abonos: dict[str, int] = {}
    for d in deudas:
        if d.saldo > 0:
            i = interes(d.saldo, d.tasa_ppm)
            d.saldo += i
            d.intereses += i
    for d in deudas:
        if d.saldo > 0 and d.cuota > 0:
            p = min(d.cuota, d.saldo, max(disponible, 0))
            d.saldo -= p
            disponible -= p
            abonos[d.nombre] = abonos.get(d.nombre, 0) + p
    for d in orden_pago([d for d in deudas if d.prepagar or not solo_prepagables], estrategia):
        if disponible <= 0:
            break
        p = min(disponible, d.saldo)
        d.saldo -= p
        disponible -= p
        abonos[d.nombre] = abonos.get(d.nombre, 0) + p
    for d in deudas:
        if d.saldo == 0 and d.mes_cero is None:
            d.mes_cero = mes
    return disponible, abonos


@dataclass
class Comparacion:
    estrategia: str
    meses_cero: dict[str, int | None]
    mes_libre: int | None
    intereses: int
    orden: list[str]


def comparar_estrategia(deudas: list[DeudaSim], pago_mensual: int, estrategia: str, tope: int = 600) -> Comparacion:
    ds = [DeudaSim(d.nombre, d.saldo, d.tasa_ppm, d.cuota) for d in deudas]
    orden = [d.nombre for d in orden_pago(ds, estrategia)]
    mes = 0
    while any(d.saldo > 0 for d in ds) and mes < tope:
        mes += 1
        mes_de_deudas(ds, pago_mensual, estrategia, mes)
    libre = mes if not any(d.saldo > 0 for d in ds) else None
    return Comparacion(estrategia, {d.nombre: d.mes_cero for d in ds}, libre, sum(d.intereses for d in ds), orden)


# ---------- Proyección ----------

@dataclass
class FondoSim:
    nombre: str
    objetivo: int
    acumulado: int
    fecha_objetivo: date | None
    cada_meses: int | None = None
    aporte_mensual: int = 0  # > 0: aporte fijo (natillera); devuelve lo acumulado en su fecha
    aporte_proximo: int | None = None  # aporte desde el ciclo siguiente a la devolución


@dataclass
class EventoSim:
    nombre: str
    fecha: date
    tipo: str  # ingreso | gasto
    monto: int | None
    estimado: bool = True
    deuda: str | None = None
    fondo: str | None = None


@dataclass
class Entrada:
    hoy: date
    meses: int
    neto_quincena: int
    gasto_basico: int      # mensual; incluye las cuotas mínimas de las deudas
    tarjeta_mes: int         # mensual
    libre: int             # gasto libre mensual estimado
    ahorro_mensual: int    # va al fondo de emergencia antes que a las deudas
    estrategia: str
    deudas: list[DeudaSim]
    fondos: list[FondoSim]
    eventos: list[EventoSim]
    emergencia: int        # saldo inicial del fondo de emergencia
    otros_activos: int     # resto de cuentas de la última foto
    meta1: int = 0
    meta_m4: int = 0
    incapacidad: tuple[str, int, int] | None = None  # (AAAA-MM inicio, meses, ppm del ingreso)
    sobrante_a_ahorro: bool = False  # plan: el sobrante solo prepaga deudas marcadas; el resto, a ahorro
    rend_emergencia_ppm: int = 0  # rendimiento mensual del fondo de emergencia (cuentas de la meta 1)
    rend_otros_ppm: int = 0       # rendimiento mensual de las demás cuentas
    retencion_ppm: int = 0        # retención en la fuente sobre el rendimiento (7 % = 70.000)
    tope_emergencia: int = 0      # > 0: el fondo de emergencia no pasa de aquí; el exceso va a inversión
    rend_inversion_ppm: int = 0   # rendimiento mensual esperado de la inversión de largo plazo (variable)
    inversion: int = 0            # saldo inicial de la inversión de largo plazo


@dataclass
class Mes:
    clave: str
    ingreso: int
    gasto: int
    abonos: dict[str, int]
    saldos: dict[str, int]
    deuda_total: int
    emergencia: int
    fondos: int
    patrimonio: int
    meses_colchon_decimas: int
    eventos: list[str] = field(default_factory=list)
    rendimiento: int = 0
    inversion: int = 0


@dataclass
class Proyeccion:
    meses: list[Mes]
    fecha_cero: dict[str, str | None]
    mes_libre: str | None
    intereses: int
    avisos: list[str]
    mes_meta1: str | None
    mes_m4: str | None
    rendimientos: int = 0
    mes_inicio_inversion: str | None = None


def _meses_incapacidad(inc: tuple[str, int, int] | None) -> dict[str, int]:
    if not inc or not inc[0]:
        return {}
    anio, mes = int(inc[0][:4]), int(inc[0][5:7])
    inicio = date(anio, mes, 1)
    return {mes_clave(sumar_meses(inicio, k)): inc[2] for k in range(inc[1])}


def proyectar(e: Entrada) -> Proyeccion:
    deudas = [DeudaSim(d.nombre, d.saldo, d.tasa_ppm, d.cuota, prepagar=d.prepagar) for d in e.deudas]
    fondos = [FondoSim(f.nombre, f.objetivo, f.acumulado, f.fecha_objetivo, f.cada_meses, f.aporte_mensual, f.aporte_proximo)
              for f in e.fondos]
    avisos = []
    for d in deudas:
        if d.saldo > 0 and not d.tasa_ppm:
            avisos.append(f"{d.nombre} sin tasa: la fecha de cero puede ser optimista.")
    for ev in e.eventos:
        if ev.monto is None:
            avisos.append(f"{ev.nombre} sin monto: no entra en la proyección.")
    cuotas = sum(d.cuota for d in deudas if d.saldo > 0)
    gasto_sin_cuotas = max(0, e.gasto_basico - cuotas)
    incap = _meses_incapacidad(e.incapacidad)
    emergencia, otros, inversion = e.emergencia, e.otros_activos, e.inversion
    inicio_inversion = None
    salida: list[Mes] = []
    base = date(e.hoy.year, e.hoy.month, 1)
    for k in range(e.meses):
        inicio_mes = sumar_meses(base, k)
        clave = mes_clave(inicio_mes)
        pagos = [d for d in dias_pago_del_mes(inicio_mes.year, inicio_mes.month) if d >= e.hoy]
        factor = incap.get(clave, PPM)
        ingreso = div_redondeo(e.neto_quincena * len(pagos) * factor, PPM)
        gasto = gasto_sin_cuotas + e.tarjeta_mes + e.libre if pagos else 0
        if k == 0 and pagos:
            gasto = div_redondeo(gasto * len(pagos), 2)  # mes en curso: solo lo que falta
        nombres_eventos = []
        directos: dict[str, int] = {}
        # Provisión de fondos por cada quincena del mes, y usos en su fecha.
        provision = 0
        for f in fondos:
            if f.aporte_mensual:
                # Aporte fijo el día de pago del 30 (también el mes de la devolución); en su fecha
                # devuelve todo como ingreso y desde el mes siguiente aplica el aporte del nuevo ciclo.
                if pagos and pagos[-1].day >= 28:
                    f.acumulado += f.aporte_mensual
                    provision += f.aporte_mensual
                if f.fecha_objetivo and mes_clave(f.fecha_objetivo) == clave:
                    ingreso += f.acumulado
                    nombres_eventos.append(f"Devolución {f.nombre}")
                    f.acumulado = 0
                    f.fecha_objetivo = sumar_meses(f.fecha_objetivo, f.cada_meses) if f.cada_meses else None
                    if f.aporte_proximo is not None:
                        f.aporte_mensual = f.aporte_proximo
                continue
            for p in pagos:
                est = EstadoFondo(f.objetivo, f.acumulado, f.fecha_objetivo)
                aporte = est.provision(p)
                f.acumulado += aporte
                provision += aporte
            if f.fecha_objetivo and f.fecha_objetivo.year == inicio_mes.year and f.fecha_objetivo.month == inicio_mes.month and f.objetivo > 0:
                usado = min(f.acumulado, f.objetivo)
                gasto += f.objetivo
                f.acumulado -= usado
                nombres_eventos.append(f"Uso {f.nombre}")
                if f.cada_meses:
                    f.fecha_objetivo = sumar_meses(f.fecha_objetivo, f.cada_meses)
                else:
                    f.objetivo = 0
                gasto -= usado  # lo provisionado ya salió de la quincena
        for ev in e.eventos:
            if ev.monto is None or mes_clave(ev.fecha) != clave:
                continue
            nombres_eventos.append(ev.nombre + (" (estimado)" if ev.estimado else ""))
            if ev.tipo == "ingreso":
                if ev.deuda:
                    directos[ev.deuda] = directos.get(ev.deuda, 0) + ev.monto
                elif ev.fondo:
                    for f in fondos:
                        if f.nombre == ev.fondo:
                            f.acumulado += ev.monto
                else:
                    ingreso += ev.monto
            elif ev.tipo == "traslado":
                # Plata del mes que se guarda en un fondo: sale del disponible y queda en el fondo.
                for f in fondos:
                    if f.nombre == ev.fondo:
                        f.acumulado += ev.monto
                        provision += ev.monto
            else:
                usado = 0
                if ev.fondo:
                    for f in fondos:
                        if f.nombre == ev.fondo:
                            usado = min(f.acumulado, ev.monto)
                            f.acumulado -= usado
                gasto += ev.monto - usado
        # Ingresos con destino a una deuda: abono directo (antes del interés del mes siguiente).
        abonos_dir: dict[str, int] = {}
        for d in deudas:
            if d.nombre in directos and d.saldo > 0:
                p = min(directos[d.nombre], d.saldo)
                d.saldo -= p
                abonos_dir[d.nombre] = p
                ingreso += directos[d.nombre] - p  # lo que sobra queda como ingreso
        disponible = ingreso - gasto - provision - e.ahorro_mensual
        emergencia += e.ahorro_mensual
        if disponible < 0:
            emergencia += disponible  # el faltante sale del colchón
            disponible = 0
        sobrante, abonos = mes_de_deudas(deudas, disponible, e.estrategia, k + 1, e.sobrante_a_ahorro)
        for n, v in abonos_dir.items():
            abonos[n] = abonos.get(n, 0) + v
        emergencia += sobrante
        # Rendimiento una vez al mes, sobre el saldo al cierre; el mes en curso solo por los días que faltan.
        # Se acredita neto de la retención en la fuente.
        r_em, r_ot = interes(emergencia, e.rend_emergencia_ppm), interes(otros, e.rend_otros_ppm)
        if k == 0:
            dias_mes = calendar.monthrange(inicio_mes.year, inicio_mes.month)[1]
            restantes = dias_mes - e.hoy.day + 1
            r_em, r_ot = div_redondeo(r_em * restantes, dias_mes), div_redondeo(r_ot * restantes, dias_mes)
        r_em -= div_redondeo(r_em * e.retencion_ppm, PPM)
        r_ot -= div_redondeo(r_ot * e.retencion_ppm, PPM)
        emergencia += r_em
        otros += r_ot
        rendimiento = r_em + r_ot
        # Inversión de largo plazo: crece con su rendimiento esperado (sin retención; variable).
        r_inv = interes(inversion, e.rend_inversion_ppm)
        inversion += r_inv
        rendimiento += r_inv
        # Con el tope (M4) cumplido, el exceso del fondo de emergencia pasa a la inversión.
        if e.tope_emergencia and emergencia > e.tope_emergencia:
            inversion += emergencia - e.tope_emergencia
            emergencia = e.tope_emergencia
            inicio_inversion = inicio_inversion or clave
        deuda_total = sum(d.saldo for d in deudas)
        en_fondos = sum(f.acumulado for f in fondos)
        salida.append(Mes(
            clave=clave, ingreso=ingreso, gasto=gasto + provision, abonos=abonos,
            saldos={d.nombre: d.saldo for d in deudas}, deuda_total=deuda_total,
            emergencia=emergencia, fondos=en_fondos,
            patrimonio=emergencia + otros + en_fondos + inversion - deuda_total,
            meses_colchon_decimas=div_redondeo(emergencia * 10, e.gasto_basico) if e.gasto_basico > 0 else 0,
            eventos=nombres_eventos, rendimiento=rendimiento, inversion=inversion,
        ))
    mes_por_indice = {i + 1: m.clave for i, m in enumerate(salida)}
    fecha_cero = {d.nombre: (mes_por_indice.get(d.mes_cero) if d.mes_cero else None) for d in deudas}
    for d in e.deudas:
        if d.saldo <= 0:
            fecha_cero[d.nombre] = mes_clave(e.hoy)
    libre = None
    if all(v for v in fecha_cero.values()):
        libre = max(fecha_cero.values()) if fecha_cero else mes_clave(e.hoy)
    m1 = next((m.clave for m in salida if e.meta1 and m.emergencia >= e.meta1), None)
    m4 = next((m.clave for m in salida if e.meta_m4 and m.emergencia >= e.meta_m4), None)
    if inicio_inversion and e.rend_inversion_ppm:
        avisos.append("Inversión largo plazo: el rendimiento esperado es variable y sin garantía.")
    return Proyeccion(salida, fecha_cero, libre, sum(d.intereses for d in deudas), avisos, m1, m4,
                      sum(m.rendimiento for m in salida), inicio_inversion)
