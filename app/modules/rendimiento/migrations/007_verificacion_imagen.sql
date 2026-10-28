-- Verificación de cada ilustración contra su análisis (paso 3): dentro, exagerada o sin_verificar.
ALTER TABLE imagenes_proyectadas ADD COLUMN verificacion TEXT
    CHECK (verificacion IS NULL OR verificacion IN ('dentro', 'exagerada', 'sin_verificar'));
ALTER TABLE imagenes_proyectadas ADD COLUMN verificacion_nota TEXT;
ALTER TABLE imagenes_proyectadas ADD COLUMN intentos INTEGER;
