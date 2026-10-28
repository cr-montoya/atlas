-- Rendimiento de cada cuenta: tasa efectiva anual en partes por millón (9,00 % E.A. = 90.000) y una nota
-- (por ejemplo "variable, sin Fogafín"). NULL = sin dato: la cuenta no crece en la proyección.
ALTER TABLE cuentas ADD COLUMN rendimiento_ea_ppm INTEGER CHECK (rendimiento_ea_ppm IS NULL OR rendimiento_ea_ppm >= 0);
ALTER TABLE cuentas ADD COLUMN rendimiento_nota TEXT NOT NULL DEFAULT '';
