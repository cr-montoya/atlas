-- Registro rápido de comidas por momento del día (fase 4). Lo que escribe el usuario es [H]; los intercambios
-- son los que él marca, nunca estimados por la app. Con BRAIN_ESCRIBIR_COMIDAS=1 el día también se escribe
-- en el vault, en 00_Inbox/comidas/AAAA-Www/AAAA-MM-DD.md (la única escritura de la app en el vault).
CREATE TABLE comidas_registro (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    momento TEXT NOT NULL CHECK (momento IN ('desayuno', 'media_manana', 'almuerzo', 'media_tarde', 'cena', 'extra')),
    hora TEXT,                        -- HH:MM
    texto TEXT,                       -- qué comió y cuánto, con sus palabras
    intercambios TEXT,                -- JSON {"carbohidrato": 2, ...} marcado por él
    segun_plan INTEGER NOT NULL DEFAULT 0,
    actualizado TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (fecha, momento)
);

CREATE TABLE comidas_dia (
    fecha TEXT PRIMARY KEY,
    agua_vasos INTEGER,               -- vasos de 200 ml
    suplementos TEXT,
    notas TEXT,
    vault_estado TEXT,                -- escrito | manual (el archivo ya existía escrito a mano) | error
    actualizado TEXT NOT NULL DEFAULT (datetime('now'))
);
