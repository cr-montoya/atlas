-- Rendimiento v1: sesiones, series, combate, técnicas, tests y anotaciones de sesiones importadas.
-- Cargas en gramos enteros (80 kg = 80000), distancias en metros, duraciones en segundos,
-- RPE en décimas (8,5 = 85), valores de test en milésimas de su unidad (44,20 cm = 47100).

CREATE TABLE ejercicios (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    grupo TEXT NOT NULL,              -- grupo muscular principal: piernas, empuje, tirón, core, cadera, cuerpo completo
    tipo_carga TEXT NOT NULL CHECK (tipo_carga IN
        ('barra', 'maquina', 'mancuerna_par', 'mancuerna_una', 'unilateral', 'peso_corporal', 'peso_corporal_lastre')),
    carga_hombro INTEGER NOT NULL DEFAULT 0 CHECK (carga_hombro IN (0, 1)),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1))
);

CREATE TABLE tecnicas (
    id INTEGER PRIMARY KEY,
    disciplina TEXT NOT NULL CHECK (disciplina IN ('judo', 'bjj', 'muaythai')),
    familia TEXT NOT NULL,
    nombre TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    UNIQUE (disciplina, nombre)
);

-- Sesión registrada en la app. Si viene de un sensor, `clave_importada` la vincula
-- con la actividad de Garmin o Polar ("fuente|fecha|hora").
CREATE TABLE sesiones (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    hora TEXT,
    tipo TEXT NOT NULL CHECK (tipo IN ('fuerza', 'combate', 'cardio')),
    disciplina TEXT NOT NULL,         -- fuerza, judo, bjj, muaythai, caminata, caminadora, carrera, ciclismo, cardio, otro
    duracion_s INTEGER CHECK (duracion_s IS NULL OR duracion_s >= 0),
    sensaciones INTEGER CHECK (sensaciones IS NULL OR sensaciones BETWEEN 1 AND 5),
    molestia_hombro INTEGER CHECK (molestia_hombro IS NULL OR molestia_hombro BETWEEN 0 AND 10),
    notas TEXT,
    clave_importada TEXT,
    guardada INTEGER NOT NULL DEFAULT 0 CHECK (guardada IN (0, 1)),  -- 0 mientras se registra
    creada TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX sesiones_fecha ON sesiones (fecha);

CREATE TABLE series (
    id INTEGER PRIMARY KEY,
    sesion_id INTEGER NOT NULL REFERENCES sesiones (id) ON DELETE CASCADE,
    ejercicio_id INTEGER NOT NULL REFERENCES ejercicios (id),
    orden INTEGER NOT NULL,
    reps INTEGER NOT NULL CHECK (reps > 0),
    carga_g INTEGER NOT NULL DEFAULT 0 CHECK (carga_g >= 0),  -- lastre en ejercicios de peso corporal
    rpe_x10 INTEGER CHECK (rpe_x10 IS NULL OR rpe_x10 BETWEEN 10 AND 100),
    peso_corporal_g INTEGER           -- foto del peso corporal al guardar, para ejercicios de peso corporal
);
CREATE INDEX series_sesion ON series (sesion_id);

CREATE TABLE combate_bloques (
    id INTEGER PRIMARY KEY,
    sesion_id INTEGER NOT NULL REFERENCES sesiones (id) ON DELETE CASCADE,
    orden INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('tecnica', 'drill', 'situacional', 'randori')),
    duracion_s INTEGER CHECK (duracion_s IS NULL OR duracion_s >= 0),
    rounds INTEGER CHECK (rounds IS NULL OR rounds > 0),
    rival TEXT                        -- más pesado, más liviano, zurdo, más técnico (randori y situacional)
);

-- Lo trabajado en un bloque: una técnica del catálogo, una situación o ambas, y su resultado.
CREATE TABLE combate_tecnicas (
    id INTEGER PRIMARY KEY,
    bloque_id INTEGER NOT NULL REFERENCES combate_bloques (id) ON DELETE CASCADE,
    tecnica_id INTEGER REFERENCES tecnicas (id),
    situacion TEXT CHECK (situacion IS NULL OR situacion IN ('agarre', 'entradas', 'transiciones', 'defensa')),
    resultado TEXT NOT NULL DEFAULT 'trabajada' CHECK (resultado IN ('trabajada', 'funciono', 'no_funciono')),
    detalle TEXT
);

CREATE TABLE tests (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('cmj', 'antropometria', 'dinamometria', 'carga_velocidad', 'caminata_6min',
                                       'rm', 'sprint', 'movilidad', 'otro')),
    fecha TEXT NOT NULL,              -- AAAA-MM-DD; con precisión de mes, el día 01
    fecha_precision TEXT NOT NULL DEFAULT 'dia' CHECK (fecha_precision IN ('dia', 'mes')),
    fecha_aproximada INTEGER NOT NULL DEFAULT 0 CHECK (fecha_aproximada IN (0, 1)),  -- "~ene 2025"
    metodo TEXT,
    evaluador TEXT,
    protocolo TEXT,
    notas TEXT,
    origen TEXT,                      -- de dónde vino: "app" o el archivo local de carga
    creado TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE test_valores (
    id INTEGER PRIMARY KEY,
    test_id INTEGER NOT NULL REFERENCES tests (id) ON DELETE CASCADE,
    medida TEXT NOT NULL,             -- "CMJ", "Peso", "% graso", "Suma 6 pliegues"
    valor_mil INTEGER NOT NULL,
    unidad TEXT NOT NULL,
    direccion TEXT NOT NULL CHECK (direccion IN ('mas', 'menos', 'neutra')),
    UNIQUE (test_id, medida)
);

-- Correcciones a sesiones leídas del vault (nunca se escribe en el vault).
-- clave = "fuente|fecha|hora", estable aunque se reimporte el CSV.
CREATE TABLE anotaciones_importadas (
    clave TEXT PRIMARY KEY,
    disciplina TEXT,                  -- confirmación o reclasificación del usuario
    es_entrenamiento INTEGER CHECK (es_entrenamiento IS NULL OR es_entrenamiento IN (0, 1)),
    sensaciones INTEGER CHECK (sensaciones IS NULL OR sensaciones BETWEEN 1 AND 5),
    molestia_hombro INTEGER CHECK (molestia_hombro IS NULL OR molestia_hombro BETWEEN 0 AND 10),
    notas TEXT,
    actualizada TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Trabajos de fondo (sincronización de sensores y, en la fase 3, análisis de Claude). Uno a la vez.
CREATE TABLE trabajos_ia (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'en_cola' CHECK (estado IN ('en_cola', 'corriendo', 'listo', 'fallido')),
    creado TEXT NOT NULL DEFAULT (datetime('now')),
    inicio TEXT,
    fin TEXT,
    parametros TEXT,                  -- JSON
    resultado TEXT,
    error TEXT,
    registro TEXT
);
