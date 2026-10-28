---
name: Atlas (finanzas y rendimiento)
description: El ritual del día de pago. Una superficie oscura y cálida donde la quincena se reparte peso a peso y los números son los protagonistas.
colors:
  # Tema oscuro (por defecto)
  noche: "#131211"
  superficie: "#1b1a18"
  superficie-alta: "#23211f"
  linea: "#2e2b28"
  tinta: "#ede8e0"
  tinta-suave: "#aaa59d"
  tinta-tenue: "#8f8a82"
  azul-pago: "#2a72de"
  azul-pago-texto: "#6a9ff0"
  negativo: "#ef6a55"
  positivo: "#a9bb8f"
  bolsillo-fijo: "#ddaa61"
  bolsillo-deuda: "#d68b7a"
  bolsillo-ahorro: "#9fb08a"
  bolsillo-libre: "#bfb8ac"
  # Tema claro
  papel: "#f7f1e8"
  papel-superficie: "#fffdf9"
  papel-alta: "#efe8dc"
  papel-linea: "#e1dcd3"
  papel-tinta: "#1c1b1a"
  papel-tinta-suave: "#4a4741"
  papel-tinta-tenue: "#6b6761"
  papel-azul-pago: "#2a63c4"
  papel-negativo: "#b8321d"
  papel-positivo: "#47622f"
  papel-bolsillo-fijo: "#8c5c10"
  papel-bolsillo-deuda: "#94473a"
  papel-bolsillo-ahorro: "#4d5f4e"
  papel-bolsillo-libre: "#5f5b55"
  # Rendimiento: disciplinas (categórico) y zonas de FC (rampa brasa, un solo tono)
  r-fuerza: "#ddaa61"
  r-judo: "#7fa8b8"
  r-bjj: "#b48aa8"
  r-muaythai: "#d68b7a"
  r-cardio: "#9fb08a"
  r-otro: "#bfb8ac"
  r-z1: "#7a6c55"
  r-z2: "#9a7f55"
  r-z3: "#bb9257"
  r-z4: "#dba65c"
  r-z5: "#f4c88a"
  papel-r-fuerza: "#8c5c10"
  papel-r-judo: "#2f6378"
  papel-r-bjj: "#7a4a6e"
  papel-r-muaythai: "#94473a"
  papel-r-cardio: "#4d5f4e"
  papel-r-otro: "#5f5b55"
  papel-r-z1: "#a28456"
  papel-r-z2: "#9a7238"
  papel-r-z3: "#7f5618"
  papel-r-z4: "#633f0b"
  papel-r-z5: "#462b05"
typography:
  cifra-hero:
    fontFamily: Geist
    fontSize: 2.5rem
    fontWeight: 500
    lineHeight: 1.05
    letterSpacing: -0.03em
    fontFeature: '"tnum" 1'
  titulo:
    fontFamily: Geist
    fontSize: 1.5rem
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.02em
  subtitulo:
    fontFamily: Geist
    fontSize: 1.0625rem
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: -0.01em
  cuerpo:
    fontFamily: Geist
    fontSize: 1rem
    fontWeight: 400
    lineHeight: 1.55
  cifra:
    fontFamily: Geist
    fontSize: 1rem
    fontWeight: 500
    lineHeight: 1.3
    fontFeature: '"tnum" 1'
  etiqueta:
    fontFamily: Geist
    fontSize: 0.8125rem
    fontWeight: 500
    lineHeight: 1.3
  dato:
    fontFamily: Geist Mono
    fontSize: 0.8125rem
    fontWeight: 400
    lineHeight: 1.3
rounded:
  sm: 6px
  md: 8px
  lg: 12px
  pill: 9999px
spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
components:
  boton-primario:
    backgroundColor: "{colors.azul-pago}"
    textColor: "#ffffff"
    typography: "{typography.subtitulo}"
    rounded: "{rounded.md}"
    height: 48px
    padding: "0 20px"
  boton-secundario:
    backgroundColor: "{colors.superficie-alta}"
    textColor: "{colors.tinta}"
    typography: "{typography.subtitulo}"
    rounded: "{rounded.md}"
    height: 44px
    padding: "0 16px"
  campo:
    backgroundColor: "{colors.noche}"
    textColor: "{colors.tinta}"
    typography: "{typography.cifra}"
    rounded: "{rounded.md}"
    height: 48px
    padding: "0 12px"
  tarjeta:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.lg}"
    padding: "16px"
  barra-inferior:
    backgroundColor: "{colors.superficie}"
    textColor: "{colors.tinta-suave}"
    typography: "{typography.etiqueta}"
    height: 64px
  etiqueta-tipo:
    backgroundColor: "{colors.superficie-alta}"
    textColor: "{colors.tinta-suave}"
    typography: "{typography.etiqueta}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
