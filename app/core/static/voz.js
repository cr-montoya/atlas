/* Registro por voz: graba con MediaRecorder y envía el audio crudo al servidor, que lo transcribe en casa.
   Cada [data-grabadora] es una grabadora: la del relato y la de la respuesta a una pregunta. */
(function () {
  "use strict";
  var MAX_S = 180;
  var TIPOS = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];

  function tipoSoportado() {
    if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return "";
    for (var i = 0; i < TIPOS.length; i++) if (MediaRecorder.isTypeSupported(TIPOS[i])) return TIPOS[i];
    return "";
  }

  function hayMicrofono() {
    return !!(window.isSecureContext && window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  function mmss(s) { return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }

  function iniciar(caja) {
    var botonGrabar = caja.querySelector("[data-grabar]");
    var panel = caja.querySelector("[data-grabando]");
    var contador = caja.querySelector("[data-contador]");
    var estado = caja.querySelector("[data-estado]");
    var sinMicro = caja.querySelector("[data-sin-micro]");
    var grabador = null, flujo = null, trozos = [], reloj = null, inicio = 0, enviar = false;

    function sinMicrofono() {
      if (botonGrabar) botonGrabar.disabled = true;
      if (sinMicro) {
        sinMicro.hidden = false;
        if (!window.isSecureContext && location.protocol === "http:") {
          var aviso = sinMicro.querySelector("[data-https]"), enlace = sinMicro.querySelector("[data-enlace-https]");
          if (aviso && enlace) { aviso.hidden = false; enlace.href = "https://" + location.host + location.pathname; }
        }
      }
    }

    if (!botonGrabar) return;
    if (!hayMicrofono()) { sinMicrofono(); return; }

    function detenerTodo() {
      clearInterval(reloj);
      if (flujo) flujo.getTracks().forEach(function (t) { t.stop(); });
      flujo = null;
      panel.hidden = true;
      botonGrabar.hidden = false;
    }

    function decir(texto) { if (estado) estado.textContent = texto; }

    async function subir(blob) {
      decir("Enviando…");
      botonGrabar.disabled = true;
      try {
        var antes = caja.getAttribute("data-guardar-antes");
        if (antes) {
          var form = document.getElementById("f-borrador");
          var r0 = await fetch(antes, { method: "POST", body: new FormData(form), headers: { "X-Solo-Guardar": "1" } });
          if (!r0.ok) throw new Error("No pude guardar el borrador antes de enviar");
        }
        var r = await fetch(caja.getAttribute("data-envio"), {
          method: "POST", body: blob, headers: { "Content-Type": blob.type || "application/octet-stream" }
        });
        var datos = {};
        try { datos = await r.json(); } catch (e) { /* sin cuerpo JSON */ }
        if (datos.url) { location.href = datos.url; return; }
        throw new Error(datos.error || "No pude enviar el audio");
      } catch (err) {
        decir(err.message + ". Prueba de nuevo o escríbelo.");
        botonGrabar.disabled = false;
      }
    }

    botonGrabar.addEventListener("click", async function () {
      decir("");
      try {
        flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (err) {
        decir("No pude usar el micrófono.");
        sinMicrofono();
        return;
      }
      var tipo = tipoSoportado();
      try {
        grabador = tipo ? new MediaRecorder(flujo, { mimeType: tipo }) : new MediaRecorder(flujo);
      } catch (err) {
        detenerTodo();
        sinMicrofono();
        return;
      }
      trozos = [];
      enviar = false;
      grabador.ondataavailable = function (ev) { if (ev.data && ev.data.size) trozos.push(ev.data); };
      grabador.onstop = function () {
        detenerTodo();
        if (!enviar) { decir("Grabación cancelada."); return; }
        subir(new Blob(trozos, { type: (grabador.mimeType || tipo || "").split(";")[0] }));
      };
      grabador.start(1000);
      inicio = Date.now();
      contador.textContent = "0:00";
      botonGrabar.hidden = true;
      panel.hidden = false;
      var detener = panel.querySelector("[data-detener]");
      if (detener) detener.focus();
      reloj = setInterval(function () {
        var s = Math.floor((Date.now() - inicio) / 1000);
        contador.textContent = mmss(s);
        if (s >= MAX_S && grabador.state === "recording") { enviar = true; grabador.stop(); }
      }, 250);
    });

    panel.querySelector("[data-detener]").addEventListener("click", function () {
      if (grabador && grabador.state === "recording") { enviar = true; grabador.stop(); }
    });
    panel.querySelector("[data-cancelar]").addEventListener("click", function () {
      if (grabador && grabador.state === "recording") { enviar = false; grabador.stop(); }
      botonGrabar.focus();
    });
  }

  document.querySelectorAll("[data-grabadora]").forEach(iniciar);
  // "Guardar todo" queda deshabilitado mientras haya un «Entendí…» sin confirmar. Cambiar el valor de ese campo
  // también cuenta como confirmarlo (como en el servidor). Sin JavaScript, el servidor responde 422 igual.
  function vigilarConfirmaciones(form) {
    var boton = form.querySelector("[data-guardar-todo]");
    if (!boton) return;
    var pendientes = Array.prototype.map.call(form.querySelectorAll(".marca-voz.entendi input[type=checkbox]"), function (caja) {
      var campo = caja.closest(".campo-voz, .check:not(.confirmo)");
      var control = campo ? campo.querySelector("select, input:not([name$='.confirmo'])") : null;
      return { caja: caja, control: control, inicial: control ? (control.type === "checkbox" ? control.checked : control.value) : null };
    });
    if (!pendientes.length) return;
    function revisar() {
      var falta = pendientes.some(function (p) {
        if (p.caja.checked) return false;
        if (!p.control) return true;
        var ahora = p.control.type === "checkbox" ? p.control.checked : p.control.value;
        return ahora === p.inicial;
      });
      boton.disabled = falta;
      boton.title = falta ? "Confirma o corrige lo marcado con «Entendí»" : "";
    }
    form.addEventListener("change", revisar);
    revisar();
  }
  document.querySelectorAll("form.borrador-voz").forEach(vigilarConfirmaciones);
})();
