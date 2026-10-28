// Fotos antes y después: deslizador, línea de tiempo, miniaturas borrosas y cámara con guía de pose.
(function () {
  var quieto = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Deslizador: el rango se maneja con teclado y el arrastre horizontal sobre la foto mueve la línea;
  // touch-action: pan-y deja pasar el scroll vertical del celular.
  document.querySelectorAll("[data-ad]").forEach(function (caja) {
    var rango = caja.parentElement.querySelector(".ad-rango");
    var poner = function (pct) {
      pct = Math.max(0, Math.min(100, pct));
      caja.style.setProperty("--pos", pct + "%");
      if (rango) { rango.value = Math.round(pct); rango.setAttribute("aria-valuetext", Math.round(100 - pct) + " % " + (rango.dataset.texto || "después")); }
    };
    if (rango) rango.addEventListener("input", function () { poner(+rango.value); });
    var activo = false;
    var mover = function (ev) {
      var r = caja.getBoundingClientRect();
      poner(((ev.clientX - r.left) / r.width) * 100);
    };
    caja.addEventListener("pointerdown", function (ev) { activo = true; caja.setPointerCapture(ev.pointerId); mover(ev); });
    caja.addEventListener("pointermove", function (ev) { if (activo) mover(ev); });
    ["pointerup", "pointercancel"].forEach(function (t) { caja.addEventListener(t, function () { activo = false; }); });
  });

  // Línea de tiempo: fundido entre fotos de la misma pose; con menos movimiento, sin fundido ni reproducción sola.
  document.querySelectorAll("[data-linea]").forEach(function (escena) {
    var fotos = escena.querySelectorAll("img");
    var raiz = escena.parentElement;
    var rango = raiz.querySelector("[data-linea-rango]");
    var fecha = raiz.querySelector("[data-linea-fecha]");
    var boton = raiz.querySelector("[data-reproducir]");
    var reloj = null;
    var mostrar = function (i) {
      fotos.forEach(function (f, j) { f.classList.toggle("visible", i === j); });
      if (rango) rango.value = i;
      if (fecha) fecha.textContent = fotos[i].dataset.fecha;
    };
    var parar = function () { clearInterval(reloj); reloj = null; if (boton) boton.setAttribute("aria-label", "Reproducir la línea de tiempo"); };
    if (rango) rango.addEventListener("input", function () { parar(); mostrar(+rango.value); });
    if (boton) boton.addEventListener("click", function () {
      if (reloj) return parar();
      var i = 0;
      mostrar(i);
      boton.setAttribute("aria-label", "Pausar la línea de tiempo");
      reloj = setInterval(function () {
        i += 1;
        if (i >= fotos.length) return parar();
        mostrar(i);
      }, quieto ? 1500 : 1200);
    });
  });

  // Miniaturas borrosas hasta tocarlas (por si alguien mira la pantalla).
  document.querySelectorAll("[data-revelar]").forEach(function (b) {
    b.addEventListener("click", function () {
      var visto = b.classList.toggle("visto");
      b.setAttribute("aria-pressed", visto ? "true" : "false");
    });
  });

  // Subir desde la galería o los archivos: lista de lo elegido y, en el PC, arrastrar y soltar.
  var zona = document.querySelector("[data-zona]");
  if (zona) {
    var input = zona.querySelector("[data-archivos]"), lista = document.querySelector("[data-elegidas]");
    var enviar = document.querySelector("[data-enviar]");
    var pintar = function () {
      var n = input.files.length;
      lista.textContent = "";
      Array.prototype.slice.call(input.files, 0, 20).forEach(function (f) {
        var li = document.createElement("li");
        var img = document.createElement("img");
        img.alt = ""; img.width = 48; img.height = 64; img.src = URL.createObjectURL(f);
        img.onload = function () { URL.revokeObjectURL(img.src); };
        var nombre = document.createElement("span"); nombre.textContent = f.name;
        li.appendChild(img); li.appendChild(nombre); lista.appendChild(li);
      });
      if (enviar) enviar.textContent = n > 1 ? "Subir " + n + " fotos" : "Subir foto";
    };
    input.addEventListener("change", pintar);
    ["dragenter", "dragover"].forEach(function (t) {
      zona.addEventListener(t, function (ev) { ev.preventDefault(); zona.classList.add("encima"); });
    });
    ["dragleave", "dragend"].forEach(function (t) { zona.addEventListener(t, function () { zona.classList.remove("encima"); }); });
    zona.addEventListener("drop", function (ev) {
      ev.preventDefault(); zona.classList.remove("encima");
      var dt = new DataTransfer();
      Array.prototype.forEach.call(ev.dataTransfer.files, function (f) { if (/^image\//.test(f.type)) dt.items.add(f); });
      if (dt.files.length) { input.files = dt.files; pintar(); }
    });
    // Soltar una imagen fuera de la zona no debe abrirla en el navegador y perder la página
    ["dragover", "drop"].forEach(function (t) { addEventListener(t, function (ev) { if (!zona.contains(ev.target)) ev.preventDefault(); }); });
  }

  // Cámara con la foto anterior encima. Solo con HTTPS (el navegador no da la cámara por HTTP).
  var cam = document.querySelector("[data-camara]");
  if (!cam) return;
  var sinCamara = document.querySelector("[data-sin-camara]");
  if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    if (sinCamara) sinCamara.hidden = false;
    return;
  }
  cam.hidden = false;
  var video = cam.querySelector("video"), guia = cam.querySelector(".guia"), lienzo = cam.querySelector("canvas");
  var previa = cam.querySelector(".vista-previa"), cuenta = cam.querySelector("[data-cuenta]");
  var btnCapturar = cam.querySelector("[data-capturar]"), tras = cam.querySelector(".tras-captura");
  var opacidad = cam.querySelector("[data-opacidad]");
  var frontal = true, flujo = null, blob = null;

  var espejo = function () {
    var t = frontal ? "scaleX(-1)" : "none";
    video.style.transform = t;
    if (guia) guia.style.transform = t;
  };
  var abrir = function () {
    if (flujo) flujo.getTracks().forEach(function (t) { t.stop(); });
    navigator.mediaDevices.getUserMedia({ video: { facingMode: frontal ? "user" : "environment", width: { ideal: 1920 } }, audio: false })
      .then(function (s) { flujo = s; video.srcObject = s; espejo(); })
      .catch(function () { cam.hidden = true; if (sinCamara) { sinCamara.hidden = false; sinCamara.textContent = "No pude abrir la cámara (permiso denegado o sin cámara). Sube la foto normal."; } });
  };
  if (opacidad && guia) {
    var aplicar = function () { guia.style.opacity = opacidad.value / 100; opacidad.setAttribute("aria-valuetext", opacidad.value + " %"); };
    opacidad.addEventListener("input", aplicar);
    aplicar();
  }
  cam.querySelector("[data-voltear]").addEventListener("click", function () { frontal = !frontal; abrir(); });

  var capturar = function () {
    lienzo.width = video.videoWidth; lienzo.height = video.videoHeight;
    lienzo.getContext("2d").drawImage(video, 0, 0);  // se guarda sin espejo
    lienzo.toBlob(function (b) {
      blob = b;
      previa.src = URL.createObjectURL(b);
      previa.style.transform = video.style.transform;
      previa.hidden = false; video.hidden = true; if (guia) guia.hidden = true;
      btnCapturar.hidden = true; tras.hidden = false;
    }, "image/jpeg", 0.92);
  };
  btnCapturar.addEventListener("click", function () {
    var elegido = cam.querySelector("input[name=temporizador]:checked");
    var s = elegido ? +elegido.value : 0;
    btnCapturar.disabled = true;
    var tic = function () {
      if (s <= 0) { cuenta.textContent = ""; btnCapturar.disabled = false; return capturar(); }
      cuenta.textContent = s; s -= 1; setTimeout(tic, 1000);
    };
    tic();
  });
  cam.querySelector("[data-repetir]").addEventListener("click", function () {
    blob = null; previa.hidden = true; video.hidden = false; if (guia) guia.hidden = false;
    btnCapturar.hidden = false; tras.hidden = true;
  });
  var btnGuardar = cam.querySelector("[data-guardar]");
  btnGuardar.addEventListener("click", function () {
    if (!blob) return;
    var form = document.querySelector("[data-subir]");
    var datos = new FormData();
    datos.append("pose", cam.dataset.pose);
    datos.append("fecha", form.querySelector("[name=fecha]").value);
    datos.append("notas", form.querySelector("[name=notas]").value);
    datos.append("foto", blob, "foto.jpg");
    btnGuardar.disabled = true; btnGuardar.textContent = "Guardando…";
    fetch("/rendimiento/fotos", { method: "POST", body: datos, headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.ok) { if (flujo) flujo.getTracks().forEach(function (t) { t.stop(); }); location.href = j.url; return; }
        btnGuardar.disabled = false; btnGuardar.textContent = "Guardar foto"; alert(j.error);
      })
      .catch(function () { btnGuardar.disabled = false; btnGuardar.textContent = "Guardar foto"; });
  });
  addEventListener("pagehide", function () { if (flujo) flujo.getTracks().forEach(function (t) { t.stop(); }); });
  abrir();
})();
