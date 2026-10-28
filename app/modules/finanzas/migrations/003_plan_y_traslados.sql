-- Plan del Life Brain: el sobrante solo prepaga las deudas marcadas (la tarjeta); lo demás va a ahorro.
-- Eventos de tipo 'traslado': plata del mes que se guarda en un fondo (no cambia el patrimonio).

ALTER TABLE deudas ADD COLUMN prepagar INTEGER NOT NULL DEFAULT 1 CHECK (prepagar IN (0, 1));
ALTER TABLE escenario ADD COLUMN sobrante_a_ahorro INTEGER NOT NULL DEFAULT 1 CHECK (sobrante_a_ahorro IN (0, 1));

CREATE TABLE eventos_nueva (
    id        INTEGER PRIMARY KEY,
    nombre    TEXT NOT NULL,
    fecha     TEXT NOT NULL,
    tipo      TEXT NOT NULL CHECK (tipo IN ('ingreso', 'gasto', 'traslado')),
    monto     INTEGER CHECK (monto IS NULL OR monto >= 0),
    estimado  INTEGER NOT NULL DEFAULT 1 CHECK (estimado IN (0, 1)),
    deuda_id  INTEGER REFERENCES deudas(id) ON DELETE SET NULL,
    fondo_id  INTEGER REFERENCES fondos(id) ON DELETE SET NULL,
    escenario TEXT NOT NULL DEFAULT '' CHECK (escenario IN ('', 'extra')),
    nota      TEXT NOT NULL DEFAULT ''
);
INSERT INTO eventos_nueva SELECT id, nombre, fecha, tipo, monto, estimado, deuda_id, fondo_id, escenario, nota FROM eventos;
DROP TABLE eventos;
ALTER TABLE eventos_nueva RENAME TO eventos;
