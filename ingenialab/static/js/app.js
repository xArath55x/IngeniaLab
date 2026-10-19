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

  function sessionExpired(message, retry) {
    const back = el("div", { class: "modal-back" }, [
      el("div", { class: "modal", role: "dialog", "aria-modal": "true" }, [
        el("h3", { text: "Sesión expirada" }),
        el("p", { text: message }),
        el("p", { class: "small muted", text: "Inicia sesión en la pestaña que se abrirá y después pulsa «Reintentar». Lo que tienes en pantalla no se perderá." }),
        el("div", { class: "btn-row" }, [
          el("a", { class: "btn secondary", href: "/cuentas/login/?next=/", target: "_blank", rel: "noopener", text: "Iniciar sesión" }),
          el("button", { class: "btn", type: "button", text: "Reintentar", onclick: () => { back.remove(); retry(); } }),
        ]),
      ]),
    ]);
    document.body.append(back);
  }

  /* Envía JSON por POST. Resuelve con la respuesta del servidor ({ok, ...}).
   * Si la red falla o la sesión expiró, la promesa queda pendiente hasta que el reintento tenga éxito. */
  function api(url, body) {
    return new Promise((resolve) => {
      const attempt = () => {
        fetch(url, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken"), "X-Requested-With": "fetch" },
          body: JSON.stringify(body || {}),
        })
          .then(async (res) => {
            if (res.status === 401 || res.status === 403) {
              let data = {};
              try { data = await res.json(); } catch (e) { /* respuesta HTML de CSRF */ }
              sessionExpired(data.message || "Tu sesión expiró por inactividad. Tu trabajo guardado se conserva.", attempt);
              return;
            }
            hideNetBanner();
            if (res.status >= 500) {
              let problem = {};
              try { problem = await res.json(); } catch (e) { /* error HTML inesperado */ }
              resolve({ ok: false, ...problem, message: problem.message || "Ocurrió un error en el servidor. Intenta de nuevo." });
              return;
            }
            resolve(await res.json());
          })
          .catch(() => showNetBanner("No se pudo contactar al servidor. Revisa tu conexión; tus datos en pantalla se conservan.", attempt));
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
