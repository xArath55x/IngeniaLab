/* ACT-207A: editor accesible, pasos consecutivos y validación previa a las API. */
(function () {
  "use strict";
  const form = document.getElementById("uc-form");
  if (!form) return;
  const rules = JSON.parse(document.getElementById("validation-rules").textContent);
  const guide = JSON.parse(document.getElementById("guide-data").textContent);
  const initial = JSON.parse(document.getElementById("form-data").textContent);
  const validation = document.getElementById("validation");
  const buttons = ["btn-validate", "btn-generate", "btn-save"].map(id => document.getElementById(id));
  const saveButton = document.getElementById("btn-save");
  const F = { name: document.getElementById("f-name"), system: document.getElementById("f-system"),
    pre: document.getElementById("f-pre"), post: document.getElementById("f-post") };
  let ucId = form.dataset.ucId || "", rendered = null, busy = false;
  const lists = {};
  const limits = {
    primary_actors: [rules.max_actors, rules.actor], secondary_actors: [rules.max_actors, rules.actor],
    main_flow: [rules.max_steps, rules.step], alternate_flows: [rules.max_alternates, rules.alternate],
    relations: [rules.max_relations, rules.name]
  };
  function invalidate() {
    rendered = null; saveButton.disabled = true;
    validation.innerHTML = IL.feedback("hint", "Cambios pendientes.", " Valida la plantilla y regenera el diagrama antes de guardar.");
  }
  function renumber(box) {
    box.querySelectorAll(".list-item").forEach((row, i) => {
      const num = row.querySelector(".num"); if (num) num.textContent = (i + 1) + ".";
      row.querySelector("input").setAttribute("aria-label", `${box.dataset.placeholder}: elemento ${i + 1}`);
      row.querySelector(".icon-btn").setAttribute("aria-label", `Quitar elemento ${i + 1} de ${box.dataset.list}`);
    });
    box.querySelector(".add-btn").disabled = box.querySelectorAll(".list-item").length >= limits[box.dataset.list][0];
  }
  function addItem(box, value, changed) {
    if (box.querySelectorAll(".list-item").length >= limits[box.dataset.list][0]) return null;
    const relation = !!box.dataset.relations;
    const row = IL.el("div", { class: "list-item" });
    if (box.dataset.numbered) row.append(IL.el("span", { class: "num", "aria-hidden": "true" }));
    if (relation) {
      const select = IL.el("select", { class: "rel-type", "aria-label": "Tipo de relación" }, [
        IL.el("option", { value: "include", text: "«include»" }), IL.el("option", { value: "extend", text: "«extend»" })]);
      select.value = value && value.type || "include"; row.append(select);
    }
    const input = IL.el("input", { type: "text", placeholder: box.dataset.placeholder, maxlength: limits[box.dataset.list][1] });
    input.value = relation ? value && value.target || "" : value || "";
    input.addEventListener("keydown", event => {
      if (event.key === "Enter") { event.preventDefault(); const next = addItem(box, null, true); if (next) next.focus(); }
    });
    row.append(input, IL.el("button", { type: "button", class: "icon-btn", text: "✕", onclick: () => {
      row.remove(); renumber(box); invalidate(); box.querySelector(".add-btn").focus();
    }}));
    box.insertBefore(row, box.querySelector(".add-btn")); renumber(box);
    if (changed) invalidate();
    return input;
  }
  document.querySelectorAll("[data-list]").forEach(box => {
    lists[box.dataset.list] = box;
    box.append(IL.el("button", { type: "button", class: "btn small ghost add-btn", text: box.dataset.add, onclick: () => {
      const input = addItem(box, null, true); if (input) input.focus();
    }}));
  });
  const attempt = document.getElementById("f-attempt");
  guide.forEach(g => attempt.append(IL.el("option", { value: g.id, text: g.label })));
  if (!initial && form.dataset.selectedAttempt) attempt.value = form.dataset.selectedAttempt;
  function renderGuide() {
    const g = guide.find(x => x.id === attempt.value);
    const back = document.getElementById("back-classification");
    if (back && g) back.href = "/clasificacion/intento/" + g.id + "/";
    const box = document.getElementById("guide"); box.replaceChildren();
    if (!g) { box.append(IL.el("p", { class: "muted small", text: "Sin entrevista seleccionada." })); return; }
    if (!g.requirements.length) box.append(IL.el("p", { class: "muted small", text: "Aún no has clasificado requisitos en esta entrevista." }));
    g.requirements.forEach(r => box.append(IL.el("div", { class: "guide-req" }, [
      IL.el("span", { class: "tag " + (r.category === "RF" ? "rf" : "rnf"), text: r.category }),
      IL.el("span", { text: r.statement })
    ])));
    if (!F.system.value) F.system.value = g.system;
  }
  if (initial) {
    F.name.value = initial.name; F.system.value = initial.system_name;
    F.pre.value = initial.preconditions; F.post.value = initial.postconditions;
    if (initial.attempt_id) attempt.value = initial.attempt_id;
    Object.keys(lists).forEach(k => (initial[k] || []).forEach(v => addItem(lists[k], v, false)));
  } else {
    addItem(lists.primary_actors); addItem(lists.main_flow); addItem(lists.main_flow);
  }
  renderGuide();
  function payload() {
    const data = { id: ucId || null, name: F.name.value, system_name: F.system.value,
      preconditions: F.pre.value, postconditions: F.post.value, attempt_id: attempt.value };
    Object.entries(lists).forEach(([k, box]) => {
      data[k] = [...box.querySelectorAll(".list-item")].map(row => box.dataset.relations
        ? { type: row.querySelector("select").value, target: row.querySelector("input").value } : row.querySelector("input").value);
    });
    return data;
  }
  function signature(data) { const copy = { ...data }; delete copy.id; return JSON.stringify(copy); }
  function showErrors(errors, focus) {
    document.querySelectorAll(".field").forEach(field => {
      field.classList.remove("invalid"); field.querySelectorAll(".field-error").forEach(e => e.remove());
      field.querySelectorAll("input,textarea,select").forEach(e => { e.removeAttribute("aria-invalid"); e.removeAttribute("aria-describedby"); });
    });
    let first = null;
    Object.entries(errors || {}).forEach(([key, message]) => {
      const field = document.querySelector(`.field[data-field="${key}"]`); if (!field) return;
      const errorId = `error-${key}`; field.classList.add("invalid");
      field.append(IL.el("div", { class: "field-error", id: errorId, role: "alert", text: "✖ " + message }));
      field.querySelectorAll("input,textarea,select").forEach(e => { e.setAttribute("aria-invalid", "true"); e.setAttribute("aria-describedby", errorId); });
      first = first || field.querySelector("input,textarea,select,button");
    });
    if (first && focus) { first.focus(); first.scrollIntoView({ behavior: "smooth", block: "center" }); }
  }
  function checked() {
    const result = CU02Validation.check(payload(), rules); showErrors(result.errors, true);
    if (!result.ok) validation.innerHTML = IL.feedback("bad", "Revisa la plantilla.", " Corrige los campos marcados antes de continuar.");
    return result;
  }
  function feedback(result, title) {
    showErrors(result.errors || {}, !result.ok);
    validation.innerHTML = IL.feedback(result.ok ? "ok" : "bad", title, result.message || "") +
      (result.warnings || []).map(w => IL.feedback("hint", "Sugerencia:", " " + w)).join("");
  }
  function applyNormalized(data) {
    F.name.value = data.name; F.system.value = data.system_name;
    F.pre.value = data.preconditions; F.post.value = data.postconditions;
    Object.entries(lists).forEach(([k, box]) => box.querySelectorAll(".list-item").forEach((row, i) => {
      row.querySelector("input").value = k === "relations" ? data[k][i].target : data[k][i];
    }));
  }
  function setBusy(value) {
    busy = value; form.setAttribute("aria-busy", String(value));
    form.querySelectorAll("input,select,textarea,button").forEach(e => { e.disabled = value; });
    buttons.forEach(b => { b.disabled = value; });
    document.getElementById("preview-format").disabled = value;
    if (!value) { Object.values(lists).forEach(renumber); saveButton.disabled = !rendered; }
  }
  async function submit(action) {
    if (busy) return;
    const result = checked(); if (!result.ok) { rendered = null; saveButton.disabled = true; return; }
    if (action === "save" && rendered !== signature(result.data)) {
      invalidate(); return;
    }
    setBusy(true);
    try {
      const urls = { validate: form.dataset.validateUrl, generate: form.dataset.generateUrl, save: form.dataset.saveUrl };
      const response = await IL.api(urls[action], { ...result.data, format: document.getElementById("preview-format").value });
      feedback(response, response.ok ? "Estructura válida." : "No se pudo completar la operación.");
      if (!response.ok) { rendered = null; return; }
      applyNormalized(response.spec);
      if (action !== "validate") {
        const diagram = document.getElementById("diagram");
        if (response.image_format === "png" && response.png_data_uri) {
          const image = IL.el("img", { src: response.png_data_uri, alt: "Diagrama PNG generado por PlantUML", style: "max-width:100%;height:auto" });
          diagram.replaceChildren(image);
        } else diagram.innerHTML = response.svg;
        document.getElementById("preview-format").value = response.image_format || "svg";
        document.getElementById("code").textContent = response.plantuml_code;
        const tag = document.getElementById("engine-tag"); tag.hidden = false;
        tag.textContent = response.engine === "plantuml" ? "PlantUML real" : "Vista simplificada (no es PlantUML)";
        const status = document.getElementById("render-status");
        status.textContent = (response.cached ? "Cache SHA-256: acierto" : "Generacion nueva") +
          ` · ${response.duration_ms} ms` + (response.cache_warning ? " · " + response.cache_warning : "");
        rendered = signature(CU02Validation.check(payload(), rules).data);
      }
      if (action === "save") {
        // URL absoluta desde el prefijo actual, sin concatenar a /nuevo/.
        history.replaceState(null, "", form.dataset.listUrl + response.id + "/");
        ucId = response.id; document.getElementById("title").textContent = response.spec.name;
        document.getElementById("diagram-downloads").style.display = "flex";
        document.getElementById("download-svg").href = form.dataset.listUrl + ucId + "/diagrama/svg/";
        document.getElementById("download-png").href = form.dataset.listUrl + ucId + "/diagrama/png/";
        IL.toast(response.message, "ok"); IL.showBadges(response.badges);
      }
    } catch (error) {
      validation.innerHTML = IL.feedback("bad", "No se pudo completar la operación.", " Conserva tus campos y vuelve a intentar.");
    } finally { setBusy(false); }
  }
  form.addEventListener("input", invalidate);
  form.addEventListener("change", () => { renderGuide(); invalidate(); });
  form.addEventListener("submit", event => { event.preventDefault(); submit("validate"); });
  F.name.addEventListener("blur", () => { try { F.name.value = CU02Validation.text(F.name.value, false); } catch (e) { /* se mostrará al validar */ } });
  buttons[0].addEventListener("click", () => submit("validate"));
  buttons[1].addEventListener("click", () => submit("generate"));
  buttons[2].addEventListener("click", () => submit("save"));
  if (initial && document.querySelector("#diagram svg")) {
    const checkedInitial = CU02Validation.check(payload(), rules);
    if (checkedInitial.ok) rendered = signature(checkedInitial.data);
  }
  saveButton.disabled = !rendered;
})();
