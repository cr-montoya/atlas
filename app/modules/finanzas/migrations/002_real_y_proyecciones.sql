-- v2: plan vs real, ingresos extra, fondos de previsión, proyección, revisión.
-- Tasas en partes por millón (1 % = 10.000; 2,1285 % = 21.285) para no usar float.

ALTER TABLE quincenas ADD COLUMN tipo TEXT NOT NULL DEFAULT 'quincena'
    CHECK (tipo IN ('quincena', 'extra', 'prima', 'intereses_cesantias', 'cesantias', 'otro'));

ALTER TABLE deudas ADD COLUMN tasa_mensual_ppm INTEGER CHECK (tasa_mensual_ppm IS NULL OR tasa_mensual_ppm >= 0);
ALTER TABLE deudas ADD COLUMN cuota_mensual INTEGER NOT NULL DEFAULT 0 CHECK (cuota_mensual >= 0);

CREATE TABLE fondos (
    id              INTEGER PRIMARY KEY,
    nombre          TEXT NOT NULL UNIQUE,
    objetivo        INTEGER NOT NULL DEFAULT 0 CHECK (objetivo >= 0),
    fecha_objetivo  TEXT,
    cada_meses      INTEGER CHECK (cada_meses IS NULL OR cada_meses > 0),
    bolsillo_id     INTEGER NOT NULL REFERENCES bolsillos(id),
    estimado        INTEGER NOT NULL DEFAULT 0 CHECK (estimado IN (0, 1)),
    -- aporte_mensual > 0: fondo de aporte fijo (por ejemplo la natillera). No se provisiona solo:
    -- lo alimenta una línea de plantilla vinculada, y en su fecha devuelve lo acumulado.
    aporte_mensual  INTEGER NOT NULL DEFAULT 0 CHECK (aporte_mensual >= 0),
    aporte_proximo  INTEGER CHECK (aporte_proximo IS NULL OR aporte_proximo >= 0),  -- desde el ciclo siguiente
    orden           INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE quincena_lineas ADD COLUMN fondo_id INTEGER REFERENCES fondos(id);
ALTER TABLE plantilla_lineas ADD COLUMN fondo_id INTEGER REFERENCES fondos(id);

-- tipo 'aporte' suma, 'uso' resta; monto siempre positivo.
CREATE TABLE fondo_movimientos (
    id          INTEGER PRIMARY KEY,
    fondo_id    INTEGER NOT NULL REFERENCES fondos(id) ON DELETE CASCADE,
    fecha       TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('aporte', 'uso')),
    monto       INTEGER NOT NULL CHECK (monto > 0),
    quincena_id INTEGER REFERENCES quincenas(id) ON DELETE SET NULL,
    nota        TEXT NOT NULL DEFAULT ''
);

-- Pago real de una línea (uno por línea).
CREATE TABLE pagos (
    linea_id INTEGER PRIMARY KEY REFERENCES quincena_lineas(id) ON DELETE CASCADE,
    fecha    TEXT NOT NULL,
    monto    INTEGER NOT NULL CHECK (monto >= 0)
);

CREATE TABLE categorias (
    id     INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    orden  INTEGER NOT NULL DEFAULT 0
);
INSERT INTO categorias (nombre, orden) VALUES
    ('comida', 1), ('transporte', 2), ('salud', 3), ('casa', 4), ('regalos', 5), ('ocio', 6), ('otro', 7);

CREATE TABLE gastos (
    id           INTEGER PRIMARY KEY,
    fecha        TEXT NOT NULL,
    monto        INTEGER NOT NULL CHECK (monto > 0),
    bolsillo_id  INTEGER NOT NULL REFERENCES bolsillos(id),
    categoria_id INTEGER REFERENCES categorias(id),
    nota         TEXT NOT NULL DEFAULT '',
    creado       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Eventos futuros conocidos. monto NULL = sin dato (no entra a la proyección, se avisa).
CREATE TABLE eventos (
    id        INTEGER PRIMARY KEY,
    nombre    TEXT NOT NULL,
    fecha     TEXT NOT NULL,
    tipo      TEXT NOT NULL CHECK (tipo IN ('ingreso', 'gasto')),
    monto     INTEGER CHECK (monto IS NULL OR monto >= 0),
    estimado  INTEGER NOT NULL DEFAULT 1 CHECK (estimado IN (0, 1)),
    deuda_id  INTEGER REFERENCES deudas(id) ON DELETE SET NULL,
    fondo_id  INTEGER REFERENCES fondos(id) ON DELETE SET NULL,
    escenario TEXT NOT NULL DEFAULT '' CHECK (escenario IN ('', 'extra')),
    nota      TEXT NOT NULL DEFAULT ''
);

-- Escenario base de la proyección (una fila).
CREATE TABLE escenario (
    id                   INTEGER PRIMARY KEY CHECK (id = 1),
    neto_quincena        INTEGER NOT NULL DEFAULT 0,
    gasto_basico         INTEGER NOT NULL DEFAULT 0,
    tarjeta_mes            INTEGER NOT NULL DEFAULT 1000000,
    libre                INTEGER NOT NULL DEFAULT 0,
    ahorro_mensual       INTEGER NOT NULL DEFAULT 0,
    incluir_extra        INTEGER NOT NULL DEFAULT 1 CHECK (incluir_extra IN (0, 1)),
    estrategia           TEXT NOT NULL DEFAULT 'avalancha' CHECK (estrategia IN ('avalancha', 'bola')),
    meses                INTEGER NOT NULL DEFAULT 24 CHECK (meses IN (12, 24)),
    meta_m4              INTEGER NOT NULL DEFAULT 0,
    incapacidad_activa   INTEGER NOT NULL DEFAULT 0 CHECK (incapacidad_activa IN (0, 1)),
    incapacidad_inicio   TEXT NOT NULL DEFAULT '',
    incapacidad_meses    INTEGER NOT NULL DEFAULT 1,
    incapacidad_pct_ppm  INTEGER NOT NULL DEFAULT 666700
);
INSERT INTO escenario (id) VALUES (1);

CREATE TABLE revisiones (
    mes         TEXT PRIMARY KEY,
    distinto    TEXT NOT NULL DEFAULT '',
    inesperado  TEXT NOT NULL DEFAULT '',
    ajustar     TEXT NOT NULL DEFAULT '',
    plantillas  TEXT NOT NULL DEFAULT '',
    sensacion   INTEGER CHECK (sensacion IS NULL OR sensacion BETWEEN 1 AND 5),
    actualizada TEXT NOT NULL DEFAULT (datetime('now'))
);
