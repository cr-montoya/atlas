# Resumen para IA

La app deja sus datos listos para que la sesión del Life Brain los lea, sin que el usuario escriba un prompt con números. La app **nunca** escribe en el vault: la sesión lee estos archivos y hace la ingesta.

## Dónde

| Archivo | Para qué |
| --- | --- |
| `exports/resumen-ia.json` | Datos estructurados, esquema versionado (abajo) |
| `exports/resumen-ia.md` | Lo mismo en Markdown con las reglas del vault: prefijo `[M]`, fuente `[app finanzas AAAA-MM-DD | alta]`, sin raya larga, sin números de cuenta |

Ruta absoluta en el portátil: `~/atlas/exports/`. Se puede cambiar con `FINANZAS_EXPORTS` en `.env`. La carpeta está en `.gitignore` (tiene datos reales) y los archivos quedan con permisos 600.

## Cuándo se regenera

- Al confirmar una quincena o un ingreso extra.
- Al guardar el escenario base en Futuro.
- Al guardar la revisión mensual.
- A mano: `make resumen-ia`, o en la app: Más, Exportar resumen, Generar ahora.

La escritura es atómica (archivo temporal y renombrado): quien lea nunca ve un archivo a medias. Si la escritura falla, la operación de plata ya quedó guardada y el error queda en `make logs`.

## Esquema (`schema_version` "1")

Unidades: todo monto es un entero. COP en pesos; USD en centavos (con `moneda: "USD"`); TRM en centavos de peso (319961 = 3.199,61); tasas en partes por millón (21285 = 2,1285 % mensual). Fechas ISO. `null` = sin dato.

| Clave | Contenido |
| --- | --- |
| `schema_version` | "1". Sube con cualquier cambio incompatible |
| `generado`, `hoy`, `fuente`, `unidades` | Cuándo se generó, la fecha de los datos y la etiqueta de fuente para el vault |
| `periodo` | `desde` (hoy menos 90 días) y `hasta` |
| `proximo_pago` | Siguiente día de pago (15 o 30) |
| `quincenas[]` | Quincenas e ingresos extra del periodo: `id`, `fecha`, `tipo` (`quincena`, `extra`, `prima`, `intereses_cesantias`, `cesantias`, `otro`), `neto`, `plantilla`, `trm`, `lineas[]` (`concepto`, `bolsillo`, `tipo_bolsillo`, `planeado`, `real`, `pagada`, `deuda`, `fondo`) |
| `plan_vs_real[]` | Por quincena y bolsillo: `planeado`, `real` (`null` = sin registrar) y `diferencia` (planeado menos real) |
| `gastos[]` | Gastos rápidos del periodo: `fecha`, `monto`, `bolsillo`, `categoria`, `nota` |
| `abonos[]` | Abonos y ajustes de deudas del periodo, con `trm` y `costo_cop` en USD |
| `deudas[]` | `nombre`, `moneda`, `saldo`, `saldo_cop`, `tasa_mensual_ppm`, `cuota_mensual`, `fecha_cero_por_promedio`, `promedio_por_quincena`, `pocos_datos` |
| `fondos[]` | `nombre`, `objetivo`, `acumulado`, `fecha_objetivo`, `cada_meses`, `provision_quincena`, `quincenas_restantes`, `estimado`, `aporte_fijo`, `no_liquido`, `falta` |
| `metas[]` | `nombre`, `objetivo`, `actual`, `pct`, `faltan`, `cuentas` |
| `patrimonio` | Última foto: `foto`, `trm`, `cuentas`, `deudas_cop`, `neto` |
| `indicadores` | Mes en curso: `ingreso_neto`, `ahorro`, `tasa_ahorro_pct`, `meses_colchon_decimas` (41 = 4,1 meses), `gasto_basico_referencia`, `pagos_deuda`, `deuda_ingreso_pct`, `gasto_libre_tope`, `gasto_libre_real` |
| `escenario` | Supuestos de la proyección (montos, estrategia, horizonte, incapacidad) |
| `eventos[]` | Ingresos, gastos y traslados a un fondo, futuros: `tipo` (`ingreso`, `gasto`, `traslado`), `monto` (`null` = sin dato), `estimado`, `destino_deuda`, `destino_fondo`, `solo_escenario` |
| `proyeccion_resumen` | `fecha_cero` por deuda (AAAA-MM o `null` si pasa del horizonte), `mes_libre_de_deudas`, `intereses_totales`, `comparacion` con la otra estrategia, `mes_meta_1`, `mes_m4`, `al_final` y `por_mes[]` |
| `revision` | Revisión del mes en curso o, si no hay, del anterior: `distinto`, `inesperado`, `ajustar`, `plantillas`, `sensacion` (1 a 5) |
| `avisos[]` | Datos faltantes que hacen la proyección optimista (deudas sin tasa, eventos sin monto) |

## Historial del esquema

Regla acordada con la sesión del Life Brain: agregar un campo o un valor nuevo de un enum es compatible y **no** sube la versión (quien lee tolera campos desconocidos). `schema_version` sube solo si se quita o renombra algo, o si cambian las unidades.

- **1** (2026-10-17): versión inicial (v2 "real y proyecciones").
- **1**, ampliación compatible (2026-10-17): `cuentas[]` con `rendimiento_ea_ppm` y `rendimiento_ea_neto_ppm`, `ahorrar_o_prepagar[]`, `proyeccion_resumen.rendimientos_cuentas`, `mes_inicio_inversion`, `al_final.inversion_largo_plazo` y `por_mes[].inversion_largo_plazo`; en `escenario`: `retencion_ppm`, `topar_en_m4` e `inversion_ea_ppm`.
- **1**, ampliación compatible (2026-10-17): `eventos[].tipo` admite `traslado` (plata que se guarda en un fondo) y `escenario.sobrante_a_ahorro` (1 = plan: el sobrante solo prepaga las deudas marcadas y el resto va a ahorro).
