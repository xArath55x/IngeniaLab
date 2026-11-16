/* CU-10 · Autoguardado (SDS v3.0 §9.4). Requiere app.js (window.IL).
 *
 * const saver = IL.autosave.start({ module, key, collect, onState });
 *   collect()  → objeto con lo que hay en pantalla y aún no tiene registro propio.
 *   onState(state, info) → "dirty" | "saving" | "saved" | "offline" | "session" | "conflict" | "closed" | "error"
 *                          | "found" (había un punto de guardado previo; info.checkpoint).
 * saver.markDirty()          → hubo un cambio; se guarda en el siguiente ciclo (cada 30 s).
 * saver.saveNow({ pause })   → guarda ya con IL.api (modal 401 y aviso de red incluidos); devuelve la respuesta.
 * saver.discard()            → borra el punto de guardado en el servidor.
 * saver.switchKey(key)       → descarta el punto actual y sigue con otra clave (p. ej. tras guardar un caso nuevo).
 * saver.stop()
 *
 * El ciclo en segundo plano no abre modales ni banners: si falla la red o la sesión, avisa por onState
 * y reintenta en el siguiente ciclo o al volver la conexión. Un 409 detiene el ciclo sin sobrescribir.
 */
(function () {
  "use strict";
  if (!window.IL) return;
  const BASE = "/api/checkpoints/";
  const INTERVAL_MS = 30000;
  const TIMEOUT_MS = 10000;

  function cookie(name) {
    const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }
  function uuid() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const n = Math.floor(Math.random() * 16); return (c === "x" ? n : (n & 3) | 8).toString(16);
    });
  }
  function url(module, key, suffix) {
    return BASE + encodeURIComponent(module) + "/" + encodeURIComponent(key) + "/" + (suffix || "");
  }
  async function quiet(method, target, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(target, {
        method, credentials: "same-origin", cache: "no-store", signal: controller.signal,
        headers: { "Content-Type": "application/json", "X-CSRFToken": cookie("csrftoken"), "X-Requested-With": "fetch",
          "X-Request-ID": uuid(), "X-IngeniaLab-User": document.body.dataset.userId || "" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let data = null;
      try { data = await res.json(); } catch (e) { data = null; }
      return { status: res.status, data: data || {} };
    } finally { clearTimeout(timer); }
  }

  function start(options) {
    const module = options.module;
    let key = options.key;
    const collect = options.collect;
    const notify = options.onState || function () {};
    const interval = options.intervalMs || INTERVAL_MS;
    let revision = 0, changes = 0, savedChanges = 0, lastSent = null, inFlight = null, stopped = false, timer = null;

    function dirty() { return changes !== savedChanges; }
    function stopWith(state, info) { stopped = true; clearInterval(timer); notify(state, info || {}); }
    function body(pause) { return { module, key, revision, pause: !!pause, payload: { schema: 1, ...collect() } }; }

    function handle(status, data, sentAt, signature) {
      if (status === 200 && data.ok) {
        revision = data.revision; savedChanges = sentAt; lastSent = signature;
        notify(dirty() ? "dirty" : "saved", { savedAt: data.saved_at, paused: data.paused });
        return true;
      }
      if (status === 401) { notify("session", { message: data.message }); return false; }
      if (status === 409 && data.error === "revision_conflict") { stopWith("conflict", { message: data.message }); return false; }
      if (status === 409 && data.error === "practice_closed") { savedChanges = changes; stopWith("closed", { message: data.message }); return false; }
      if (status === 409) { stopWith("conflict", { message: data.message }); return false; }
      notify("error", { message: data.message || "No se pudo autoguardar." });
      return false;
    }

    async function tick() {
      if (stopped || inFlight || !dirty()) return;
      const sentAt = changes;
      const request = body(false);
      const signature = JSON.stringify(request.payload);
      if (signature === lastSent) { savedChanges = sentAt; notify("saved", {}); return; }
      notify("saving", {});
      inFlight = (async () => {
        try {
          const { status, data } = await quiet("POST", BASE, request);
          handle(status, data, sentAt, signature);
        } catch (error) {
          notify("offline", {});  // Se reintenta en el siguiente ciclo o al volver la conexión.
        }
      })();
      try { await inFlight; } finally { inFlight = null; }
    }

    async function load() {
      try {
        const { status, data } = await quiet("GET", url(module, key));
        if (status === 200 && data.ok && data.found) {
          revision = data.revision; lastSent = JSON.stringify(data.payload);
          notify("found", { checkpoint: data });
        }
      } catch (error) { /* Sin conexión: se intentará al guardar. */ }
    }

    const saver = {
      get key() { return key; },
      get revision() { return revision; },
      get dirty() { return dirty(); },
      markDirty() { if (!stopped) { changes += 1; notify("dirty", {}); } },
      async saveNow(opts) {
        // Espera al guardado en segundo plano para no enviar dos veces la misma revisión.
        while (inFlight) { try { await inFlight; } catch (e) { /* ya notificado */ } }
        const pause = !!(opts && opts.pause);
        const sentAt = changes;
        const request = body(pause);
        notify("saving", {});
        inFlight = window.IL.api(BASE, request);
        try {
          const response = await inFlight;
          handle(response.http_status || response.status, response, sentAt, JSON.stringify(request.payload));
          return response;
        } finally { inFlight = null; }
      },
      async discard() {
        try { await quiet("POST", url(module, key, "descartar/"), {}); } catch (error) { /* se purga después */ }
        revision = 0; lastSent = null;
      },
      async switchKey(next) {
        await saver.discard();
        key = next; savedChanges = changes;
      },
      stop() { stopped = true; clearInterval(timer); },
      ready: null,
    };

    saver.ready = load();
    timer = setInterval(tick, interval);
    window.addEventListener("online", tick);
    window.addEventListener("beforeunload", (event) => {
      if (!stopped && dirty()) { event.preventDefault(); event.returnValue = ""; }
    });
    return saver;
  }

  /* ACT-307B: indicador, «Guardar y pausar» y reanudación sobre la barra de templates/progress/_autosave.html.
   * IL.autosave.mount({ module, key, collect, restore, notice })
   *   restore(payload) → vuelve a poner en pantalla lo autoguardado (solo si aún no hubo cambios).
   *   notice → elemento donde avisar «Recuperamos cambios…» con la opción de descartarlos. */
  const STATES = {
    idle: ["✔", "Autoguardado activo"],
    dirty: ["•", "Cambios sin guardar"],
    saving: ["⟳", "Guardando…"],
    saved: ["✔", "Guardado"],
    offline: ["⚠", "Sin conexión: cambios sin guardar. Se reintentará."],
    session: ["⚠", "Tu sesión venció: inicia sesión para seguir guardando."],
    conflict: ["⚠", "Abierta en otra pestaña: recarga la página para continuar."],
    closed: ["✔", "La práctica terminó; ya no hace falta autoguardar."],
    error: ["⚠", "No se pudo autoguardar."],
  };
  function clock(iso) {
    const date = iso ? new Date(iso) : null;
    if (!date || isNaN(date)) return "";
    return date.toLocaleString("es-MX", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  }
  function mount(options) {
    const bar = document.querySelector("[data-autosave]");
    const icon = bar && bar.querySelector(".autosave-icon");
    const text = bar && bar.querySelector(".autosave-text");
    const pause = bar && bar.querySelector("[data-autosave-pause]");
    let lastSaved = "";
    function show(state, info) {
      if (!bar) return;
      const [mark, label] = STATES[state] || STATES.error;
      if (state === "saved" && info.savedAt) lastSaved = clock(info.savedAt);
      bar.dataset.state = state;
      icon.textContent = mark;
      text.textContent = state === "saved" && lastSaved ? `${label} ${lastSaved}`
        : (state === "error" || state === "conflict") && info.message ? info.message : label;
      if (pause) pause.disabled = state === "saving" || state === "conflict" || state === "closed";
    }
    const saver = start({
      module: options.module, key: options.key, collect: options.collect,
      onState(state, info) {
        if (state !== "found") { show(state, info); return; }
        const cp = info.checkpoint;
        lastSaved = clock(cp.saved_at);
        if (saver && saver.dirty) { show("dirty", {}); return; }  // No pisar lo que el alumno ya escribió.
        if (options.restore) {
          try { options.restore(cp.payload); } catch (error) { /* Si no se puede restaurar, se conserva la pantalla. */ }
        }
        if (bar) { icon.textContent = "✔"; text.textContent = `Reanudado · guardado ${lastSaved}`; bar.dataset.state = "found"; }
        if (options.notice && options.restore) {
          const undo = window.IL.el("button", { type: "button", class: "btn small ghost", text: "Descartar estos cambios",
            onclick: async () => { undo.disabled = true; await saver.discard(); window.location.reload(); } });
          const note = window.IL.el("div", { class: "feedback hint autosave-notice", role: "status" }, [
            window.IL.el("span", { class: "icon", "aria-hidden": "true", text: "💾" }),
            window.IL.el("div", {}, [window.IL.el("strong", { text: "Recuperamos cambios autoguardados el " + lastSaved + ". " }), undo]),
          ]);
          options.notice.prepend(note);
        }
      },
    });
    if (pause) {
      pause.addEventListener("click", async () => {
        pause.disabled = true;
        const response = await saver.saveNow({ pause: true });
        if (response.ok) {
          saver.stop();
          window.IL.toast("Práctica guardada y pausada. Puedes retomarla desde Mi progreso.", "ok");
          setTimeout(() => { window.location.href = "/"; }, 800);
        } else {
          // Tras un conflicto o con la práctica terminada, pausar ya no tiene efecto.
          pause.disabled = bar.dataset.state === "conflict" || bar.dataset.state === "closed";
        }
      });
    }
    return saver;
  }

  window.IL.autosave = { start, mount, newUseCaseKey: () => "nuevo:" + uuid(), INTERVAL_MS };
})();
