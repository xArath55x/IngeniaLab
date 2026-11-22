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
    attempt_id: root.dataset.selected, covers: [], name: "", system_name: "", primary_actors: [],
    secondary_actors: [], preconditions: "", main_flow: [], alternate_flows: [], postconditions: "", relations: [],
  };
  let step = 0, saved = null, openMode = false;
  let selectedGoal = null;
  const current = () => guide.find((g) => g.id === data.attempt_id) || guide[0];
  const goal = () => current().goals[selectedGoal];
  data.system_name = current().system;

  function payload() {
    const { covers, ...rest } = data;
    return rest;
  }

  /* Requisitos que, según los casos de uso de referencia del escenario, son parte de otro caso de uso
   * (una regla, un paso o un caso incluido) y no la meta de un usuario. */
  const isRule = (statement) => {
    const req = current().requirements.find((r) => r.statement === statement);
    return Boolean(req && (current().part_of || []).includes(req.key));
  };

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
      kicker: "Punto de partida", title: "¿Qué quiere hacer el usuario?",
      help: "Elige una sola acción. Por ejemplo, en una biblioteca alguien puede querer consultar el catálogo.",
      fields: ["attempt_id"],
      render(area) {
        if (guide.length > 1) {
          const select = el("select", { class: "wizard-input", "aria-label": "Entrevista" },
            guide.map((g) => el("option", { value: g.id, text: g.label })));
          select.value = data.attempt_id;
          select.addEventListener("change", () => {
            selectGoal(null);
            data.attempt_id = select.value;
            data.system_name = current().system;
            show();
            $("step-area").querySelector("select").focus();
          });
          area.append(el("label", { class: "small muted", text: "Entrevista" }), select);
        }
        const rfs = current().requirements.filter((r) => r.category === "RF");
        const keys = new Set(rfs.map((r) => r.key));
        const options = Object.entries(current().goals)
          .filter(([key, item]) => item.unlocked || keys.has(key))
          .map(([key, item]) => [key, item.title]);
        options.push(["", "Crear un caso de uso propio"]);
        const choices = el("div", { class: "lesson-options", role: "group", "aria-label": "Acción del usuario" });
        for (const [key, title] of options) {
          choices.append(el("button", {
            type: "button", class: `lesson-option${key === selectedGoal ? " selected" : ""}`,
            "aria-pressed": String(key === selectedGoal), text: title,
            onclick: (event) => {
              selectGoal(key);
              for (const option of choices.children) {
                const chosen = option === event.currentTarget;
                option.classList.toggle("selected", chosen);
                option.setAttribute("aria-pressed", String(chosen));
              }
              $("step-error").replaceChildren();
              renderBuilt();
            },
          }));
        }
        area.append(choices);
        if (rfs.length) area.append(el("details", {}, [
          el("summary", { text: "Consultar mis requisitos funcionales" }),
          el("ul", { class: "small" }, rfs.map((r) => el("li", { text: r.statement }))),
        ]));
      },
    },
    {
      kicker: "Nombre", title: "¿Cómo se llama esta acción?",
      help: "Empieza con un verbo en infinitivo. Por ejemplo, «Consultar catálogo».",
      fields: ["name"],
      render(area) {
        area.append(input(data.name, "Ej. Registrar préstamo", (v) => { data.name = v; nameTip(); }));
        area.append(el("p", { class: "small", id: "name-tip" }));
        nameTip();
      },
    },
    {
      kicker: "Actores", title: "¿Quién inicia la acción?",
      help: "Escribe quién quiere lograr la meta. Por ejemplo, quien consulta el catálogo es el alumno.",
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
      kicker: "Antes de empezar", title: "¿Qué debe estar listo antes de empezar?",
      help: "Esto se llama precondición. Por ejemplo, «El bibliotecario ya inició sesión».",
      fields: ["preconditions"],
      render(area) { area.append(input(data.preconditions, "Ej. El bibliotecario inició sesión en el sistema.", (v) => { data.preconditions = v; }, true)); },
    },
    {
      kicker: "Flujo principal", title: "¿Qué pasa, paso a paso?",
      help: "Empieza con lo que hace la persona y luego explica cómo responde el sistema. Agrega al menos dos pasos.",
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
      help: "Piensa en un problema concreto y en cómo responde el sistema. Por ejemplo, si la clase está llena, el sistema avisa que ya no hay lugares.",
      fields: ["alternate_flows"], optional: true,
      render(area) {
        const ruleReqs = data.covers.filter(isRule);
        if (ruleReqs.length) area.append(el("div", { class: "feedback hint" }, [el("span", { class: "icon", text: "💡" }), el("div", {},
          [el("strong", { text: "Estas reglas pueden ayudarte a escribir una excepción." }),
           el("ul", { class: "small" }, ruleReqs.map((s) => el("li", { text: s })))])]));
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
      kicker: "Al terminar", title: "¿Cuál es el resultado si todo sale bien?",
      help: "Esto se llama postcondición. Por ejemplo, «La reserva quedó registrada».",
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

  function selectGoal(key) {
    if (key === selectedGoal) return;
    if (data.name === goal()?.title) data.name = "";
    selectedGoal = key;
    openMode = false;
    data.covers = key ? current().requirements
      .filter((r) => r.category === "RF" && (r.key === key || current().rule_of[r.key] === key))
      .map((r) => r.statement) : [];
  }

  function showProblem(children) {
    $("step-error").replaceChildren(el("div", { class: "feedback hint" },
      [el("span", { class: "icon", text: "💡" }), el("div", {}, children)]));
  }

  function routeFromOrigin() {
    if (selectedGoal === null) {
      showProblem([el("strong", { text: "Elige una acción o selecciona «Crear un caso de uso propio»." })]);
      return true;
    }
    const selected = goal();
    if (!selected || openMode) return false;
    if (selected.unlocked) {
      const form = $("wizard-guided");
      form.action = selected.start_url;
      form.elements.namedItem("attempt").value = data.attempt_id;
      $("btn-next").disabled = true;
      form.submit();
      return true;
    }
    showProblem([el("strong", { text: "Puedes empezar a escribir este caso de uso." }),
      el("p", { class: "small", text: "Para practicar con opciones, descubre sus requisitos en la entrevista y clasifícalos como funcionales." }),
      el("button", { type: "button", class: "btn small secondary", text: "Escribir mi caso de uso",
        onclick: () => {
          openMode = true;
          if (!data.name.trim()) data.name = selected.title;
          step += 1;
          show();
          focusInput();
        } })]);
    return true;
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
    // [etiqueta, valores, paso en que se llena, lista numerada]
    const parts = [
      ["Acción elegida", goal() ? [goal().title] : selectedGoal === "" ? ["Crear un caso de uso propio"] : [], 0],
      ["Nombre", data.name.trim() ? [data.name.trim()] : [], 1],
      ["Actor principal", data.primary_actors, 2],
      ["Actores secundarios", data.secondary_actors, 2],
      ["Precondición", data.preconditions.trim() ? [data.preconditions.trim()] : [], 3],
      ["Flujo principal", data.main_flow, 4, true],
      ["Flujos alternos", data.alternate_flows, 5],
      ["Postcondición", data.postconditions.trim() ? [data.postconditions.trim()] : [], 6],
      ["Relaciones", data.relations.map((r) => `«${r.type}» ${r.target}`), 7],
    ];
    // Solo se muestra lo construido y, vacío, lo que corresponde al paso actual.
    const visible = parts.filter(([label, values, at]) => values.length || (at === step && label !== "Actores secundarios"));
    $("built").replaceChildren(...(visible.length ? visible : [["Acción elegida", [], 0]]).flatMap(([label, values, , ordered]) => {
      const dd = el("dd", { class: values.length ? "" : "empty" });
      if (!values.length) dd.textContent = "Por construir";
      else if (ordered || values.length > 1) dd.append(el(ordered ? "ol" : "ul", {}, values.map((v) => el("li", { text: v }))));
      else dd.textContent = values[0];
      return [el("dt", { text: label }), dd];
    }));
  }

  function show() {
    const s = STEPS[step];
    $("step-kicker").textContent = s.kicker;
    $("step-title").textContent = s.title;
    $("step-help").textContent = s.help;
    $("step-context").replaceChildren(...(s.fields.includes("main_flow") ? data.covers.map((s) => el("li", { text: s })) : []));
    $("step-error").replaceChildren();
    const area = $("step-area"); area.replaceChildren(); s.render(area);
    $("progress").style.width = `${Math.round(100 * step / (STEPS.length - 1))}%`;
    $("step-count").textContent = `Paso ${step + 1} de ${STEPS.length}`;
    $("btn-back").disabled = step === 0;
    $("btn-next").disabled = false;
    $("btn-next").hidden = step === STEPS.length - 1;
    $("btn-next").textContent = s.optional ? "Siguiente (o saltar) →" : "Siguiente →";
    renderBuilt();
  }

  $("btn-next").addEventListener("click", () => {
    if (step === 0 && routeFromOrigin()) return;
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
  window.addEventListener("pageshow", () => { if (step === 0) $("btn-next").disabled = false; });
  window.addEventListener("beforeunload", (e) => {
    if (!saved && (data.name || data.main_flow.length)) { e.preventDefault(); e.returnValue = ""; }
  });
  show();
})();
