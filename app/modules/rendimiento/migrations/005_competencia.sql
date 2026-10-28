-- Competencia (torneo de planificacion-semanal.md): pesajes en casa y marcas del checklist del día.
-- El torneo, el plan y el checklist se leen del vault; aquí solo queda lo que registral usuario.
CREATE TABLE pesajes (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL UNIQUE,       -- AAAA-MM-DD, uno por día
    hora TEXT,                        -- HH:MM
    peso_g INTEGER NOT NULL CHECK (peso_g BETWEEN 30000 AND 200000),
    condicion TEXT CHECK (condicion IS NULL OR condicion IN ('ropa_interior', 'con_ropa')),
    nota TEXT,
    actualizado TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Marcas del checklist por torneo (fecha del torneo); se borran cuando pasa.
CREATE TABLE checklist_competencia (
    competencia TEXT NOT NULL,
    item TEXT NOT NULL,
    PRIMARY KEY (competencia, item)
);
