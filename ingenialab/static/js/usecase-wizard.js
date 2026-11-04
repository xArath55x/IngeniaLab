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
  const current = () => guide.find((g) => g.id === data.attempt_id) || guide[0];
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
      kicker: "Punto de partida", title: "¿Qué requisitos cubre tu caso de uso?",
      help: "Un caso de uso agrupa varios requisitos funcionales: uno es la meta del usuario (registrar, consultar, pedir…) y otros son reglas que se vuelven pasos o excepciones. Selecciona los que vas a modelar.",
      fields: ["attempt_id"],
      render(area) {
        if (guide.length > 1) {
          const select = el("select", { class: "wizard-input", "aria-label": "Entrevista" },
            guide.map((g) => el("option", { value: g.id, text: g.label })));
          select.value = data.attempt_id;
          select.addEventListener("change", () => { data.attempt_id = select.value; data.system_name = current().system; data.covers = []; openMode = false; show(); });
          area.append(el("label", { class: "small muted", text: "Entrevista" }), select);
        }
        const rfs = current().requirements.filter((r) => r.category === "RF");
        if (!rfs.length) area.append(el("p", { class: "muted", text: "No clasificaste requisitos funcionales en esta entrevista; puedes continuar de todos modos." }));
        area.append(el("div", { class: "lesson-options" }, rfs.map((r) => {
          const on = data.covers.includes(r.statement);
          const b = el("button", {
            type: "button", class: `lesson-option${on ? " selected" : ""}`, "aria-pressed": String(on),
            onclick: () => { data.covers = on ? data.covers.filter((s) => s !== r.statement) : [...data.covers, r.statement]; show(); },
          }, [el("span", { text: r.statement })]);
          return b;
        })));
        // Sin etiquetas: distinguir metas de reglas es lo que se practica; la retroalimentación llega al avanzar.
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
      help: "Describe el camino normal, sin errores. Alterna lo que hace el actor y lo que responde el sistema. Necesitas al menos 2 pasos; revisa que tus pasos cubran los requisitos de arriba.",
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
        const ruleReqs = data.covers.filter(isRule);
        if (ruleReqs.length) area.append(el("div", { class: "feedback hint" }, [el("span", { class: "icon", text: "💡" }), el("div", {},
          [el("strong", { text: "Estos requisitos son reglas o pasos: suelen escribirse como un paso de verificación, un flujo alterno o un caso de uso incluido:" }),
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

  /* Modo guiado: si la meta elegida tiene caso de uso de referencia, se construye con opciones (lección). */
  const keyOf = (statement) => (current().requirements.find((r) => r.statement === statement) || {}).key;
  const goalOf = (statement) => (current().goals || {})[keyOf(statement)];

  function startGuided(url) {
    const form = el("form", { method: "post", action: url }, [
      el("input", { type: "hidden", name: "csrfmiddlewaretoken", value: (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || "" }),
      el("input", { type: "hidden", name: "attempt", value: data.attempt_id }),
    ]);
    document.body.append(form);
    form.submit();
  }

  function showProblem(children, kind = "hint") {
    $("step-error").replaceChildren(el("div", { class: `feedback ${kind}` },
      [el("span", { class: "icon", text: kind === "ok" ? "✔" : "💡" }), el("div", {}, children)]));
  }

  // Devuelve true si el paso 1 ya decidió qué hacer (iniciar el modo guiado o mostrar un aviso).
  function routeFromOrigin() {
    if (openMode) return false;
    if (data.covers.length && data.covers.every(isRule)) {
      showProblem([el("strong", { text: "Lo que elegiste es una regla o un paso, no la meta de un usuario." }),
        el("p", { class: "small", text: "¿A qué acción del usuario pertenece? Por ejemplo, «impedir el préstamo si…» ocurre al registrar un préstamo: selecciona también el requisito de esa acción." })]);
      return true;
    }
    const goalKeys = [...new Set(data.covers.map(keyOf).filter((k) => k in (current().goals || {})))];
    if (goalKeys.length > 1) {
      showProblem([el("strong", { text: "Elegiste la meta de dos casos de uso distintos." }),
        el("p", { class: "small", text: "Un caso de uso tiene una sola meta del usuario: deja solo una y crea el otro después." })]);
      return true;
    }
    if (!goalKeys.length) return false;
    // Reglas que pertenecen a la meta de otro caso de uso.
    const ruleOf = current().rule_of || {};
    const foreign = data.covers.filter((s) => ruleOf[keyOf(s)] && ruleOf[keyOf(s)] !== goalKeys[0]);
    if (foreign.length) {
      showProblem([el("strong", { text: "Estos requisitos son reglas de otro caso de uso, no de este:" }),
        el("ul", { class: "small" }, foreign.map((s) => el("li", { text: s }))),
        el("p", { class: "small", text: "Quítalos o cambia la meta que elegiste." })]);
      return true;
    }
    const goal = current().goals[goalKeys[0]];
    if (goal.unlocked) {
      showProblem([el("strong", { text: "¡Bien! Elegiste la meta de un caso de uso." }),
        el("p", { class: "small", text: "Ahora lo construirás con preguntas de opción múltiple…" })], "ok");
      $("btn-next").disabled = true;
      setTimeout(() => startGuided(goal.start_url), 900);
      return true;
    }
    const missing = [...goal.not_discovered.map((t) => `Descubrir en la entrevista un requisito del tema «${t}».`),
      ...goal.not_classified.map((s) => `Clasificar como RF: «${s}»`)];
    showProblem([el("strong", { text: "Este caso de uso tiene un modo guiado con opciones, pero aún no se desbloquea:" }),
      el("ul", { class: "small" }, missing.map((m) => el("li", { text: m }))),
      el("button", { type: "button", class: "btn small secondary", text: "Continuar con respuestas abiertas",
        onclick: () => { openMode = true; step += 1; show(); focusInput(); } })]);
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
      ["Requisitos que cubre", data.covers, 0],
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
    $("built").replaceChildren(...(visible.length ? visible : [["Requisitos que cubre", [], 0]]).flatMap(([label, values, , ordered]) => {
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
    $("step-context").replaceChildren(...(step > 0 && step < STEPS.length - 1 ? data.covers.map((s) => el("li", { text: s })) : []));
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
  window.addEventListener("beforeunload", (e) => {
    if (!saved && (data.name || data.main_flow.length)) { e.preventDefault(); e.returnValue = ""; }
  });
  show();
})();
