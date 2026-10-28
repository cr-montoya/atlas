-- Registro por voz: un relato con sus rondas (texto transcrito o escrito), el borrador y lo que se guardó.
-- El audio nunca se guarda. Descartar borra la fila.
CREATE TABLE voz_entradas (
    id INTEGER PRIMARY KEY,
    estado TEXT NOT NULL DEFAULT 'transcribiendo'
        CHECK (estado IN ('transcribiendo', 'interpretando', 'borrador', 'guardada', 'fallida')),
    fecha_base TEXT NOT NULL,
    hora_base TEXT NOT NULL,
    rondas TEXT NOT NULL DEFAULT '[]',      -- JSON: lista de textos, uno por ronda
    borrador TEXT,                          -- JSON: {"items": [...], "pregunta": ..., "preguntados": [...]}
    error TEXT,
    reintentable INTEGER NOT NULL DEFAULT 0,  -- 1: la transcripción quedó y se puede volver a interpretar
    registros TEXT,                         -- JSON: lo que se guardó, con sus enlaces
    creada TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    actualizada TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX voz_entradas_estado ON voz_entradas (estado);

-- Pares sesión y actividad del reloj que el usuario dijo que no son la misma: no se vuelven a proponer.
CREATE TABLE vinculos_descartados (
    sesion_id INTEGER NOT NULL REFERENCES sesiones (id) ON DELETE CASCADE,
    clave TEXT NOT NULL,
    creado TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (sesion_id, clave)
);
