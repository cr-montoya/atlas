-- Cómo se sintió el usuario cada día, por voz o a mano. Una fila por día; si queda sin ningún dato se borra.
-- Las longitudes de los textos se validan en la app (sensaciones.py).
CREATE TABLE sensaciones_dia (
    fecha TEXT PRIMARY KEY,
    energia INTEGER CHECK (energia IS NULL OR energia BETWEEN 1 AND 5),
    animo INTEGER CHECK (animo IS NULL OR animo BETWEEN 1 AND 5),
    estres INTEGER CHECK (estres IS NULL OR estres BETWEEN 1 AND 5),
    sueno INTEGER CHECK (sueno IS NULL OR sueno BETWEEN 1 AND 5),
    motivacion INTEGER CHECK (motivacion IS NULL OR motivacion BETWEEN 1 AND 5),
    hambre INTEGER CHECK (hambre IS NULL OR hambre BETWEEN 1 AND 5),
    sintomas TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(sintomas)),   -- JSON: claves de sensaciones.SINTOMAS
    sintomas_otros TEXT,
    dolor TEXT,
    sin_entreno TEXT CHECK (sin_entreno IS NULL OR sin_entreno IN ('descanso', 'enfermedad', 'lesion', 'otro')),
    relato TEXT,                          -- citas verificadas de la voz, una por línea
    notas TEXT,
    actualizada TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
