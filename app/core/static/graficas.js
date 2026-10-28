// Cargador único de ECharts para los módulos de Atlas.
// Uso: Graficas.dibujar(elemento, function (v) { return opcionesDeECharts; })
// donde v("--tinta") lee una variable CSS del tema activo. La gráfica se redibuja
// al cambiar de tema y al cambiar el tamaño, y no anima con prefers-reduced-motion.
(function () {
  var URL = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js";
  var SRI = "sha384-Mx5lkUEQPM1pOJCwFtUICyX45KNojXbkWdYhkKUKsbv391mavbfoAmONbzkgYPzR";
  var estado = "sin-cargar", espera = [], vivas = [];
  var quieto = matchMedia("(prefers-reduced-motion: reduce)");

  function cargar(listo) {
    if (window.echarts) return listo();
    espera.push(listo);
    if (estado !== "sin-cargar") return;
    estado = "cargando";
    var s = document.createElement("script");
    s.src = URL; s.integrity = SRI; s.crossOrigin = "anonymous";
    s.onload = function () { estado = "lista"; espera.splice(0).forEach(function (f) { f(); }); };
    s.onerror = function () {
      estado = "sin-cargar"; espera = [];
      vivas.forEach(function (g) { g.el.dataset.error = "1"; });
    };
    document.head.appendChild(s);
  }

  function variable(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

  function pintar(g) {
    if (g.chart) g.chart.dispose();
    g.chart = echarts.init(g.el, null, { renderer: "svg" });
    var op = g.fn(variable);
    op.animation = !quieto.matches && op.animation !== false;
    g.chart.setOption(op);
  }

  function limpiar() {
    vivas = vivas.filter(function (g) {
      if (document.contains(g.el)) return true;
      if (g.chart) g.chart.dispose();
      return false;
    });
  }

  window.Graficas = {
    dibujar: function (el, fn) {
      if (!el) return;
      limpiar();
      var g = { el: el, fn: fn, chart: null };
      vivas.push(g);
      cargar(function () { if (document.contains(el)) pintar(g); });
    },
    variable: variable,
  };

  new MutationObserver(function () {
    limpiar();
    if (window.echarts) vivas.forEach(pintar);
  }).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  quieto.addEventListener("change", function () { if (window.echarts) vivas.forEach(pintar); });
  addEventListener("resize", function () { vivas.forEach(function (g) { if (g.chart) g.chart.resize(); }); });
  document.addEventListener("htmx:afterSettle", limpiar);
})();
