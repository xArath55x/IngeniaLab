/* CU-10 · Autoguardado (SDS v3.0 §9.4). Requiere app.js (window.IL).
 *
 * const saver = IL.autosave.start({ module, key, collect, onState });
 *   collect()  → objeto con lo que hay en pantalla y aún no tiene registro propio.
 *   onState(state, info) → "dirty" | "saving" | "saved" | "offline" | "session" | "conflict" | "closed" | "limit"
 *                          | "error" | "held" | "found" (había un punto de guardado previo; info.checkpoint, info.dirty)
 *                          | "resolved" (se dejó de esperar la elección: el autoguardado anterior ya no aplica).
 *   warnOnLeave → false para no pedir confirmación al salir (p. ej. si solo hay una selección en pantalla).
 * saver.markDirty()               → hubo un cambio; se guarda en el siguiente ciclo (cada 30 s).
 * saver.snapshot()                → marca de los cambios hechos hasta ahora (para switchKey).
 * saver.saveNow({ pause })        → guarda ya; reautentica si hace falta. Nunca queda colgado sin red.
 *                                   Un caso de uso nuevo sin cambios no crea punto de guardado ({ ok, skipped }).
 * saver.resolveFound("restore")   → la pantalla ya muestra el autoguardado: no hay cambios pendientes.
 * saver.resolveFound("keep")      → conservar lo escrito; el siguiente guardado reemplaza al anterior.
 * saver.discard()                 → borra el punto de guardado; devuelve false si no se pudo (sin red).
 * saver.switchKey(key, snapshot)  → sigue con otra clave y descarta la anterior (p. ej. tras guardar un caso nuevo).
 * saver.stop()
 *
 * Reglas para no perder trabajo sin avisar:
 * - No se guarda nada hasta conocer la revisión del servidor (la consulta inicial se reintenta en cada ciclo).
 * - Si había un autoguardado y el alumno ya escribió algo, se retienen los guardados hasta que elija (estado "held").
 * - La revisión solo cambia con una respuesta del servidor, nunca por un fallo de red.
 * - El ciclo en segundo plano no abre modales ni banners: avisa por onState y reintenta.
 */
