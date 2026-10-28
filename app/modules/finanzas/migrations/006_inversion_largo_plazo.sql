-- Con M4 cumplido, el fondo de emergencia se topa en M4 y el sobrante va a "Inversión largo plazo"
-- (acciones o ETF diversificados, 5 años o más) con un rendimiento esperado editable (10 % E.A. = 100.000).
ALTER TABLE escenario ADD COLUMN topar_en_m4 INTEGER NOT NULL DEFAULT 1 CHECK (topar_en_m4 IN (0, 1));
ALTER TABLE escenario ADD COLUMN inversion_ea_ppm INTEGER NOT NULL DEFAULT 100000 CHECK (inversion_ea_ppm >= 0);
