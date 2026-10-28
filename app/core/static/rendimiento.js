// Gráficas y movimiento de Rendimiento (DESIGN.md, sección Rendimiento).
// Los datos vienen en <script type="application/json"> junto a cada gráfica; los colores, de las
// variables CSS del tema activo (Graficas redibuja al cambiar de tema).
(function () {
  var MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  var miles = function (s) { return s.replace(/\B(?=(\d{3})+(?!\d))/g, "."); };
  // Milésimas a texto colombiano: 47130 -> "47,13"
  function dec(mil, max) {
    max = max == null ? 2 : max;
    var n = Math.round(mil / Math.pow(10, 3 - max)) / Math.pow(10, max);
    var partes = n.toFixed(max).split(".");
    var frac = (partes[1] || "").replace(/0+$/, "");
    return miles(partes[0]) + (frac ? "," + frac : "");
  }
  function fecha(p) {
    var x = p.fecha.split("-");
    var mes = MESES[+x[1] - 1] + " " + x[0].slice(2);
    return (p.aprox ? "~" : "") + (p.precision === "mes" ? mes : +x[2] + " " + mes);
  }
  function datos(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }
  function ejeX(v, categorias) {
    return { type: "category", data: categorias, boundaryGap: false, axisTick: { show: false },
      axisLine: { lineStyle: { color: v("--linea") } },
      axisLabel: { color: v("--tinta-tenue"), fontFamily: "Geist", hideOverlap: true } };
  }
  function ejeY(v, unidad) {
    return { type: "value", scale: true, splitNumber: 3, splitLine: { lineStyle: { color: v("--linea") } },
      axisLabel: { color: v("--tinta-tenue"), fontFamily: "Geist", formatter: function (n) { return dec(n, 1); } },
      name: unidad || "", nameTextStyle: { color: v("--tinta-tenue"), fontFamily: "Geist", align: "left" } };
  }
  function tooltip(v, formatter) {
    return { trigger: "axis", backgroundColor: v("--superficie-alta"), borderColor: v("--linea"),
      textStyle: { color: v("--tinta"), fontFamily: "Geist" }, formatter: formatter };
  }
  function alfa(color, a) {
    var m = color.match(/^#([0-9a-f]{6})$/i);
    if (!m) return color;
    var n = parseInt(m[1], 16);
    return "rgba(" + (n >> 16) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }

  var R = window.Rendimiento = {};

  // Evolución de una medida: línea de 2 px, área degradada, puntos y la mejor marca señalada.
  R.evolucion = function (id, opciones) {
    var d = datos(id + "-datos");
    var el = document.getElementById(id);
    if (!d || !el || d.length < 1) return;
    opciones = opciones || {};
    Graficas.dibujar(el, function (v) {
      var color = v(opciones.color || "--tinta");
      var valores = d.map(function (p) { return p.v; });
      var mejor = opciones.direccion === "menos" ? Math.min.apply(null, valores) : Math.max.apply(null, valores);
      return {
        animationDuration: 900, animationEasing: "cubicOut",
        grid: { left: 4, right: 28, top: 44, bottom: 4, containLabel: true },
        tooltip: tooltip(v, function (ps) { return ps[0].name + "<br><b>" + dec(ps[0].value) + " " + (opciones.unidad || "") + "</b>"; }),
        xAxis: ejeX(v, d.map(fecha)), yAxis: ejeY(v),
        series: [{
          type: "line", data: valores, smooth: 0.25, symbol: "circle", symbolSize: 8,
          lineStyle: { width: 2, color: color }, itemStyle: { color: color, borderColor: v("--superficie"), borderWidth: 2 },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: alfa(color, 0.22) }, { offset: 1, color: alfa(color, 0) }]) },
          label: { show: d.length <= 8, position: "top", color: v("--tinta-suave"), fontFamily: "Geist",
            formatter: function (p) { return dec(p.value); } },
          markPoint: opciones.direccion === "neutra" || valores.length < 2 ? undefined : { symbol: "pin", symbolSize: 0, silent: true,
            label: { show: true, color: v("--tinta"), fontFamily: "Geist", fontWeight: 600, offset: [0, -34],
              formatter: "Mejor" },
            data: [{ coord: [valores.indexOf(mejor), mejor] }] },
        }],
      };
    });
  };

  // Pesajes de la competencia: línea neutra, el límite punteado y, si el plan la trae, la meta en otra línea.
  R.pesajes = function (id, opciones) {
    var d = datos(id + "-datos");
    var el = document.getElementById(id);
    if (!d || !el || d.length < 1) return;
    opciones = opciones || {};
    var valores = d.map(function (p) { return p.v; });
    var refs = [opciones.limite, opciones.meta].filter(function (x) { return x != null; });
    var todos = valores.concat(refs);
    var min = Math.floor(Math.min.apply(null, todos) / 500) * 500 - 500;
    var max = Math.ceil(Math.max.apply(null, todos) / 500) * 500 + 500;
    Graficas.dibujar(el, function (v) {
      var color = v("--tinta");
      var lineas = [];
      if (opciones.limite != null) lineas.push({ yAxis: opciones.limite, lineStyle: { color: v("--tinta-suave"), type: "dashed", width: 1.5 },
        label: { formatter: "Límite " + dec(opciones.limite, 1), color: v("--tinta-suave") } });
      if (opciones.meta != null) {
        var f = opciones.metaFecha.split("-");
        lineas.push({ yAxis: opciones.meta, lineStyle: { color: v("--tinta-tenue"), type: "dotted", width: 1.5 },
          label: { formatter: "Meta " + (+f[2]) + " " + MESES[+f[1] - 1] + ": " + dec(opciones.meta, 1), color: v("--tinta-tenue") } });
      }
      return {
        animationDuration: 900, animationEasing: "cubicOut",
        grid: { left: 4, right: 8, top: 24, bottom: 4, containLabel: true },
        tooltip: tooltip(v, function (ps) { return ps[0].name + "<br><b>" + dec(ps[0].value, 1) + " kg</b>"; }),
        xAxis: ejeX(v, d.map(fecha)),
        yAxis: Object.assign(ejeY(v), { scale: false, min: min, max: max }),
        series: [{
          type: "line", data: valores, smooth: 0.25, symbol: "circle", symbolSize: 8,
          lineStyle: { width: 2, color: color }, itemStyle: { color: color, borderColor: v("--superficie"), borderWidth: 2 },
          label: { show: d.length <= 8, position: "top", color: v("--tinta-suave"), fontFamily: "Geist",
            formatter: function (p) { return dec(p.value, 1); } },
          markLine: { silent: true, symbol: "none", data: lineas,
            label: { position: "insideStartTop", fontFamily: "Geist", fontSize: 11 } },
        }],
      };
    });
  };

  // Checklist de la competencia: al marcar, htmx reemplaza la lista; el foco vuelve al mismo ítem (id estable).
  var focoChecklist = null;
  document.addEventListener("htmx:beforeRequest", function (e) {
    var b = e.detail.elt && e.detail.elt.querySelector && e.detail.elt.querySelector(".fila-check");
    focoChecklist = b && e.detail.elt.closest("#checklist-lista") ? b.id : null;
  });
  document.addEventListener("htmx:afterSettle", function () {
    if (!focoChecklist) return;
    var b = document.getElementById(focoChecklist);
    focoChecklist = null;
    if (b) b.focus();
  });

  // Curva carga-velocidad: una línea por fecha; la última en tinta y las anteriores atenuadas.
  R.curvas = function (id) {
    var d = datos(id + "-datos");
    var el = document.getElementById(id);
    if (!d || !el || !d.length) return;
    // El eje llega hasta la carga más alta medida (desde 2026-10-19 hay 75 y 85 kg), redondeada a 10.
    var tope = 10 * Math.ceil(Math.max.apply(null, d.map(function (c) {
      return Math.max.apply(null, c.puntos.map(function (p) { return p[0]; })); })) / 10);
    Graficas.dibujar(el, function (v) {
      var tinta = v("--tinta"), tenue = v("--tinta-tenue");
      var n = d.length;
      return {
        animationDuration: 900, animationEasing: "cubicOut",
        grid: { left: 4, right: 16, top: el.clientWidth < 520 && n > 3 ? 62 : 36, bottom: 4, containLabel: true },
        legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 14, itemHeight: 4,
          textStyle: { color: v("--tinta-suave"), fontFamily: "Geist" } },
        tooltip: { trigger: "axis", backgroundColor: v("--superficie-alta"), borderColor: v("--linea"),
          textStyle: { color: v("--tinta"), fontFamily: "Geist" },
          formatter: function (ps) {
            return ps[0].axisValue + " kg<br>" + ps.map(function (p) {
              return p.marker + p.seriesName + ": <b>" + dec(p.value[1]) + " m/s</b>"; }).join("<br>");
          } },
        xAxis: { type: "value", min: 10, max: Math.max(70, tope), interval: el.clientWidth < 520 && tope > 70 ? 20 : 10, axisTick: { show: false },
          axisLine: { lineStyle: { color: v("--linea") } }, splitLine: { show: false },
          axisLabel: { color: tenue, fontFamily: "Geist", formatter: "{value} kg" } },
        yAxis: ejeY(v, "m/s"),
        series: d.map(function (c, i) {
          var ultima = i === n - 1;
          var color = ultima ? tinta : alfa(tenue, 0.35 + 0.5 * (i / Math.max(n - 1, 1)));
          return { name: fecha(c), type: "line", smooth: 0.2, symbol: "circle", symbolSize: ultima ? 8 : 5,
            z: ultima ? 3 : 2, data: c.puntos.map(function (p) { return [p[0], p[1]]; }),
            lineStyle: { width: ultima ? 2.5 : 1.5, color: color }, itemStyle: { color: color },
            label: { show: ultima, position: "top", color: v("--tinta-suave"), fontFamily: "Geist",
              formatter: function (p) { return dec(p.value[1]); } } };
        }),
      };
    });
  };

  // Barras de una medida por fecha; la última en su color de dato y las demás en superficie alta.
  R.barras = function (id, opciones) {
    var d = datos(id + "-datos");
    var el = document.getElementById(id);
    if (!d || !el || !d.length) return;
    opciones = opciones || {};
    Graficas.dibujar(el, function (v) {
      var color = v(opciones.color || "--r-fuerza");
      return {
        animationDuration: 900, animationEasing: "cubicOut",
        grid: { left: 4, right: 4, top: 24, bottom: 4, containLabel: true },
        tooltip: tooltip(v, function (ps) { return ps[0].name + "<br><b>" + dec(ps[0].value) + " " + (opciones.unidad || "") + "</b>"; }),
        xAxis: { type: "category", data: d.map(fecha), axisTick: { show: false }, axisLine: { show: false },
          axisLabel: { color: v("--tinta-tenue"), fontFamily: "Geist", hideOverlap: true } },
        yAxis: { type: "value", show: false, min: 0 },
        series: [{ type: "bar", barWidth: "56%", data: d.map(function (p, i) {
          return { value: p.v, itemStyle: { color: i === d.length - 1 ? color : v("--superficie-alta"), borderRadius: [6, 6, 2, 2] } };
        }), label: { show: true, position: "top", color: v("--tinta-suave"), fontFamily: "Geist",
          formatter: function (p) { return dec(p.value, 1); } } }],
      };
    });
  };

  // Tiempo por zona: barras con la rampa brasa, en minutos.
  R.zonas = function (id) {
    var d = datos(id + "-datos");
    var el = document.getElementById(id);
    if (!d || !el) return;
    Graficas.dibujar(el, function (v) {
      return {
        animationDuration: 900, animationEasing: "cubicOut", grid: { left: 0, right: 0, top: 20, bottom: 24 },
        xAxis: { type: "category", data: ["Z1", "Z2", "Z3", "Z4", "Z5"], axisLine: { show: false }, axisTick: { show: false },
          axisLabel: { color: v("--tinta-tenue"), fontFamily: "Geist" } },
        yAxis: { type: "value", show: false },
        series: [{ type: "bar", barWidth: "58%", data: d.map(function (s, i) {
          return { value: Math.round(s / 60), itemStyle: { color: v("--r-z" + (i + 1)), borderRadius: [6, 6, 2, 2] } }; }),
          label: { show: true, position: "top", color: v("--tinta-suave"), fontFamily: "Geist" } }],
      };
    });
  };

  // Minigráfica sin ejes para los small multiples.
  R.mini = function (id, opciones) {
    var d = datos(id + "-datos");
    var el = document.getElementById(id);
    if (!d || !el || d.length < 2) return;
    opciones = opciones || {};
    Graficas.dibujar(el, function (v) {
      var color = v(opciones.color || "--tinta");
      return {
        animationDuration: 900, animationEasing: "cubicOut", grid: { left: 2, right: 6, top: 6, bottom: 2 },
        tooltip: tooltip(v, function (ps) { return ps[0].name + "<br><b>" + dec(ps[0].value) + " " + (opciones.unidad || "") + "</b>"; }),
        xAxis: { type: "category", data: d.map(fecha), show: false, boundaryGap: false },
        yAxis: { type: "value", show: false, scale: true },
        series: [{ type: "line", data: d.map(function (p) { return p.v; }), smooth: 0.3, symbol: "circle",
          symbolSize: function (_, p) { return p.dataIndex === d.length - 1 ? 7 : 0; },
          lineStyle: { width: 2, color: color }, itemStyle: { color: color },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: alfa(color, 0.18) }, { offset: 1, color: alfa(color, 0) }]) } }],
      };
    });
  };

  // Radar: anterior en tinta tenue con relleno al 10 %, última en tinta con relleno al 18 %. 100 = mejor marca propia.
  R.radar = function (id) {
    var d = datos(id + "-datos");
    var el = document.getElementById(id);
    if (!d || !el || d.length < 3) return;
    Graficas.dibujar(el, function (v) {
      var tinta = v("--tinta"), tenue = v("--tinta-tenue");
      return {
        animationDuration: 900, animationEasing: "cubicOut",
        legend: { bottom: 0, icon: "roundRect", itemWidth: 14, itemHeight: 4, textStyle: { color: v("--tinta-suave"), fontFamily: "Geist" } },
        tooltip: { backgroundColor: v("--superficie-alta"), borderColor: v("--linea"), textStyle: { color: tinta, fontFamily: "Geist" } },
        radar: { radius: el.clientWidth < 420 ? "54%" : "64%", center: ["50%", "46%"], splitNumber: 4,
          indicator: d.map(function (x) { return { name: x.nombre, max: 100 }; }),
          axisName: { color: v("--tinta-suave"), fontFamily: "Geist" },
          splitLine: { lineStyle: { color: v("--linea") } }, splitArea: { show: false },
          axisLine: { lineStyle: { color: v("--linea") } } },
        series: [{ type: "radar", symbol: "circle", symbolSize: 5, data: [
          { name: "Anterior", value: d.map(function (x) { return x.pa; }),
            lineStyle: { color: tenue, width: 1.5 }, itemStyle: { color: tenue }, areaStyle: { color: alfa(tenue, 0.10) } },
          { name: "Última", value: d.map(function (x) { return x.pu; }),
            lineStyle: { color: tinta, width: 2 }, itemStyle: { color: tinta }, areaStyle: { color: alfa(tinta, 0.18) } },
        ] }],
      };
    });
  };

  // Cifras que cuentan desde 0 y entradas escalonadas al entrar en pantalla (sin movimiento si se pide menos).
  R.animarEntrada = function (raiz) {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) return;
    var bloques = (raiz || document).querySelectorAll(".t-dato, .esencial, .t-foco, .calendario, .entra-r");
    if (!bloques.length) return;
    document.body.classList.add("anima");
    var obs = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (!e.isIntersecting) return;
        obs.unobserve(e.target);
        var el = e.target;
        requestAnimationFrame(function () { el.classList.add("lleno"); });
        el.querySelectorAll("[data-contar]").forEach(function (c) {
          var fin = parseInt(c.dataset.contar, 10), decs = parseInt(c.dataset.decimales || "0", 10);
          if (isNaN(fin)) return;
          var resto = c.innerHTML.replace(/^[^<]*/, ""), t0 = null;
          var paso = function (t) {
            t0 = t0 || t;
            var p = Math.min((t - t0) / 900, 1), e2 = 1 - Math.pow(1 - p, 3);
            c.innerHTML = dec(fin * e2, decs) + resto;
            if (p < 1) requestAnimationFrame(paso);
          };
          requestAnimationFrame(paso);
        });
      });
    }, { threshold: 0.2 });
    bloques.forEach(function (b, i) { b.style.setProperty("--retardo", (i % 4) * 60 + "ms"); obs.observe(b); });
  };

  // Carrusel "En foco" del celular: los puntos siguen la tarjeta visible y al tocarlos llevan a ella.
  R.carrusel = function (sel) {
    var raiz = document.querySelector(sel);
    if (!raiz) return;
    var pista = raiz.querySelector(".foco"), puntos = raiz.querySelectorAll(".punto-foco");
    if (!pista || !puntos.length) return;
    var tarjetas = pista.children;
    var marcar = function (i) {
      puntos.forEach(function (p, j) { p.classList.toggle("activo", i === j); p.setAttribute("aria-selected", i === j ? "true" : "false"); });
    };
    var obs = new IntersectionObserver(function (es) {
      es.forEach(function (e) { if (e.isIntersecting && e.intersectionRatio > 0.6) marcar([].indexOf.call(tarjetas, e.target)); });
    }, { root: pista, threshold: [0.6] });
    [].forEach.call(tarjetas, function (t) { obs.observe(t); });
    puntos.forEach(function (p) {
      p.addEventListener("click", function () {
        var t = tarjetas[+p.dataset.i];
        if (t) pista.scrollTo({ left: t.offsetLeft - pista.offsetLeft, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      });
    });
  };

  R.dec = dec;
})();