---

# Design System: Finanzas personales

## Overview

**Creative North Star: "La mesa del día de pago"**

Es la noche del 15 o del 30. La plata llegó y hay que darle destino antes de que se disuelva. La app es esa mesa: una superficie oscura y cálida (no azul, no neón) sobre la que la quincena se reparte peso a peso hasta que la cuenta da cero. Hereda de Oura la calma, el fondo de tono cálido y la disciplina de color (los tonos tierra hacen el trabajo de datos y nunca van en botones; un único azul decide). Hereda de Mercury los patrones de finanzas: filas de montos alineados a la derecha, estados claros, profundidad por tono y no por sombra. De taste-skill `minimalist-ui` toma la paleta contenida, las líneas de 1 px y la ausencia de adornos.

Es una superficie de trabajo (modo Operate): navegación estándar, controles estándar, todo encontrable en segundos. La identidad vive en cuatro cosas: la tipografía de cifras tabulares, la paleta cálida, una densidad tranquila y un solo gesto propio, la **tira del reparto**.

**Key Characteristics:**
- Oscuro primero (`noche` #131211) con tema claro de papel cálido (`papel` #f7f1e8).
- Las cifras son las protagonistas: Geist con `tnum`, alineadas a la derecha, separador de miles con punto.
- Color con trabajo: cada tipo de bolsillo tiene su tono tierra; rojo y verde solo para signo; azul solo para la acción decisiva.
- Plano: tarjetas separadas por un paso de tono y una línea de 1 px, sin sombras.
- Una columna en el celular (360 px), barra de navegación inferior, botones de 44 px o más.

## Colors

Monocromo cálido con cuatro tonos tierra para los bolsillos y un único azul de acción.

### Primary
- **Azul de pago** (#2a72de oscuro / #2a63c4 claro): solo el botón que compromete plata: "Confirmar reparto", "Registrar abono", "Guardar foto". Uno por pantalla. Texto blanco (4,6:1 y 5,7:1).
- **Azul de pago, texto** (#6a9ff0): enlaces y foco en el tema oscuro, nunca como relleno.

### Tertiary (colores de dato)
- **Fijo, mostaza** (#ddaa61 / #8c5c10): bolsillo Casa y gastos fijos.
- **Deuda, arcilla** (#d68b7a / #94473a): Tarjeta Uno y cualquier bolsillo que paga deudas.
- **Ahorro, salvia** (#9fb08a / #4d5f4e): Ahorro y barras de metas.
- **Libre, piedra** (#bfb8ac / #5f5b55): Libre, el `resto`.
- **Negativo** (#ef6a55 / #b8321d): patrimonio negativo, descuadre, errores.
- **Positivo** (#a9bb8f / #47622f): "Cuadra: 0", patrimonio positivo.

### Neutral
- **Noche** (#131211): fondo de página y fondo de los campos.
- **Superficie** (#1b1a18): tarjetas y barra inferior.
- **Superficie alta** (#23211f): botones secundarios, etiquetas, filas activas.
- **Línea** (#2e2b28): divisores de 1 px y bordes de tarjeta y campo.
- **Tinta** (#ede8e0): texto principal y cifras. Nunca blanco puro.
- **Tinta suave** (#aaa59d): etiquetas, conceptos, texto secundario.
- **Tinta tenue** (#8f8a82): metadatos (fechas, TRM, notas). Mínimo 4,6:1 en cualquier superficie.
- Tema claro: papel #f7f1e8, papel superficie #fffdf9, papel alta #efe8dc, línea #e1dcd3, tinta #1c1b1a, suave #4a4741, tenue #6b6761.

### Named Rules
**La regla del único azul.** El azul de pago aparece una vez por pantalla, en la acción que mueve plata. Todo lo demás clicable es secundario.
**La regla del signo.** Rojo y verde solo dicen signo o cuadre. Nunca decoran.
**La regla tierra.** Los tonos de bolsillo viven en datos (tira, punto, barra), nunca en botones ni en fondos grandes.

## Typography

**Fuente de interfaz y cifras:** Geist (Google Fonts), con `system-ui, -apple-system, "Segoe UI", sans-serif` de respaldo.
**Fuente de dato:** Geist Mono, solo para la vista previa del Markdown exportado. La TRM va en Geist con cifras tabulares (en mono, dentro de una frase, se ve con huecos).

**Character:** una sola familia de grotesca neutra con buen juego de cifras tabulares; la jerarquía sale del tamaño y del peso, no de una segunda voz decorativa.

### Hierarchy
- **Cifra hero** (500, 2.5rem, 1.05, -0.03em, `tnum`): el monto principal de cada pantalla (neto de la quincena, patrimonio). Uno por pantalla.
- **Título** (600, 1.5rem, 1.2): nombre de la pantalla ("Quincena del 30").
- **Subtítulo** (600, 1.0625rem): encabezado de bloque ("Deudas", "Metas").
- **Cuerpo** (400, 1rem, 1.55): textos y ayudas. Medida máxima 65ch.
- **Cifra** (500, 1rem, `tnum`): montos en filas y campos, alineados a la derecha.
- **Etiqueta** (500, 0.8125rem): nombres de campo, barra inferior, etiquetas de tipo. Sin mayúsculas sostenidas.

### Named Rules
**La regla tabular.** Todo monto lleva `font-variant-numeric: tabular-nums` y se alinea a la derecha. Formato COP `4.650.000`; USD `1.837,00 USD`.
**La regla sin sobretítulo.** Nada de etiquetas pequeñas encima de los títulos; el título se sostiene solo.

## Layout

Una columna de máximo 40rem centrada; en escritorio el tablero pasa a dos columnas (deudas y metas lado a lado) desde 64rem. Gutter lateral de 16 px en el celular, 24 px desde 48rem. Ritmo vertical: 8 px dentro de una fila, 16 px entre filas de un bloque, 32 px entre bloques. Más espacio arriba de un subtítulo que debajo.

Barra de navegación inferior fija de 64 px (más el área segura del dispositivo) en el celular; en escritorio, desde 48rem, la misma navegación pasa a una barra superior. El contenido deja espacio inferior para que la barra nunca tape el último botón. Nunca desplazamiento horizontal: las tablas se vuelven filas apiladas a 360 px.

## Elevation & Depth

Sin sombras. La profundidad es tonal: noche (fondo) a superficie (tarjeta) a superficie alta (control). Cada tarjeta lleva además una línea de 1 px. El único cambio de profundidad interactivo es el del botón presionado (`transform: scale(0.98)`).

### Named Rules
**La regla plana.** Elevación por tono o por línea, nunca ambas con sombra. Ninguna `box-shadow` salvo el anillo de foco.

## Shapes

Radios contenidos: 12 px en tarjetas, 8 px en botones y campos, 6 px en elementos pequeños, píldora solo para etiquetas de tipo y la tira del reparto. Bordes de 1 px en `linea`. Nada de bordes laterales de color.

## Components

### Buttons
- **Shape:** 8 px, alto 48 px (primario) y 44 px (secundario), ancho completo en el celular.
- **Primary:** azul de pago, texto blanco, peso 600. Desactivado: superficie alta con tinta tenue y `cursor: not-allowed`, nunca azul atenuado.
- **Hover / Focus:** hover aclara el fondo un paso; foco con anillo de 2 px `azul-pago-texto` y separación de 2 px.
- **Secondary:** superficie alta, tinta, sin borde. **Ghost:** solo texto en azul de pago texto, para acciones menores ("Ajustar por extracto").

### Chips
- **Etiqueta de tipo:** píldora en superficie alta con un punto de 8 px del color del tipo de bolsillo y el nombre del tipo en tinta suave.

### Cards / Containers
- **Corner Style:** 12 px.
- **Background:** superficie sobre noche.
- **Shadow Strategy:** ninguna (ver Elevation).
- **Border:** 1 px `linea`.
- **Internal Padding:** 16 px; 24 px desde 48rem.
- Nunca tarjetas dentro de tarjetas; dentro de una tarjeta se separa con líneas de 1 px.

### Inputs / Fields
- **Style:** fondo noche (un paso más hundido que la tarjeta), borde 1 px línea, 8 px, alto 48 px, cifra alineada a la derecha para montos, `inputmode="numeric"` o `decimal`.
- **Focus:** borde azul de pago texto y anillo de 2 px.
- **Error / Disabled:** borde y mensaje en negativo bajo el campo, el mensaje dice el problema y cómo arreglarlo.

### Navigation
- Barra inferior de cinco destinos: Inicio, Quincena, Deudas, Futuro, Más (desde v2, Futuro reemplaza a Metas e incluye proyección, metas, fondos y foto mensual; icono `chart-line-up`). Icono Phosphor (peso bold, 24 px, SVG en línea) sobre etiqueta. Activo: tinta y una línea superior de 2 px en tinta; inactivo: tinta suave. Cada destino ocupa al menos 44 px de alto.

### Tira del reparto (componente propio)
La quincena dibujada como una sola barra horizontal de 12 px de alto y radio píldora, partida en segmentos proporcionales a cada bolsillo, con su color tierra y 2 px de separación. Debajo, la leyenda: punto de color, bolsillo, monto. En el formulario de reparto se actualiza en vivo con htmx junto al estado de cuadre ("Cuadra: 0" en positivo, "Faltan 120.000" o "Sobran 120.000" en negativo). En el tablero resume el último reparto. Si sobra plata, el segmento sobrante se dibuja con línea punteada en negativo.

### Barra de meta
Riel de 8 px en superficie alta con relleno salvia; a la derecha el porcentaje entero ("71 %") y debajo "Faltan 5.000.000".

### Gráfica de patrimonio (ECharts)
Línea de 2 px en tinta, área sin relleno, línea de cero de 1 px en tinta tenue, puntos solo en las fotos; ejes en etiqueta tinta tenue, sin cuadrícula vertical. Tooltip en superficie alta. Colores tomados de las variables CSS del tema activo.

### Fila plan vs real (v2)
Misma fila de montos de v1. A la izquierda, concepto y debajo bolsillo con su punto. A la derecha, el real como cifra principal y debajo "plan 700.000" en tinta tenue. Si hay diferencia, va en la misma línea pequeña con signo ("-35.000" en negativo, "+20.000" en positivo); nunca solo color. Al final de la fila, un botón secundario de 44 px "Pagada" con icono `check`: sin marcar es superficie alta con tinta suave; marcada muestra el icono en positivo y el texto "Pagada". Tocar el monto abre un campo en línea para el real (htmx, sin modal). Un bolsillo sin registro dice "sin registrar" en tinta tenue, sin diferencia.

### Gasto rápido (v2)
Una sola pantalla, sin tarjetas anidadas. Arriba, el campo de monto en tamaño cifra hero (2.5rem, tabular, alineado a la derecha, `inputmode="numeric"`, con foco al abrir). Debajo, los bolsillos como segmentos de 48 px con su punto de color y, luego, las categorías como chips de 44 px en rejilla de 3 columnas (texto, sin emojis). La nota va en un `details` cerrado. Botón primario "Guardar gasto" a ancho completo, fijo sobre la barra inferior como el panel de cuadre. Se abre desde un botón secundario "Gasto" con icono `plus` en la cabecera de Quincena y en Inicio.

### Etiqueta "estimado" (v2)
Píldora en superficie alta con texto "estimado" en tinta tenue, 0.8125rem, sin color de dato. Acompaña a todo monto que no sea dato (eventos, fondos, parámetros). En la gráfica, los valores estimados se nombran en el tooltip.

### Tarjeta de fondo de previsión (v2)
Fila como la barra de meta: nombre (con etiqueta "estimado" si aplica), riel de 8 px con el color del bolsillo del fondo, acumulado de objetivo y debajo "28.609 por quincena, 12 quincenas hasta el 15 abr 2027". Sin fecha o sin monto: riel punteado en línea y el texto "falta la fecha" o "falta el monto" con un enlace "Completar".

### Indicadores del mes (v2)
Una lista de filas dentro de una tarjeta, no una rejilla de cifras grandes: nombre a la izquierda y valor tabular a la derecha (tasa de ahorro "22 %", colchón "4,1 meses", deuda / ingreso "20 %", gasto libre "1.100.000 de 946.690"). Debajo de cada valor, una línea tenue que lo explica en palabras. Solo el gasto libre excedido usa negativo.

### Gráfica de proyección (ECharts, v2)
Meses en el eje x ("nov 26"). Patrimonio en línea de 2 px en tinta; fondo de emergencia en línea salvia; deuda total en línea arcilla. Meta 1 y M4 como líneas horizontales punteadas de 1 px en tinta tenue con su nombre al final. Eventos como puntos pequeños sobre el eje con su nombre en el tooltip. Si el escenario incapacidad está activo, una banda vertical en negativo al 8 % de opacidad. Debajo de la gráfica, en texto, las fechas de cero de cada deuda (la gráfica nunca es el único lugar donde está el dato). Los controles del escenario son campos y segmentos estándar encima de la gráfica que la recalculan con htmx.

### Avalancha frente a bola de nieve (v2)
Dos columnas en escritorio y apiladas en el celular, cada una con el orden de pago, el mes libre de deudas y los intereses totales. La diferencia se dice en una frase ("Avalancha ahorra 33.398 en intereses"), sin resaltar una columna con color.

### Revisión mensual (v2)
Cinco preguntas en un solo formulario: cuatro `textarea` de 3 líneas y la última como segmentos del 1 al 5. Botón primario "Guardar revisión".

## Rendimiento

**Creative North Star: "El tatami después de la sesión"**

Terminó la clase o la última serie. Todavía hay calor en el cuerpo y quieres ver, en dos segundos, cómo va la semana. Rendimiento es la misma mesa cálida de finanzas (mismos tokens, misma Geist, mismas reglas de foco, línea y tema), pero más viva: los datos se mueven, los anillos se llenan, las cifras son grandes. La referencia es Garmin Connect: tarjetas de vistazo con un anillo y una cifra al centro, una fila de esenciales, una gráfica en foco y un calendario con barras de color por actividad. De taste-skill `high-end-visual-design` toma la coreografía de movimiento (curva de resorte, entradas escalonadas, solo `transform` y `opacity`), el mosaico asimétrico en escritorio y el aire generoso; **no** toma sombras, doble capa (double-bezel), sobretítulos, vidrio con blur ni barras flotantes, porque rompen las reglas de arriba.

Marca de la app: **Atlas**, arriba a la izquierda, con el selector de módulo (Finanzas, Rendimiento) a la derecha.

### Colores de dato (solo en datos, nunca en botones ni fondos grandes)

- **Disciplinas (categórico):** fuerza mostaza `#ddaa61` / `#8c5c10`; judo agua `#7fa8b8` / `#2f6378`; BJJ ciruela `#b48aa8` / `#7a4a6e`; Muay Thai arcilla `#d68b7a` / `#94473a`; cardio y caminatas salvia `#9fb08a` / `#4d5f4e`; otro piedra `#bfb8ac` / `#5f5b55`. Todos con 5,4:1 o más sobre superficie y superficie alta en los dos temas. Una sesión de Polar sin confirmar se dibuja con el color de la disciplina sugerida (solo existen judo y BJJ) y se confirma por semana.
- **Zonas de FC (rampa brasa, un solo tono que sube de intensidad):** Z1 `#7a6c55`, Z2 `#9a7f55`, Z3 `#bb9257`, Z4 `#dba65c`, Z5 `#f4c88a` en oscuro; en claro, de `#a28456` a `#462b05`. Cada zona tiene 3:1 o más sobre la superficie. Nunca rojo ni verde: siguen reservados para el signo.
- **Agua no es azul de acción.** El azul de pago sigue siendo uno por pantalla, en la acción que guarda ("Guardar sesión", "Guardar test").
- Muay Thai (arcilla) se parece al negativo; por eso un delta nunca va solo con color (ver Deltas).

### Tipografía expresiva

- **Cifra hero de rendimiento:** 3rem, 500, -0.035em, `tnum`. Una por pantalla (por ejemplo, minutos de la semana en Hoy, el CMJ en Tests).
- **Cifra de tarjeta:** 2rem, 500, -0.03em, `tnum`, centrada en anillos o arriba a la izquierda en tarjetas de dato. En rendimiento **sí** se permite una cifra grande por tarjeta de vistazo: es la excepción explícita a "una cifra hero por pantalla" de finanzas.
- Unidades en tamaño etiqueta y tinta suave junto a la cifra ("48,30 cm", "320 min"), nunca del mismo tamaño.
- **Escala compacta de rendimiento** (documentada en la auditoría 7.2, 2026-10-22). Rendimiento mete más datos por pantalla que finanzas y usa cuatro pasos más, además de la jerarquía general:
  - **Micro** (0.75rem): números del calendario, subtextos de chips, marcas como "Hoy", registros técnicos.
  - **Nota** (0.875rem): textos de apoyo dentro de tarjetas, como notas, detalles de filas y listas de lo que se envía.
  - **Cuerpo compacto** (0.9375rem): valores y textos en filas densas, como el plan día por día o las medidas junto a una foto.
  - **Título de tarjeta** (1.125rem): el nombre de una tarjeta dentro de una lista, como una comida o una tarjeta del guion, y la cifra mini.

  Ningún otro tamaño suelto: un paso nuevo se agrega aquí primero.

### Layout

- **Celular (360 px):** una columna, gutter de 16 px, 24 px entre tarjetas. La pantalla Hoy, de arriba abajo:
  1. Cabecera: título "Hoy", fecha y un botón secundario de icono para sincronizar (`arrows-clockwise`), con "Última sincronización: hace 2 días" debajo en tinta tenue.
  2. **De un vistazo:** rejilla de 2 por 2 tarjetas (minutos de la semana, carga total, combate, molestia del hombro). Cada una: icono de 20 px en su color de dato y nombre en etiqueta; al centro un anillo con la cifra; debajo, la comparación con la semana anterior.
  3. **Esenciales:** fila de 4 mini anillos de 64 px (sueño, HRV, FC en reposo, pasos), cada uno con su cifra dentro y el nombre debajo. Sin dato: anillo punteado y "sin dato".
  4. **En foco:** carrusel de tarjetas a ancho completo con `scroll-snap` (tiempo por zona de la semana, molestia del hombro en el tiempo, último test), con puntos de posición debajo. Es el único desplazamiento horizontal permitido, dentro del componente y nunca en la página.
  5. **Calendario del mes:** ver abajo.
  6. **Ayer:** lista de filas con icono, nombre y valor (sesiones, minutos, FC, sueño), como en Garmin.
- **Escritorio (desde 64rem):** contenedor `amplio` de 80rem en una rejilla de 12 columnas con mosaico asimétrico: vistazo en 8 columnas (4 tarjetas en fila) y esenciales en 4 columnas apilados; en foco en 8 columnas con dos gráficas lado a lado (sin carrusel); calendario en 4 columnas; año de calor a ancho completo abajo. Huecos de 24 px. Entre 48rem y 64rem, la misma rejilla en 2 columnas.
- Más aire que finanzas: 40 px entre bloques en el celular y 56 px en escritorio.

### Componentes de rendimiento

- **Anillo:** SVG con riel de 8 px en superficie alta y arco de 8 px con puntas redondeadas en el color de dato; cifra de tarjeta al centro y, debajo, la meta o la unidad en tinta suave. Variante **medidor** de 270 grados partido en las cinco zonas de FC (como el medidor de FC de Garmin), con una marca en la zona actual. Variante **mini** de 64 px con riel de 5 px. Siempre con `role="img"` y `aria-label` con el dato en palabras.
- **Calendario del mes (Garmin):** 7 columnas lunes a domingo; cada día es una celda en superficie alta de radio 6 px con el número arriba y hasta 4 barras de 6 px por sesión en el color de su disciplina; si hay más, "+2" abajo a la derecha en azul de pago texto. Hoy con borde de 1 px en tinta. Días sin sesión: solo el número; días fuera del mes en fondo. Cabe a 360 px (celdas de unos 44 px) y reemplaza al calendario de 16 semanas en el celular. Tocar un día abre sus sesiones.
- **Año de calor (escritorio):** cuadrícula de 53 semanas por 7 días en SVG desde el servidor; intensidad por minutos con la rampa brasa; meses en etiqueta tinta tenue arriba. En el celular no se muestra.
- **Deltas:** flecha (`arrow-up-right` o `arrow-down-right`), signo y número, más el porcentaje en tinta suave ("+4,59 cm +9,7 %"). El color sigue la dirección de la métrica: positivo si mejora, negativo si empeora, tinta si la métrica es neutra (volumen, carga total, sesiones). Nunca solo color.
- **Comparar semanas:** en el celular, filas (métrica a la izquierda; semana A, semana B y delta a la derecha) con dos barras finas pareadas debajo, A en tinta tenue y B en tinta. En escritorio, small multiples: una mini gráfica por métrica en una rejilla de 4 columnas con el mismo eje para A y B.
- **Radar de tests:** ECharts, dos polígonos (fecha anterior en tinta tenue con relleno al 10 %, fecha nueva en tinta con relleno al 18 %), nombres cortos ("CMJ", "Dina.", "1RM", "Sprint", "Movil."), 100 % = mejor marca propia. Debajo, siempre, la tabla de valores.
- **Gráfica en foco:** área con degradado vertical de la tinta al 22 % a transparente bajo una línea de 2 px (el área de Body Battery de Garmin); barras de zonas apiladas en la rampa brasa; punto final marcado. Es el único degradado permitido y vive dentro de la gráfica.
- **Tarjeta de vistazo:** la tarjeta de siempre (superficie, línea de 1 px, radio 12 px, sin sombra), con padding de 16 px y altura igual a la de su vecina de fila.
- **Registrar:** segmentos grandes de 56 px para elegir el tipo (Fuerza, Combate, Cardio), "Repetir la sesión anterior" como botón secundario arriba, series como filas con controles de más y menos de 44 px a cada lado de la cifra y "Guardar sesión" como único botón azul fijo sobre la barra inferior.
- **Iconos:** Phosphor bold como en finanzas (una sola familia en toda la app); 20 px en las tarjetas y en su color de dato.

### Movimiento

- **Curva de resorte:** `cubic-bezier(0.32, 0.72, 0, 1)` para todo; nunca `linear` ni `ease-in-out`. Duraciones: 180 ms en presión y hover, 420 ms en cambios de estado, 900 ms en el llenado de datos.
- **Llenado de anillos:** el arco crece de 0 a su valor animando `stroke-dashoffset` en 900 ms al entrar en pantalla (`IntersectionObserver`), con 60 ms de escalón entre tarjetas.
- **Conteo de cifras:** la cifra de tarjeta cuenta de 0 a su valor en el mismo tiempo que su anillo; el texto final está en el HTML desde el principio, así que sin JavaScript o para un lector de pantalla siempre dice el valor real.
- **Gráficas:** ECharts dibuja líneas y áreas de izquierda a derecha en 900 ms con `cubicOut`, y redibuja con el tema.
- **Entrada:** las tarjetas suben 12 px y pasan de opacidad 0 a 1 en 420 ms, escalonadas, solo en la primera carga (no tras un intercambio de htmx). Sin blur.
- **Presión:** `scale(0.98)` en 180 ms, como en finanzas.
- **`prefers-reduced-motion: reduce`:** nada se mueve; anillos, cifras y gráficas aparecen ya en su valor final.

### Estados vacíos

Cada bloque sin datos dice qué falta y ofrece la acción: "Sin sesiones esta semana" con "Registrar"; "Sensores sin sincronizar desde el 11 oct" con "Sincronizar". Anillo punteado en línea y la palabra "sin dato", nunca un 0.

### Do's and Don'ts de rendimiento

- **Do** una cifra grande por tarjeta de vistazo y una cifra hero por pantalla.
- **Do** animar solo `transform`, `opacity` y el trazo de los SVG, y respetar `prefers-reduced-motion`.
- **Do** que cada gráfica tenga su dato en texto cerca (tabla, fila o `aria-label`).
- **Don't** usar los rojos, verdes, azules y naranjas saturados de Garmin: se traducen a la paleta tierra y a la rampa brasa.
- **Don't** usar sombras, vidrio, blur, doble capa ni sobretítulos, aunque la skill los pida.
- **Don't** desplazamiento horizontal de página; el carrusel En foco es la única excepción, dentro del componente.

## Do's and Don'ts

### Do:
- **Do** alinear todo monto a la derecha con cifras tabulares y separador de miles con punto.
- **Do** usar un solo botón azul por pantalla, en la acción que mueve plata.
- **Do** mostrar siempre el signo y el estado del cuadre con palabra y color ("Cuadra: 0", "Faltan 120.000"), nunca solo con color.
- **Do** mantener objetivos táctiles de 44 px o más y nada de desplazamiento horizontal a 360 px.
- **Do** tematizar selección de texto, foco, caret y barras de desplazamiento con la paleta.

### Don't:
- **Don't** usar Inter, Roboto ni Open Sans; ni sombras, degradados, vidrio o neón.
- **Don't** poner tonos tierra en botones o fondos grandes; viven en datos.
- **Don't** usar sobretítulos, números de sección, emojis ni el carácter de raya larga.
- **Don't** usar la plantilla de "número gigante con estadísticas debajo" en todas las tarjetas: una cifra hero por pantalla.
- **Don't** anidar tarjetas ni usar bordes laterales de color.
