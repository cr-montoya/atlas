# Resumen de rendimiento para IA

La app deja los datos de entrenamiento listos para que la sesión del Life Brain los lea y haga la ingesta a `historial-entrenamiento.md` y `marcas-y-pruebas.md`. La app **no** escribe en las notas canónicas del vault.

## Dónde

| Archivo | Para qué |
| --- | --- |
| `exports/rendimiento-ia.json` | Datos estructurados, esquema versionado (abajo) |
| `exports/rendimiento-ia.md` | Lo mismo en Markdown con las reglas del vault: prefijo `[M]`, fuente `[app rendimiento AAAA-MM-DD | alta]`, sin raya larga |

`exports/` está en `.gitignore` (tiene datos reales) y los archivos quedan con permisos 600.

## Cuándo se regenera

- Al guardar una sesión de fuerza o de combate.
- Al guardar sensaciones, molestia o una corrección de una actividad del reloj.
- Al guardar o borrar un test.
- Al guardar una foto (fase 2).
- Al guardar una comida, el agua o las notas del día (fase 4).
- Al guardar o borrar un pesaje en la vista Competencia.
- A mano: `make resumen-rendimiento`.

La escritura es atómica. Si falla, lo guardado se conserva y el error queda en `make logs`.

## Esquema (`schema_version` "1")

Unidades: cargas en gramos (80 kg = 80000); duraciones en segundos; distancias en metros; FC en lpm; RPE en décimas (8,5 = 85); valores de test en milésimas de su unidad (44,20 cm = 47100); molestia del hombro de 0 a 10. Fechas ISO. `null` = sin dato.

| Clave | Contenido |
| --- | --- |
| `schema_version`, `generado`, `hoy`, `fuente`, `unidades` | Sobre común con el resumen de finanzas |
| `periodo` | `desde` (hoy menos 90 días) y `hasta` |
| `sesiones[]` | Sesiones guardadas en la app: `id`, `fecha`, `tipo` (`fuerza`, `combate`), `disciplina`, `duracion_s`, `molestia_hombro`, `sensaciones`, `notas`, `reloj` (actividad vinculada: `fuente`, `deporte`, `hora`, `duracion_s`, `fc_media`, `fc_max`) |
| `sesiones[].ejercicios[]` | Fuerza: `ejercicio`, `grupo`, `tipo_carga`, `carga_el_hombro`, `carga_total_g`, `series[]` (`reps`, `carga_g`, `rpe_x10`). La sesión trae `carga_total_g` |
| `sesiones[].bloques[]` | Combate: `tipo` (`tecnica`, `drill`, `situacional`, `randori`), `duracion_s`, `rounds`, `rival[]`, `entradas[]` (`tecnica`, `familia`, `situacion`, `resultado`: `trabajada`, `funciono`, `no_funciono`, `detalle`) |
| `actividades_anotadas[]` | Correcciones a actividades de Garmin o Polar: `clave` (`fuente\|fecha\|hora`), `disciplina`, `es_entrenamiento`, `sensaciones`, `molestia_hombro`, `notas` |
| `tests[]` | Tests registrados en la app o cargados del archivo local (los del vault ya están en el vault): `tipo`, `fecha`, `fecha_precision` (`dia`, `mes`), `fecha_aproximada`, `metodo`, `evaluador`, `protocolo`, `notas`, `origen`, `valores[]` (`medida`, `valor_mil`, `unidad`, `direccion`: `mas`, `menos`, `neutra`) |
| `semanas[]` | Semana anterior y actual: `semana`, `sesiones`, `minutos_s`, `carga_g`, `zonas_s` (Z1 a Z5), `zonas_estimadas`, `sueno_s`, `hrv_ms`, `fc_reposo`, `pasos`, `molestia_promedio_mil` |
| `metas` | `hitos[]` (`nombre`, `inicio`, `fin`, `aproximado`, `texto`) y `pasos_dia` |
| `fotos[]` | Solo `fecha` y `pose`. Nunca la imagen ni su ruta |
| `comidas[]` | Comidas registradas en la app, tal como las escribió (`[H]` en el `.md`): `fecha`, `momento` (`desayuno`, `media_manana`, `almuerzo`, `media_tarde`, `cena`, `extra`), `hora`, `texto`, `intercambios` (los que marcó él, por grupo) y `segun_plan`. La app no estima porciones ni califica el día; eso lo hace la revisión semanal con `.agents/nutricion.md` |
| `pesajes[]` | Pesajes en casa registrados en la vista Competencia: `fecha`, `hora`, `peso_g`, `condicion` (`ropa_interior`, `con_ropa`) y `nota`, con la ventana de 90 días. En el `.md`, el peso es `[M]` y la nota `[H]`. La app no los califica ni los compara con el límite en el resumen |
| `avisos[]` | Molestia del hombro al alza, sensores atrasados, sesiones "Judo o BJJ" sin confirmar |

## Registro por voz: qué sale de la casa

`/rendimiento/voz` convierte un relato (audio o texto) en un borrador de comidas, agua y sesiones. Ver
`openspec/changes/v1-registro-por-voz`.

- **El audio no sale de la casa ni se guarda.** Se transcribe en el servidor con faster-whisper (`BRAIN_WHISPER_MODELO`,
  por defecto `small`, desde el caché de Hugging Face, sin descargas en tiempo de ejecución) y se borra en el acto.
- **A Anthropic solo va texto:** la transcripción, la fecha y la hora, los momentos y grupos de intercambio, y los
  nombres de los catálogos de ejercicios y técnicas. Nada de peso corporal, sensores, fotos ni el vault.
- **Llamada aislada:** `claude -p` sin herramientas (`--tools ""`), sin MCP, sin ajustes ni memoria del usuario
  (`--setting-sources ""`), sin sesión guardada, con un entorno mínimo (sin `BRAIN_*` ni `FINANZAS_*`) y en una carpeta
  temporal vacía. Modelo: `BRAIN_MODELO_VOZ` (por defecto `opus`); tope: `BRAIN_TIEMPO_MAX_VOZ` (120 s).
- **No inventa:** Python valida contra lo dicho (cita literal, números oídos, horas dichas, catálogos y rangos) y nada se
  guarda hasta que el usuario confirma el borrador. Las transcripciones se vacían a los 30 días.
- **Cruce con los sensores:** lo hace Python con las actividades importadas; Claude no las ve.
