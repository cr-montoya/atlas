-- Montos: COP en pesos (INTEGER); USD en centavos (INTEGER); TRM en centavos de peso (INTEGER).
-- Fechas ISO (TEXT 'AAAA-MM-DD').

CREATE TABLE bolsillos (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    tipo    TEXT NOT NULL CHECK (tipo IN ('fijo', 'deuda', 'ahorro', 'libre')),
    orden   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE deudas (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    moneda  TEXT NOT NULL CHECK (moneda IN ('COP', 'USD')),
    saldo   INTEGER NOT NULL CHECK (saldo >= 0),
    orden   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE plantillas (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE
);

-- modo: 'fijo' (monto fijo), 'pedir' (el monto se pide al aplicar), 'resto' (neto menos las demás)
CREATE TABLE plantilla_lineas (
    id           INTEGER PRIMARY KEY,
    plantilla_id INTEGER NOT NULL REFERENCES plantillas(id) ON DELETE CASCADE,
    orden        INTEGER NOT NULL DEFAULT 0,
    concepto     TEXT NOT NULL,
    bolsillo_id  INTEGER NOT NULL REFERENCES bolsillos(id),
    modo         TEXT NOT NULL CHECK (modo IN ('fijo', 'pedir', 'resto')),
    monto        INTEGER CHECK (monto IS NULL OR monto >= 0),
    deuda_id     INTEGER REFERENCES deudas(id),
    CHECK ((modo = 'fijo') = (monto IS NOT NULL))
);
CREATE UNIQUE INDEX un_resto_por_plantilla ON plantilla_lineas(plantilla_id) WHERE modo = 'resto';

CREATE TABLE quincenas (
    id           INTEGER PRIMARY KEY,
    fecha        TEXT NOT NULL,
    neto         INTEGER NOT NULL CHECK (neto > 0),
    plantilla_id INTEGER REFERENCES plantillas(id),
    trm          INTEGER,
    creada       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE quincena_lineas (
    id           INTEGER PRIMARY KEY,
    quincena_id  INTEGER NOT NULL REFERENCES quincenas(id) ON DELETE CASCADE,
    orden        INTEGER NOT NULL DEFAULT 0,
    concepto     TEXT NOT NULL,
    bolsillo_id  INTEGER NOT NULL REFERENCES bolsillos(id),
    monto        INTEGER NOT NULL CHECK (monto >= 0),
    deuda_id     INTEGER REFERENCES deudas(id)
);

-- tipo 'abono': monto positivo en la moneda de la deuda (baja el saldo).
-- tipo 'ajuste': monto con signo = saldo nuevo menos saldo anterior.
-- trm y costo_cop solo para abonos en USD.
CREATE TABLE movimientos_deuda (
    id           INTEGER PRIMARY KEY,
    deuda_id     INTEGER NOT NULL REFERENCES deudas(id) ON DELETE CASCADE,
    fecha        TEXT NOT NULL,
    tipo         TEXT NOT NULL CHECK (tipo IN ('abono', 'ajuste')),
    monto        INTEGER NOT NULL,
    trm          INTEGER,
    costo_cop    INTEGER,
    quincena_id  INTEGER REFERENCES quincenas(id) ON DELETE SET NULL,
    nota         TEXT NOT NULL DEFAULT '',
    creado       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE cuentas (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    orden   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE fotos (
    id      INTEGER PRIMARY KEY,
    fecha   TEXT NOT NULL UNIQUE,
    trm     INTEGER NOT NULL CHECK (trm > 0)
);

CREATE TABLE foto_saldos (
    foto_id   INTEGER NOT NULL REFERENCES fotos(id) ON DELETE CASCADE,
    cuenta_id INTEGER NOT NULL REFERENCES cuentas(id),
    saldo     INTEGER NOT NULL,
    PRIMARY KEY (foto_id, cuenta_id)
);

-- Saldo de cada deuda en la fecha de la foto, en su moneda.
CREATE TABLE foto_deudas (
    foto_id  INTEGER NOT NULL REFERENCES fotos(id) ON DELETE CASCADE,
    deuda_id INTEGER NOT NULL REFERENCES deudas(id),
    saldo    INTEGER NOT NULL CHECK (saldo >= 0),
    PRIMARY KEY (foto_id, deuda_id)
);

CREATE TABLE metas (
    id       INTEGER PRIMARY KEY,
    nombre   TEXT NOT NULL UNIQUE,
    objetivo INTEGER NOT NULL CHECK (objetivo > 0),
    orden    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE meta_cuentas (
    meta_id   INTEGER NOT NULL REFERENCES metas(id) ON DELETE CASCADE,
    cuenta_id INTEGER NOT NULL REFERENCES cuentas(id),
    PRIMARY KEY (meta_id, cuenta_id)
);
