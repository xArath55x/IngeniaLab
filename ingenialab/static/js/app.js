/* IngeniaLab — utilidades de cliente compartidas.
 * Incluye OfflineHandler (RF-12 / SDS §3.3): ante un fallo de red se muestra un banner
 * y la operación puede reintentarse sin perder lo capturado en pantalla. */
(function () {
  "use strict";

  function getCookie(name) {
    const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
    return m ? decodeURIComponent(m.pop()) : "";
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    });
    (children || []).forEach((c) => node.append(c));
    return node;
  }

  /* ---------- Toasts ---------- */
  function toast(message, kind, icon) {
    let box = document.querySelector(".toasts");
    if (!box) { box = el("div", { class: "toasts", "aria-live": "polite" }); document.body.append(box); }
    const t = el("div", { class: "toast " + (kind || ""), role: "status" }, [
      el("span", { text: icon || (kind === "ok" ? "✔" : kind === "bad" ? "✖" : "ℹ") }),
      el("span", { text: message }),
    ]);
    box.append(t);
    setTimeout(() => t.remove(), 4500);
  }

  function showBadges(badges) {
    (badges || []).forEach((b) => toast("Nueva insignia: " + b.name, "ok", b.icon));
  }

  /* ---------- Modal de confirmación ---------- */
  function confirmModal(title, message, okLabel, cancelLabel) {
    return new Promise((resolve) => {
      const close = (v) => { back.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      const onKey = (e) => { if (e.key === "Escape") close(false); };
      const okBtn = el("button", { class: "btn", type: "button", text: okLabel || "Confirmar", onclick: () => close(true) });
      const back = el("div", { class: "modal-back", onclick: (e) => { if (e.target === back) close(false); } }, [
        el("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-title" }, [
          el("h3", { id: "modal-title", text: title }),
          el("p", { text: message }),
          el("div", { class: "btn-row" }, [
            el("button", { class: "btn ghost", type: "button", text: cancelLabel || "Cancelar", onclick: () => close(false) }),
            okBtn,
          ]),
        ]),
      ]);
      document.body.append(back);
      document.addEventListener("keydown", onKey);
      okBtn.focus();
    });
  }

  /* ---------- OfflineHandler ---------- */
  let banner = null;
  function showNetBanner(message, onRetry) {
    hideNetBanner();
    const children = [el("span", { text: "⚠ " + message })];
    if (onRetry) children.push(el("button", { class: "btn small", type: "button", text: "Reintentar", onclick: onRetry }));
    banner = el("div", { class: "net-banner", role: "alert" }, children);
    document.body.append(banner);
  }
  function hideNetBanner() { if (banner) { banner.remove(); banner = null; } }

  window.addEventListener("offline", () =>
    showNetBanner("Sin conexión. IngeniaLab requiere una conexión activa; tu trabajo en pantalla se conserva."));
  window.addEventListener("online", () => { hideNetBanner(); toast("Conexión restablecida.", "ok"); });

  // ACT-211C: límite completo de fetch + lectura JSON, con aborto de transporte.
  async function fetchJSON(url, init, timeoutMs) {
    const controller = new AbortController();
    let timer;
    const deadline = new Promise((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        const error = new Error("Tiempo de espera agotado"); error.name = "AbortError"; reject(error);
      }, timeoutMs);
    });
    const operation = (async () => {
      const res = await fetch(url, { ...init, signal: controller.signal });
      try { return { res, data: await res.json(), parseError: false }; }
      catch (error) { return { res, data: null, parseError: true }; }
    })();
    try { return await Promise.race([operation, deadline]); }
    finally { clearTimeout(timer); }
  }

  let sessionRecovery = null;
  function sessionExpired(message) {
    if (sessionRecovery) return sessionRecovery;
    sessionRecovery = new Promise((resolve) => {
      const note = el("p", { text: message });
      const retry = el("button", { class: "btn", type: "button", text: "Reintentar", onclick: async () => {
        retry.disabled = true;
        try {
          const { res, data, parseError } = await fetchJSON("/cuentas/api/sesion/", { credentials: "same-origin", cache: "no-store" }, 10000);
          if (res.status !== 200 || parseError || !data || !data.ok || typeof data.user_id !== "string" || typeof data.csrf_token !== "string" || !data.csrf_token) {
            note.textContent = "Primero inicia sesión en la pestaña nueva y vuelve a reintentar."; return;
          }
          back.remove(); resolve(data);
        } catch (error) { note.textContent = "No se pudo actualizar la sesión. Revisa tu conexión y reintenta."; }
        finally { retry.disabled = false; }
      }});
      const back = el("div", { class: "modal-back" }, [
        el("div", { class: "modal", role: "dialog", "aria-modal": "true" }, [
          el("h3", { text: "Actualizar sesión" }), note,
          el("p", { class: "small muted", text: "Inicia sesión en la pestaña nueva y después pulsa Reintentar. Tu borrador se conserva." }),
          el("div", { class: "btn-row" }, [
            el("a", { class: "btn secondary", href: "/cuentas/login/?next=/elicitacion/", target: "_blank", rel: "noopener", text: "Iniciar sesión" }), retry,
          ]),
        ]),
      ]);
      document.body.append(back);
    }).finally(() => { sessionRecovery = null; });
    return sessionRecovery;
  }

  function requestId() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const n = Math.floor(Math.random() * 16); return (c === "x" ? n : (n & 3) | 8).toString(16);
    });
  }

  /* Mantiene cuerpo, identidad y clave durante los reintentos explícitos.
   * No reenvía automáticamente operaciones cuyo resultado sea incierto. */
  function api(url, body, options) {
    const payload = JSON.stringify(body || {});
    const identity = document.body.dataset.userId || "";
    const id = requestId();
    let csrf = "";
    const configured = options && options.timeoutMs;
    const timeoutMs = Number.isFinite(configured) && configured > 0 ? configured : 10000;
    return new Promise((resolve) => {
      let busy = false;
      const attempt = async () => {
        if (busy) return;
        busy = true;
        try {
          const { res, data, parseError } = await fetchJSON(url, {
            method: "POST", credentials: "same-origin",
            headers: { "Content-Type": "application/json", "X-CSRFToken": csrf || getCookie("csrftoken"),
              "X-Requested-With": "fetch", "X-Request-ID": id, "X-IngeniaLab-User": identity },
            body: payload,
          }, timeoutMs);
          if (res.status === 401 || (res.status === 403 && (parseError || !data || data.error === "csrf_failed"))) {
            const refreshed = await sessionExpired((data && data.message) || "Tu sesión o token necesitan actualizarse.");
            if (identity && refreshed.user_id !== identity) {
              resolve({ ok: false, status: 409, error: "session_changed", message: "La cuenta activa cambió. Tu borrador se conserva; vuelve a tu cuenta para enviarlo." }); return;
            }
            csrf = refreshed.csrf_token; Promise.resolve().then(attempt); return;
          }
          hideNetBanner();
          if (parseError || !data || typeof data !== "object" || Array.isArray(data) || typeof data.ok !== "boolean") {
            resolve({ ok: false, status: res.status, error: "invalid_response", message: "El servidor devolvió una respuesta no válida. Tus datos en pantalla se conservan." }); return;
          }
          resolve({ ...data, ok: res.status >= 200 && res.status < 300 && data.ok, status: res.status });
        } catch (error) {
          showNetBanner(error.name === "AbortError"
            ? "El servidor tardó demasiado. El resultado puede haberse guardado; reintenta la misma operación para comprobarlo."
            : "No se pudo contactar al servidor. Tus datos en pantalla se conservan.", attempt);
        } finally { busy = false; }
      };
      attempt();
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function feedback(kind, title, body) {
    const icon = kind === "ok" ? "✔" : kind === "bad" ? "✖" : "💡";
    return `<div class="feedback ${kind}" role="status"><span class="icon" aria-hidden="true">${icon}</span>` +
      `<div><strong>${esc(title)}</strong>${body ? esc(body) : ""}</div></div>`;
  }

  window.IL = { api, toast, showBadges, confirmModal, el, esc, feedback };
})();
