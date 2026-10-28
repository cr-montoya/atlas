-- Fotos del cuerpo para comparar antes y después. Las imágenes viven en disco (data/fotos/, fuera de git,
-- permisos 600) sin metadatos EXIF; aquí solo la fecha, la pose y el nombre del archivo.
-- Se llama fotos_cuerpo porque finanzas ya usa la tabla fotos para la foto mensual de saldos.
CREATE TABLE fotos_cuerpo (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    pose TEXT NOT NULL CHECK (pose IN ('frente', 'perfil_derecho', 'espalda')),
    archivo TEXT NOT NULL,            -- nombre dentro de data/fotos/, por ejemplo 2026-10-17_frente.jpg
    ancho INTEGER NOT NULL,
    alto INTEGER NOT NULL,
    notas TEXT,
    creada TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (fecha, pose)
);
