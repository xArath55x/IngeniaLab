/* Lecciones guiadas de casos de uso (CU-02): un ejercicio por pantalla, vidas y retroalimentación inmediata.
 * El servidor califica; aquí solo se arma la respuesta y se muestra el resultado. */
(function () {
  "use strict";
  const root = document.getElementById("lesson");
  if (!root) return;
  let state = JSON.parse(document.getElementById("lesson-state").textContent);
  const $ = (id) => document.getElementById(id);
  const checkBtn = $("btn-check");
  let answer = null, pendingNext = null, busy = false;

  /* Tarjeta «Tu caso de uso»: cada acierto llena su parte; lo pendiente se muestra vacío. */
  let filled = new Set();
  function renderBuilt() {
    $("built").replaceChildren(...state.built.flatMap((part) => {
      const isNew = part.values && !filled.has(part.id);
      const dd = IL.el("dd", { class: `built-item${part.values ? "" : " empty"}${isNew ? " new" : ""}` });
      if (!part.values) dd.textContent = "Por construir";
      else if (part.id === "main_flow") dd.append(IL.el("ol", {}, part.values.map((v) => IL.el("li", { text: v }))));
      else dd.textContent = part.values.join(" · ");
      return [IL.el("dt", { text: part.label }), dd];
    }));
    filled = new Set(state.built.filter((p) => p.values).map((p) => p.id));
  }

  function renderHeader() {
    $("progress").style.width = `${Math.round(100 * state.solved / state.total)}%`;
    const lives = $("lives");
    lives.textContent = "❤️".repeat(state.lives) + "🤍".repeat(state.max_lives - state.lives);
    lives.setAttribute("aria-label", `${state.lives} de ${state.max_lives} vidas`);
  }

  function button(text, cls, onClick) {
    return IL.el("button", { type: "button", class: cls, text, onclick: onClick });
  }

  function setReady(ready) { checkBtn.disabled = !ready || busy; }

  function renderChoice(ex, area) {
    ex.options.forEach((o) => area.append(button(o.text, "lesson-option", (e) => {
      area.querySelectorAll(".lesson-option").forEach((b) => b.classList.remove("selected"));
      e.currentTarget.classList.add("selected");
      answer = o.id; setReady(true);
    })));
  }

  function renderMulti(ex, area) {
    const chosen = new Set();
    ex.options.forEach((o) => {
      const b = button(o.text, "lesson-option", () => {
        chosen.has(o.id) ? chosen.delete(o.id) : chosen.add(o.id);
        b.classList.toggle("selected", chosen.has(o.id));
        b.setAttribute("aria-pressed", String(chosen.has(o.id)));
        answer = [...chosen]; setReady(chosen.size > 0);
      });
      b.setAttribute("aria-pressed", "false");
      area.append(b);
    });
  }

  function renderOrder(ex, area) {
    const picked = IL.el("ol", { class: "lesson-sequence", "aria-label": "Tu orden" });
    const pool = IL.el("div", { class: "lesson-pool", "aria-label": "Pasos disponibles" });
    const order = [];
    const sync = () => {
      picked.replaceChildren(...order.map((id, i) => {
        const o = ex.options.find((x) => x.id === id);
        return IL.el("li", {}, [button(`${i + 1}. ${o.text}`, "lesson-tile placed", () => {
          order.splice(order.indexOf(id), 1); sync();
        })]);
      }));
      pool.replaceChildren(...ex.options.filter((o) => !order.includes(o.id)).map((o) =>
        button(o.text, "lesson-tile", () => { order.push(o.id); sync(); })));
      if (!order.length) picked.append(IL.el("li", { class: "muted small", text: "Toca los pasos en el orden en que ocurren." }));
      answer = [...order]; setReady(order.length === ex.options.length);
    };
    area.append(picked, pool);
    sync();
  }

  function renderClassify(ex, area) {
    const chosen = {};
    ex.options.forEach((o) => {
      const row = IL.el("div", { class: "lesson-classify" }, [IL.el("span", { class: "lesson-classify-item", text: o.text })]);
      ex.categories.forEach((c) => {
        const b = button(c.text, "lesson-option small", () => {
          chosen[o.id] = c.id;
          row.querySelectorAll("button").forEach((x) => x.classList.toggle("selected", x === b));
          answer = { ...chosen }; setReady(Object.keys(chosen).length === ex.options.length);
        });
        row.append(b);
      });
      area.append(row);
    });
  }

  function renderExercise(ex) {
    answer = null; pendingNext = null;
    $("ex-title").textContent = ex.title;
    $("ex-prompt").textContent = ex.prompt;
    $("ex-context").replaceChildren(...ex.context.map((t) => IL.el("li", { text: t })));
    const area = $("ex-area"); area.replaceChildren();
    area.className = ex.type === "order" ? "" : "lesson-options";
    ({ choice: renderChoice, multi: renderMulti, order: renderOrder, classify: renderClassify })[ex.type](ex, area);
    $("feedback").replaceChildren(); $("footer").className = "lesson-footer";
    checkBtn.textContent = "Comprobar"; setReady(false);
    $("ex-prompt").focus?.();
  }

  async function saveUseCase() {
    const btn = $("finish-save");
    btn.disabled = true; $("finish-status").textContent = "Generando el diagrama UML…";
    const r = await IL.api(root.dataset.saveUrl, {});
    if (!r.ok) {
      btn.disabled = false; $("finish-status").textContent = r.message || "No se pudo generar el diagrama. Intenta de nuevo.";
      return;
    }
    $("finish-diagram").innerHTML = r.svg;
    $("finish-status").textContent = r.engine === "plantuml"
      ? "✔ Guardado en tus casos de uso." : "✔ Guardado en tus casos de uso (vista simplificada, no es PlantUML).";
    btn.hidden = true;
    $("finish-view").href = r.edit_url; $("finish-view").hidden = false;
    IL.showBadges(r.badges);
  }

  function renderFinish() {
    $("exercise").hidden = true; $("footer").hidden = true; $("finish").hidden = false;
    $("finish-back").href = $("finish-back-done").href = root.dataset.lessonsUrl;
    if (state.lesson_status === "completed") {
      $("finish-icon").textContent = "🏆";
      $("finish-title").textContent = "¡Construiste tu caso de uso!";
      $("finish-text").textContent = `Ganaste ${state.xp} XP con ${state.lives} ${state.lives === 1 ? "vida" : "vidas"} restante(s). ` +
        "Revisa la tarjeta de la derecha y genera su diagrama UML: quedará guardado en Modelado.";
      $("finish-editor").href = root.dataset.editorUrl;
      $("finish-done").hidden = false;
      $("finish-save").addEventListener("click", saveUseCase);
      if (state.saved) saveUseCase();  // ya guardado: solo vuelve a mostrar el diagrama
    } else {
      $("finish-icon").textContent = "💔";
      $("finish-title").textContent = "Te quedaste sin vidas";
      $("finish-text").textContent = "Repasa las explicaciones y vuelve a intentarlo: la lección empieza de nuevo.";
      $("finish-failed").hidden = false;
    }
  }

  function showFeedback(r) {
    const fb = $("feedback");
    const title = r.correct ? "¡Correcto!" : "Respuesta incorrecta";
    const body = IL.el("div", {}, [IL.el("strong", { text: title })]);
    if (!r.correct) {
      body.append(IL.el("p", { class: "small", text: "Respuesta correcta:" }),
        IL.el("ul", { class: "small" }, r.solution.map((s) => IL.el("li", { text: s }))));
    }
    body.append(IL.el("p", { class: "small", text: r.explanation }));
    fb.replaceChildren(body);
    $("footer").className = `lesson-footer ${r.correct ? "ok" : "bad"}`;
    checkBtn.textContent = "Continuar"; checkBtn.disabled = false;
  }

  checkBtn.addEventListener("click", async () => {
    if (pendingNext) {
      state = pendingNext; renderHeader();
      return state.lesson_status === "in_progress" ? renderExercise(state.current) : renderFinish();
    }
    if (answer === null || busy) return;
    busy = true; checkBtn.disabled = true;
    const r = await IL.api(root.dataset.answerUrl, { exercise_id: state.current.id, answer });
    busy = false;
    if (!r.ok) { IL.toast(r.message || "No se pudo registrar la respuesta.", "bad"); window.location.reload(); return; }
    $("ex-area").querySelectorAll("button").forEach((b) => (b.disabled = true));
    pendingNext = r;
    state = { ...state, lives: r.lives, solved: r.solved, built: r.built }; renderHeader(); renderBuilt();
    showFeedback(r);
  });

  renderHeader(); renderBuilt();
  state.lesson_status === "in_progress" ? renderExercise(state.current) : renderFinish();
})();