(function () {
  "use strict";
  const IL = window.IL;
  if (!IL) return;
  const BASE = "/api/checkpoints/";
  const INTERVAL_MS = 30000;
  const TIMEOUT_MS = 10000;
  const OFFLINE = { ok: false, error: "offline", message: "Sin conexión: no se pudo guardar. Tus cambios siguen en pantalla." };

  /* 401, o 403 de CSRF (JSON con csrf_failed o una página HTML sin JSON): la sesión o el token necesitan actualizarse. */
  function needsAuth(status, data) {
    return status === 401 || (status === 403 && (!data.error || data.error === "csrf_failed"));
  }
  function issueFor(status, data) {
    if (needsAuth(status, data)) return { state: "session", message: data.message };
    if (data.error === "session_changed") {
      return { state: "session", message: data.message || "La cuenta activa cambió; vuelve a tu cuenta para seguir guardando." };
    }
    return { state: "error", message: data.message || "No se pudo consultar el autoguardado. Se reintentará." };
  }
  function url(module, key, suffix) {
    return BASE + encodeURIComponent(module) + "/" + encodeURIComponent(key) + "/" + (suffix || "");
  }
  async function call(method, target, body, csrf) {
    const { res, data } = await IL.fetchJSON(target, {
      method, credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf || IL.getCookie("csrftoken"), "X-Requested-With": "fetch",
        "X-Request-ID": IL.requestId(), "X-IngeniaLab-User": document.body.dataset.userId || "" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }, TIMEOUT_MS);
    return { status: res.status, data: data && typeof data === "object" && !Array.isArray(data) ? data : {} };
  }

  function start(options) {
    const module = options.module;
    let key = options.key;
    const collect = options.collect;
    const notify = options.onState || function () {};
    const interval = options.intervalMs || INTERVAL_MS;
    const warnOnLeave = options.warnOnLeave !== false;
    let revision = 0, loaded = false, held = false, changes = 0, savedChanges = 0, lastSent = null;
    let inFlight = null, stopped = false, timer = null;
    let loadIssue = null;  // Por qué no se pudo consultar el punto de guardado: { state, message }.
    let unpause = false;   // El punto estaba pausado y el alumno volvió: hay que guardarlo sin pausa.
    const pendingDiscards = [];

    const dirty = () => changes > savedChanges;
    const body = (pause) => ({ module, key, revision, pause: !!pause, payload: { schema: 1, ...collect() } });
    function halt(state, info) { saver.stop(); notify(state, info || {}); }
    async function settle() { while (inFlight) { try { await inFlight; } catch (e) { /* ya notificado */ } } }
    function track(promise) {
      inFlight = promise;
      return promise.finally(() => { if (inFlight === promise) inFlight = null; });
    }

    /* Aplica la respuesta del servidor a un guardado de `sentKey` hecho con los cambios hasta `upTo`. */
    function handle(sentKey, status, data, upTo, signature, quiet) {
      if (sentKey !== key) return false;  // Se cambió de clave mientras viajaba: no toca la revisión nueva.
      if (status === 200 && data.ok) {
        revision = data.revision; savedChanges = Math.max(savedChanges, upTo); lastSent = signature; unpause = false;
        if (!quiet) notify(dirty() ? "dirty" : "saved", { savedAt: data.saved_at, paused: data.paused });
        return true;
      }
      if (data.error === "revision_conflict") { halt("conflict", { message: data.message }); return false; }
      if (data.error === "practice_closed") { savedChanges = changes; halt("closed", { message: data.message }); return false; }
      if (data.error === "too_many_drafts") { halt("limit", { message: data.message }); return false; }
      // Sesión vencida u otra cuenta en otra pestaña: se reintenta en cada ciclo.
      const issue = issueFor(status, data);
      notify(issue.state, { message: issue.state === "error" ? data.message || "No se pudo autoguardar." : issue.message });
      return false;
    }

    /* Consulta el punto de guardado de la clave actual. Si falla, `loaded` sigue en false, `loadIssue` dice por qué
     * (sin red, sesión vencida o error del servidor) y se reintenta. Devuelve la respuesta, o { offline: true }. */
    async function load() {
      const loadKey = key;
      let reply;
      try { reply = await call("GET", url(module, loadKey)); }
      catch (error) { loadIssue = { state: "offline" }; return { offline: true }; }
      if (loadKey !== key || stopped) return reply;
      const { status, data } = reply;
      if (status === 404) { loaded = true; revision = 0; loadIssue = null; return reply; }  // Práctica inexistente.
      if (status !== 200 || !data.ok) { loadIssue = issueFor(status, data); return reply; }
      loaded = true; loadIssue = null;
      if (!data.found) { revision = 0; return reply; }
      revision = data.revision; lastSent = JSON.stringify(data.payload);
      unpause = !!data.paused;  // Volvió a una práctica pausada: se quita la marca en cuanto elija qué conservar.
      held = dirty();  // Si ya escribió algo, que elija antes de reemplazar el autoguardado anterior.
      notify("found", { checkpoint: data, dirty: held });
      return reply;
    }
    function notifyLoadIssue() {
      const issue = loadIssue || { state: "offline" };
      notify(issue.state, { message: issue.message });
      return issue;
    }

    async function discardKey(target) {
      try {
        const { status } = await call("POST", url(module, target, "descartar/"), {});
        return status === 200 || status === 404;
      } catch (error) { return false; }
    }

    async function tick() {
      if (stopped || inFlight) return;
      await track((async () => {
        for (const old of pendingDiscards.splice(0)) {
          if (!(await discardKey(old))) pendingDiscards.push(old);
        }
        if (!loaded) await load();
        if (stopped || held || !(dirty() || unpause)) return;
        if (!loaded) { notifyLoadIssue(); return; }
        const upTo = changes, sentKey = key;
        const quiet = !dirty();  // Solo quitar la pausa: el indicador sigue diciendo «Reanudado».
        const request = body(false);
        const signature = JSON.stringify(request.payload);
        if (!unpause && signature === lastSent) { savedChanges = Math.max(savedChanges, upTo); notify("saved", {}); return; }
        if (!quiet) notify("saving", {});
        try {
          const { status, data } = await call("POST", BASE, request);
          handle(sentKey, status, data, upTo, signature, quiet);
        } catch (error) {
          notify("offline", {});  // Se reintenta en el siguiente ciclo o al volver la conexión.
        }
      })());
    }

    const onOnline = () => { tick(); };
    const onBeforeUnload = (event) => {
      if (warnOnLeave && !stopped && dirty()) { event.preventDefault(); event.returnValue = ""; }
    };

    const saver = {
      get key() { return key; },
      get revision() { return revision; },
      get dirty() { return dirty(); },
      get held() { return held; },
      snapshot() { return changes; },
      markDirty() { if (!stopped) { changes += 1; notify(held ? "held" : "dirty", {}); } },
      resolveFound(choice) {
        held = false;
        if (choice === "restore") { savedChanges = changes; notify("saved", {}); }
        else notify(dirty() ? "dirty" : "saved", {});
        if (unpause) settle().then(tick);  // Ya volvió: el tablero no debe seguir diciendo «Pausada».
      },
      async saveNow(opts) {
        await settle();
        if (stopped) return { ok: false, error: "stopped", message: "El autoguardado está detenido; recarga la página." };
        // Un caso de uso nuevo sin punto de guardado ni cambios no tiene nada que conservar: no se crea un borrador
        // vacío que cuente contra el límite de borradores.
        if (loaded && revision === 0 && !dirty() && String(key).startsWith("nuevo:")) {
          return { ok: true, skipped: true };
        }
        return track((async () => {
          let csrf = "", upTo = 0, sentKey = key, signature = null;
          for (let tries = 0; tries < 2; tries++) {
            let reply;
            try {
              if (!loaded) {
                reply = await load();
                if (reply.offline) { notify("offline", {}); return OFFLINE; }
              }
              if (loaded) {
                // Guardar a propósito es elegir lo que está en pantalla: el autoguardado anterior ya no se ofrece.
                if (held) { held = false; notify("resolved", {}); }
                upTo = changes; sentKey = key;
                const request = body(opts && opts.pause);
                signature = JSON.stringify(request.payload);
                notify("saving", {});
                reply = await call("POST", BASE, request, csrf);
              }
            } catch (error) { notify("offline", {}); return OFFLINE; }
            const { status, data } = reply;
            // Igual que IL.api: 401 o 403 de CSRF abren el modal de sesión y se reintenta una vez.
            if (needsAuth(status, data) && tries === 0) {
              const refreshed = await IL.sessionExpired(data.message || "Tu sesión o token necesitan actualizarse.");
              const identity = document.body.dataset.userId || "";
              if (identity && refreshed.user_id !== identity) {
                const changed = { ok: false, error: "session_changed", message: "La cuenta activa cambió. Vuelve a tu cuenta para guardar." };
                notify("session", { message: changed.message });
                return changed;
              }
              csrf = refreshed.csrf_token;
              continue;
            }
            if (!loaded) {
              const issue = notifyLoadIssue();
              return { ok: false, error: issue.state, message: issue.message || "No se pudo consultar el autoguardado.", http_status: status };
            }
            handle(sentKey, status, data, upTo, signature);
            return { ...data, ok: status === 200 && !!data.ok, http_status: status };
          }
          return { ok: false, error: "session", message: "No se pudo actualizar la sesión." };
        })());
      },
      async discard() {
        await settle();
        const done = await discardKey(key);
        if (done) { revision = 0; lastSent = null; loaded = true; held = false; }
        return done;
      },
      async switchKey(next, upTo) {
        const old = key;
        savedChanges = Math.max(savedChanges, upTo === undefined ? changes : upTo);
        held = false;
        if (old === next) {
          // Misma clave (caso de uso ya existente): la revisión solo vuelve a 0 si el servidor confirma el descarte.
          await settle();
          if (await discardKey(old)) { revision = 0; lastSent = null; loaded = true; }
          return;
        }
        key = next;  // De inmediato: un ciclo que empiece ahora ya usa la clave nueva.
        revision = 0; lastSent = null; loaded = false;
        await settle();
        if (!(await discardKey(old))) pendingDiscards.push(old);
      },
      stop() {
        stopped = true; clearInterval(timer);
        window.removeEventListener("online", onOnline);
        window.removeEventListener("beforeunload", onBeforeUnload);
      },
      ready: null,
    };

    saver.ready = track(load());
    timer = setInterval(tick, interval);
    window.addEventListener("online", onOnline);
    window.addEventListener("beforeunload", onBeforeUnload);
    return saver;
  }

  /* ACT-307B: indicador, «Guardar y pausar» y reanudación sobre la barra de templates/progress/_autosave.html.
   * IL.autosave.mount({ module, key, collect, restore, notice, afterDiscard, warnOnLeave })
   *   restore(payload) → vuelve a poner en pantalla lo autoguardado.
   *   afterDiscard(key) → qué hacer tras «Descartar estos cambios» (por omisión, recargar la página).
   *   notice → elemento donde avisar «Recuperamos cambios…» (si falta, el aviso va en la barra). */
  const STATES = {
    idle: ["✔", "Autoguardado activo"],
    dirty: ["•", "Cambios sin guardar"],
    saving: ["⟳", "Guardando…"],
    saved: ["✔", "Guardado"],
    held: ["⚠", "Elige si recuperas el autoguardado anterior; mientras tanto no se guarda."],
    offline: ["⚠", "Sin conexión: cambios sin guardar. Se reintentará."],
    session: ["⚠", "Tu sesión venció: inicia sesión para seguir guardando."],
    conflict: ["⚠", "Abierta en otra pestaña: recarga la página para continuar."],
    closed: ["✔", "La práctica terminó; ya no hace falta autoguardar."],
    limit: ["⚠", "No se pudo autoguardar."],
    error: ["⚠", "No se pudo autoguardar."],
  };
  const STOPPED = ["conflict", "closed", "limit"];
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
    let lastSaved = "", note = null;
    function show(state, info) {
      if (!bar) return;
      const [mark, label] = STATES[state] || STATES.error;
      if (state === "saved" && info.savedAt) lastSaved = clock(info.savedAt);
      bar.dataset.state = state;
      icon.textContent = mark;
      text.textContent = state === "saved" && lastSaved ? `${label} ${lastSaved}`
        : ["error", "conflict", "limit", "session"].includes(state) && info.message ? info.message : label;
      if (pause) pause.disabled = state === "saving" || STOPPED.includes(state);
    }
    function notice(strong, buttons) {
      if (note) note.remove();
      note = IL.el("div", { class: "feedback hint autosave-notice", role: "status" }, [
        IL.el("span", { class: "icon", "aria-hidden": "true", text: "💾" }),
        IL.el("div", {}, [IL.el("strong", { text: strong }), ...buttons]),
      ]);
      (options.notice || bar).prepend(note);
    }
    async function discardAndReload(button) {
      button.disabled = true;
      if (await saver.discard()) { (options.afterDiscard || (() => window.location.reload()))(saver.key); return; }
      button.disabled = false;
      IL.toast("No se pudo descartar sin conexión. Inténtalo de nuevo.", "bad");
    }
    function found(cp, wasDirty) {
      lastSaved = clock(cp.saved_at);
      if (!options.restore) { saver.resolveFound("keep"); return; }
      if (!wasDirty) {
        try { options.restore(cp.payload); } catch (error) { /* Se conserva la pantalla tal cual. */ }
        saver.resolveFound("restore");
        if (bar) { icon.textContent = "✔"; text.textContent = `Reanudado · guardado ${lastSaved}`; bar.dataset.state = "found"; }
        if (options.notice) {
          const undo = IL.el("button", { type: "button", class: "btn small ghost", text: "Descartar estos cambios",
            onclick: () => discardAndReload(undo) });
          notice("Recuperamos cambios autoguardados el " + lastSaved + ". ", [undo]);
        }
        return;
      }
      // Ya escribió algo antes de que llegara el autoguardado: no se pisa ni se reemplaza sin preguntar.
      show("held", {});
      const recover = IL.el("button", { type: "button", class: "btn small", text: "Recuperar autoguardado",
        onclick: () => {
          try { options.restore(cp.payload); } catch (error) { /* Se conserva la pantalla tal cual. */ }
          saver.resolveFound("restore"); note.remove(); note = null;
          if (bar) { text.textContent = `Reanudado · guardado ${lastSaved}`; bar.dataset.state = "found"; }
        } });
      const keep = IL.el("button", { type: "button", class: "btn small ghost", text: "Conservar lo que escribí",
        onclick: () => { saver.resolveFound("keep"); note.remove(); note = null; } });
      notice("Hay cambios autoguardados el " + lastSaved + " que no están en pantalla. ", [recover, keep]);
    }
    const saver = start({
      module: options.module, key: options.key, collect: options.collect, warnOnLeave: options.warnOnLeave,
      onState(state, info) {
        if (state === "found") found(info.checkpoint, info.dirty);
        // «Guardar y pausar» reemplazó el autoguardado anterior: ofrecer recuperarlo traería datos que ya no existen.
        else if (state === "resolved") { if (note) { note.remove(); note = null; } }
        else show(state, info);
      },
    });
    if (pause) {
      pause.addEventListener("click", async () => {
        pause.disabled = true;
        const response = await saver.saveNow({ pause: true });
        if (response.ok) {
          saver.stop();
          IL.toast(response.skipped ? "No había cambios que guardar." : "Práctica guardada y pausada. Puedes retomarla desde Mi progreso.", "ok");
          setTimeout(() => { window.location.href = "/"; }, 800);
          return;
        }
        if (response.error === "offline") IL.toast(response.message, "bad");
        pause.disabled = bar.dataset.state === "saving" || STOPPED.includes(bar.dataset.state);
      });
    }
    return saver;
  }

  window.IL.autosave = { start, mount, INTERVAL_MS,
    newUseCaseKey: () => "nuevo:" + IL.requestId() };
})();
