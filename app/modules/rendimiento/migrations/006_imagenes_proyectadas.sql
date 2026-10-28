-- Imagen proyectada (openspec/changes/v1-imagen-proyectada): una fila por pose de cada trabajo de imagen.
-- La imagen vive en data/fotos/generadas/ (permisos 600, sin metadatos); aquí solo el estado y el archivo.
-- foto_base_id no tiene ON DELETE: si se borra la foto base, la ilustración queda sola.
CREATE TABLE imagenes_proyectadas (
    id INTEGER PRIMARY KEY,
    trabajo_id INTEGER NOT NULL REFERENCES trabajos_ia (id),
    pose TEXT NOT NULL CHECK (pose IN ('frente', 'perfil_derecho', 'espalda')),
    foto_base_id INTEGER,
    fecha_base TEXT NOT NULL,
    fecha_objetivo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'lista', 'fallida')),
    error TEXT,
    archivo TEXT,                     -- nombre dentro de data/fotos/generadas/
    ancho INTEGER,
    alto INTEGER,
    creada TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (trabajo_id, pose)
);

-- Lo que hay que borrar si el trabajo se interrumpe: carpetas de hilo de Codex y la carpeta temporal.
CREATE TABLE imagen_limpieza (
    id INTEGER PRIMARY KEY,
    trabajo_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('hilo', 'carpeta')),
    valor TEXT NOT NULL,
    UNIQUE (tipo, valor)
);
