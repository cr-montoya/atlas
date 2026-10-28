-- Retención en la fuente sobre rendimientos financieros, en ppm del rendimiento (7 % = 70.000), editable.
ALTER TABLE escenario ADD COLUMN retencion_ppm INTEGER NOT NULL DEFAULT 70000 CHECK (retencion_ppm BETWEEN 0 AND 1000000);
