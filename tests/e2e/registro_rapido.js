// Prueba de extremo a extremo del criterio de la fase 1: registrar una sesión de fuerza de 4 ejercicios
// y una de judo en menos de 2 minutos cada una, a 360 px.
// Uso (con el servidor de desarrollo corriendo): make e2e   (URL=http://127.0.0.1:8001 PIN=1234)
// Cuenta los toques y escribe, y estima el tiempo de una persona a 2 s por acción.
const { chromium } = require("playwright");
const URL = process.env.URL || "http://127.0.0.1:8001";
const PIN = process.env.PIN || "1234";
const SEG_POR_ACCION = 2;

(async () => {
  const b = await chromium.launch({ headless: true });
  const ctx = await b.newContext({ viewport: { width: 360, height: 780 }, deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  const errores = [];
  p.on("pageerror", (e) => errores.push(String(e)));
  p.on("response", (r) => { if (r.status() >= 500) errores.push(r.status() + " " + r.url()); });
  let acciones = 0;
  // Tras cada acción se espera la respuesta y a que htmx conecte el contenido nuevo (como haría una persona).
  const toca = async (f) => { acciones++; if (process.env.DEPURAR) console.log("acción", acciones, p.url()); await f(); await p.waitForLoadState("networkidle"); await p.waitForTimeout(250); };
  p.on("dialog", (d) => d.accept());
  await p.goto(URL + "/login"); await p.fill("#pin", PIN); await p.click("button[type=submit]");
  // Si quedó un borrador de hoy de una corrida anterior, se descarta para empezar limpio.
  for (const tipo of ["fuerza", "combate"]) {
    await p.goto(URL + "/rendimiento/registrar");
    if (await p.locator(`button[value=${tipo}] small`).count()) {
      await p.click(`button[value=${tipo}]`);
      await p.click("text=Descartar sesión");
      await p.waitForURL(/registrar/);
    }
  }

  // Fuerza: 4 ejercicios x 4 series; en cada uno se escribe la carga de la primera serie y se agregan 3 series.
  acciones = 0;
  await p.goto(URL + "/rendimiento/registrar");
  await toca(() => p.click("button[value=fuerza]"));
  for (const [nombre, opcion] of [["Sentadilla trasera"], ["Peso muerto rumano"], ["Hip thrust"],
                                  ["Remo en máquina", "Remo en máquina (carga el hombro)"]]) {
    await toca(() => p.selectOption("#ej-nuevo", { label: opcion || nombre }));
    const sel = `.ejercicio:has(h3:text-is("${nombre}"))`;
    const bloque = p.locator(sel);
    await bloque.waitFor();
    await toca(async () => { await p.locator(sel).locator("input[name=carga]").first().fill("60"); await p.locator(sel).locator("input[name=carga]").first().dispatchEvent("change"); });
    for (let i = 0; i < 3; i++) await toca(() => p.locator(sel).locator(".mas-serie").click());
  }
  await toca(() => p.locator(".segmentos.escala.once label", { hasText: /^3$/ }).click());
  await toca(() => p.click("text=Guardar sesión"));
  await p.waitForURL(/guardada=/);
  const fuerza = acciones;

  // Judo: bloque de técnica con 2 técnicas y randori con un resultado y un rival.
  acciones = 0;
  await toca(() => p.click("button[value=combate]"));
  await toca(() => p.click("button[value=tecnica]"));
  for (const [busca, tecnica] of [["uchi", /^Uchi mata/], ["cruzado", /agarre cruzado/]]) {
    await toca(() => p.locator(".bloque-combate").last().locator("input[type=search]").fill(busca));
    await p.waitForTimeout(400);
    await toca(() => p.locator(".bloque-combate").last().locator(".chip", { hasText: tecnica }).click());
  }
  await toca(() => p.click("button[value=randori]"));
  await toca(() => p.locator(".bloque-combate").last().locator("label", { hasText: "Más pesado" }).click());
  await toca(() => p.locator(".bloque-combate").last().locator("input[type=search]").fill("o uchi"));
  await p.waitForTimeout(400);
  await toca(() => p.locator(".bloque-combate").last().locator(".chip", { hasText: /^O uchi gari/ }).click());
  await toca(() => p.locator(".bloque-combate").last().locator(".entrada").last().locator("label.r-funciono").click());
  await toca(() => p.click("text=Guardar sesión"));
  await p.waitForURL(/guardada=/);
  const judo = acciones;

  const sw = await p.evaluate(() => document.documentElement.scrollWidth);
  await b.close();
  const linea = (n, k) => `${n}: ${k} acciones, unos ${k * SEG_POR_ACCION} s a ${SEG_POR_ACCION} s por acción`;
  console.log(linea("Fuerza (4 ejercicios, 16 series)", fuerza));
  console.log(linea("Judo (técnica y randori)", judo));
  console.log("Ancho de página a 360 px:", sw, "| errores:", errores.length ? errores.join("; ") : "ninguno");
  const ok = fuerza * SEG_POR_ACCION < 120 && judo * SEG_POR_ACCION < 120 && sw === 360 && !errores.length;
  console.log(ok ? "OK: las dos sesiones caben en menos de 2 minutos." : "FALLA");
  process.exit(ok ? 0 : 1);
})();
