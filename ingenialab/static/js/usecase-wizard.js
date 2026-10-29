/* Asistente paso a paso para crear un caso de uso propio (CU-02).
 * Una pregunta por pantalla; la tarjeta «Tu caso de uso» se arma en vivo. Valida con CU02Validation
 * (las mismas reglas que el editor) y usa sus API para generar el diagrama y guardar. */
(function () {
  "use strict";
  const root = document.getElementById("wizard");
  if (!root) return;
  const $ = (id) => document.getElementById(id);
  const el = IL.el;
  const guide = JSON.parse($("guide-data").textContent);
  const rules = JSON.parse($("validation-rules").textContent);
  const data = {
    attempt_id: root.dataset.selected, origin: "", name: "", system_name: "", primary_actors: [],
    secondary_actors: [], preconditions: "", main_flow: [], alternate_flows: [], postconditions: "", relations: [],
  };
  let step = 0, saved = null;
  const current = () => guide.find((g) => g.id === data.attempt_id) || guide[0];
  data.system_name = current().system;

  function payload() {
    const { origin, ...rest } = data;
    return rest;
  }

  function input(value, placeholder, onInput, multiline) {
    const node = el(multiline ? "textarea" : "input", { type: "text", placeholder, class: "wizard-input" });
    node.value = value;
    node.addEventListener("input", () => { onInput(node.value); renderBuilt(); });
    return node;
  }

  function chip(text, active, onClick, title) {
    return el("button", { type: "button", class: `chip${active ? " active" : ""}`, text, title: title || text, onclick: onClick });
  }

  function editableList(values, render) {
    return el("ol", { class: "wizard-list" }, values.map((v, i) => el("li", {}, [
      el("span", { text: render ? render(v) : v }),
      el("button", { type: "button", class: "icon-btn", text: "✕", "aria-label": `Quitar elemento ${i + 1}`,
        onclick: () => { values.splice(i, 1); show(); } }),
    ])));
  }

  /* ---------- Pasos ---------- */
  const STEPS = [
    {
      kicker: "Punto de partida", title: "¿De qué requisito sale tu caso de uso?",
      help: "Un caso de uso suele salir de un requisito funcional (RF): algo que el sistema debe hacer para un usuario. Elige uno de los que clasificaste (opcional).",
      fields: ["attempt_id"],
      render(area) {
        if (guide.length > 1) {
          const select = el("select", { class: "wizard-input", "aria-label": "Entrevista" },
            guide.map((g) => el("option", { value: g.id, text: g.label })));
          select.value = data.attempt_id;
          select.addEventListener("change", () => { data.attempt_id = select.value; data.system_name = current().system; data.origin = ""; show(); });
          area.append(el("label", { class: "small muted", text: "Entrevista" }), select);
        }
        const rfs = current().requirements.filter((r) => r.category === "RF");
        if (!rfs.length) area.append(el("p", { class: "muted", text: "No clasificaste requisitos funcionales en esta entrevista; puedes continuar de todos modos." }));
        area.append(el("div", { class: "lesson-options" }, rfs.map((r) => el("button", {
          type: "button", class: `lesson-option${data.origin === r.statement ? " selected" : ""}`, text: r.statement,
          onclick: () => { data.origin = data.origin === r.statement ? "" : r.statement; show(); },
        }))));
      },
    },
    {
      kicker: "Nombre", title: "¿Qué quiere lograr el actor?",
      help: "Nómbralo con un verbo en infinitivo y un objeto: «Registrar préstamo», «Consultar catálogo». No uses el nombre del sistema ni una oración completa.",
      fields: ["name"],
      render(area) {
        area.append(input(data.name, "Ej. Registrar préstamo", (v) => { data.name = v; nameTip(); }));
        area.append(el("p", { class: "small", id: "name-tip" }));
        nameTip();
      },
    },
    {
      kicker: "Actores", title: "¿Quién participa?",
      help: "El actor principal inicia el caso de uso para lograr su meta. Los secundarios lo apoyan sin iniciarlo, como un servicio externo.",
      fields: ["primary_actors", "secondary_actors"],
      render(area) {
        const suggestions = current().actors || [];
        area.append(el("p", { class: "wizard-label", text: "Actor principal" }));
        area.append(input(data.primary_actors[0] || "", "Ej. Bibliotecario", (v) => { data.primary_actors = v.trim() ? [v] : []; }));
        if (suggestions.length) area.append(el("div", { class: "chips" }, suggestions.map((a) =>
          chip(a, data.primary_actors[0] === a, () => { data.primary_actors = [a]; data.secondary_actors = data.secondary_actors.filter((s) => s !== a); show(); }))));
        area.append(el("p", { class: "wizard-label", text: "Actores secundarios (opcional)" }));
        if (data.secondary_actors.length) area.append(editableList(data.secondary_actors));
        const extra = input("", "Ej. Servicio de correo", () => {});
        extra.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addSecondary(extra.value); } });
        area.append(el("div", { class: "wizard-row" }, [extra, el("button", { type: "button", class: "btn secondary", text: "Agregar", onclick: () => addSecondary(extra.value) })]));
        const others = suggestions.filter((a) => a !== data.primary_actors[0] && !data.secondary_actors.includes(a));
        if (others.length) area.append(el("div", { class: "chips" }, others.map((a) => chip(`+ ${a}`, false, () => addSecondary(a)))));
      },
    },
    {
      kicker: "Antes de empezar", title: "¿Qué debe ser cierto ANTES de empezar?",
      help: "La precondición describe el estado necesario para iniciar, por ejemplo «El bibliotecario inició sesión». No es un paso ni el resultado.",
      fields: ["preconditions"],
      render(area) { area.append(input(data.preconditions, "Ej. El bibliotecario inició sesión en el sistema.", (v) => { data.preconditions = v; }, true)); },
    },
    {
      kicker: "Flujo principal", title: "¿Qué pasa, paso a paso?",
      help: "Describe el camino normal, sin errores. Alterna lo que hace el actor y lo que responde el sistema. Necesitas al menos 2 pasos.",
      fields: ["main_flow"],
      render(area) {
        if (data.main_flow.length) area.append(editableList(data.main_flow));
        const n = data.main_flow.length + 1;
        const actor = data.primary_actors[0] ? `el actor (${data.primary_actors[0]})` : "el actor";
        area.append(el("p", { class: "wizard-label", text: n % 2 ? `Paso ${n}: ¿qué hace ${actor}?` : `Paso ${n}: ¿qué responde el sistema?` }));
        const field = input("", n % 2 ? "Ej. El bibliotecario captura la matrícula del alumno." : "Ej. El sistema muestra los préstamos activos.", () => {});
        const add = () => { if (field.value.trim()) { data.main_flow.push(field.value.trim()); show(); focusInput(); } };
        field.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
        area.append(el("div", { class: "wizard-row" }, [field, el("button", { type: "button", class: "btn secondary", text: "Agregar paso", onclick: add })]));
      },
    },
    {
      kicker: "Excepciones (opcional)", title: "¿Qué pasa si algo sale distinto?",
      help: "Un flujo alterno indica en qué paso puede cambiar el camino, la condición y cómo responde el sistema. Por ejemplo: si el alumno ya tiene tres libros, el sistema rechaza el préstamo.",
      fields: ["alternate_flows"], optional: true,
      render(area) {
        if (data.alternate_flows.length) area.append(editableList(data.alternate_flows));
        if (!data.main_flow.length) return area.append(el("p", { class: "muted", text: "Primero escribe el flujo principal." }));
        const at = el("select", { class: "wizard-input", "aria-label": "Paso" }, data.main_flow.map((s, i) => el("option", { value: i + 1, text: `Paso ${i + 1}: ${s}` })));
        const cond = input("", "Si… (ej. el alumno ya tiene tres libros prestados)", () => {});
        const resp = input("", "…entonces el sistema… (ej. rechaza el préstamo e indica el motivo)", () => {});
        const add = () => {
          if (!cond.value.trim() || !resp.value.trim()) return;
          const c = cond.value.trim().replace(/^si\s+/i, ""), r = resp.value.trim().replace(/[.\s]+$/, "");
          data.alternate_flows.push(`FA-${data.alternate_flows.length + 1} (paso ${at.value}): Si ${c}, ${r}.`);
          show();
        };
        area.append(el("p", { class: "wizard-label", text: "¿En qué paso?" }), at,
          el("p", { class: "wizard-label", text: "¿Qué condición lo cambia?" }), cond,
          el("p", { class: "wizard-label", text: "¿Qué hace el sistema entonces?" }), resp,
          el("div", { class: "btn-row", style: "margin-top:.6rem" }, [el("button", { type: "button", class: "btn secondary", text: "Agregar flujo alterno", onclick: add })]));
      },
    },
    {
      kicker: "Al terminar", title: "¿Qué queda cierto cuando termina con éxito?",
      help: "La postcondición describe el resultado, por ejemplo «El préstamo queda registrado con su fecha de devolución».",
      fields: ["postconditions"],
      render(area) { area.append(input(data.postconditions, "Ej. El préstamo queda registrado con su fecha de devolución.", (v) => { data.postconditions = v; }, true)); },
    },
    {
      kicker: "Relaciones (opcional)", title: "¿Se relaciona con otros casos de uso?",
      help: "«include»: otro caso de uso que SIEMPRE se ejecuta como parte de este (ej. Verificar límite de préstamos). «extend»: comportamiento OPCIONAL que solo se agrega en ciertas condiciones (ej. Calcular multa).",
      fields: ["relations"], optional: true,
      render(area) {
        if (data.relations.length) area.append(editableList(data.relations, (r) => `«${r.type}» ${r.target}`));
        const target = input("", "Nombre del otro caso de uso", () => {});
        let type = "include";
        const types = el("div", { class: "chips" });
        const paint = () => types.replaceChildren(
          chip("«include» siempre", type === "include", () => { type = "include"; paint(); }),
          chip("«extend» opcional", type === "extend", () => { type = "extend"; paint(); }));
        paint();
        const add = () => { if (target.value.trim()) { data.relations.push({ type, target: target.value.trim() }); show(); } };
        area.append(types, el("div", { class: "wizard-row" }, [target, el("button", { type: "button", class: "btn secondary", text: "Agregar", onclick: add })]));
      },
    },
    {
      kicker: "Listo", title: "Revisa tu caso de uso y genera el diagrama",
      help: "Revisa la tarjeta. Si algo no te convence, regresa con «Atrás». Al generar, el diagrama UML aparece aquí y puedes guardarlo.",
      fields: [],
      render(area) {
        const diagram = el("div", { class: "diagram lesson-diagram", id: "wizard-diagram" }, [el("p", { class: "muted", text: "El diagrama aparecerá aquí." })]);
        const status = el("p", { class: "small", id: "wizard-status", role: "status" });
        const generate = el("button", { type: "button", class: "btn", id: "wizard-generate", text: "Generar diagrama" });
        const save = el("button", { type: "button", class: "btn", id: "wizard-save", text: "Guardar en mis casos de uso", hidden: "" });
        generate.addEventListener("click", async () => {
          generate.disabled = true; status.textContent = "Generando el diagrama UML…";
          const r = await IL.api(root.dataset.generateUrl, { ...payload(), format: "svg" });
          generate.disabled = false;
          if (!r.ok) return serverError(r, status);
          diagram.innerHTML = r.svg;
          status.textContent = r.engine === "plantuml" ? "Diagrama listo. Si te convence, guárdalo." : "Vista simplificada (no es PlantUML). Puedes guardarlo.";
          generate.textContent = "Volver a generar"; generate.className = "btn secondary"; save.hidden = false;
        });
        save.addEventListener("click", async () => {
          save.disabled = true; status.textContent = "Guardando…";
          const r = await IL.api(root.dataset.saveUrl, payload());
          if (!r.ok) { save.disabled = false; return serverError(r, status); }
          saved = r.id;
          status.textContent = "✔ Guardado en tus casos de uso.";
          save.hidden = true; generate.hidden = true;
          buttons.append(el("a", { class: "btn", href: `${root.dataset.listUrl}${r.id}/`, text: "Ver o editar" }),
            el("a", { class: "btn ghost", href: window.location.pathname, text: "Crear otro" }));
          document.querySelector(".lesson-footer").hidden = true;
          IL.showBadges(r.badges);
        });
        const buttons = el("div", { class: "btn-row", style: "justify-content:center" }, [generate, save]);
        area.append(diagram, status, buttons);
      },
    },
  ];

  function addSecondary(value) {
    const v = value.trim();
    if (v && !data.secondary_actors.includes(v) && v !== data.primary_actors[0]) data.secondary_actors.push(v);
    show();
  }

  function nameTip() {
    const tip = $("name-tip");
    if (!tip) return;
    const first = data.name.trim().split(/\s+/)[0] || "";
    const ok = /(ar|er|ir)$/i.test(first);
    tip.textContent = !first ? "" : ok ? "✔ Empieza con un verbo en infinitivo." : `💡 «${first}» no parece un verbo en infinitivo (terminado en -ar, -er o -ir).`;
    tip.className = `small ${ok ? "ok-text" : "hint-text"}`;
  }

  function focusInput() { const f = $("step-area").querySelector("input, textarea"); if (f) f.focus(); }

  // Errores del servidor: indica en qué paso corregir.
  function serverError(r, status) {
    const fields = Object.keys(r.errors || {});
    const target = STEPS.findIndex((s) => s.fields.some((f) => fields.includes(f)));
    status.textContent = (r.message || "Revisa el caso de uso.") + (target >= 0 ? ` Revisa el paso «${STEPS[target].kicker}».` : "");
  }

  /* ---------- Tarjeta y navegación ---------- */
  function renderBuilt() {
    const parts = [
      ["Requisito de origen", data.origin ? [data.origin] : null],
      ["Nombre", data.name.trim() ? [data.name.trim()] : null],
      ["Actor principal", data.primary_actors.length ? data.primary_actors : null],
      ["Actores secundarios", data.secondary_actors.length ? data.secondary_actors : null],
      ["Precondición", data.preconditions.trim() ? [data.preconditions.trim()] : null],
      ["Flujo principal", data.main_flow.length ? data.main_flow : null, true],
      ["Flujos alternos", data.alternate_flows.length ? data.alternate_flows : null],
      ["Postcondición", data.postconditions.trim() ? [data.postconditions.trim()] : null],
      ["Relaciones", data.relations.length ? data.relations.map((r) => `«${r.type}» ${r.target}`) : null],
    ];
    $("built").replaceChildren(...parts.flatMap(([label, values, ordered]) => {
      const dd = el("dd", { class: values ? "" : "empty" });
      if (!values) dd.textContent = "Por construir";
      else if (ordered) dd.append(el("ol", {}, values.map((v) => el("li", { text: v }))));
      else dd.textContent = values.join(" · ");
      return [el("dt", { text: label }), dd];
    }));
  }

  function show() {
    const s = STEPS[step];
    $("step-kicker").textContent = s.kicker;
    $("step-title").textContent = s.title;
    $("step-help").textContent = s.help;
    $("step-context").replaceChildren(...(data.origin && step > 0 && step < STEPS.length - 1 ? [el("li", { text: data.origin })] : []));
    $("step-error").replaceChildren();
    const area = $("step-area"); area.replaceChildren(); s.render(area);
    $("progress").style.width = `${Math.round(100 * step / (STEPS.length - 1))}%`;
    $("step-count").textContent = `Paso ${step + 1} de ${STEPS.length}`;
    $("btn-back").disabled = step === 0;
    $("btn-next").hidden = step === STEPS.length - 1;
    $("btn-next").textContent = s.optional ? "Siguiente (o saltar) →" : "Siguiente →";
    renderBuilt();
  }

  $("btn-next").addEventListener("click", () => {
    const errors = CU02Validation.check(payload(), rules).errors;
    // Mensajes del asistente para los casos más comunes; el resto viene de la validación del editor.
    if (!data.primary_actors.length) errors.primary_actors = "Escribe quién inicia el caso de uso.";
    if (data.main_flow.length < rules.min_steps) errors.main_flow = `Agrega al menos ${rules.min_steps} pasos.`;
    const problem = STEPS[step].fields.map((f) => errors[f]).find(Boolean);
    if (problem) {
      $("step-error").replaceChildren(el("div", { class: "feedback bad" }, [el("span", { class: "icon", text: "✖" }), el("div", { text: problem })]));
      return focusInput();
    }
    step += 1; show(); focusInput();
  });
  $("btn-back").addEventListener("click", () => { if (step > 0 && !saved) { step -= 1; show(); } });
  window.addEventListener("beforeunload", (e) => {
    if (!saved && (data.name || data.main_flow.length)) { e.preventDefault(); e.returnValue = ""; }
  });
  show();
})();
