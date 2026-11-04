/* ACT-207A: validación pura, reutilizable en navegador y pruebas Node. */
(function (root) {
  "use strict";
  function text(value, multiline) {
    if (typeof value !== "string") throw new Error("Debe ser texto.");
    value = value.normalize("NFKC").replace(/\r\n?/g, "\n");
    if (/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value.replace(/[\n\t]/g, "")))
      throw new Error("El texto contiene caracteres de control no permitidos.");
    return multiline ? value.split("\n").map(s => s.trim()).join("\n").trim() : value.trim().replace(/\s+/gu, " ");
  }
  const key = value => value.toUpperCase().toLowerCase();
  const size = value => Array.from(value).length;
  function check(input, rules) {
    const errors = {}, data = {};
    function scalar(field, limit, required, multiline) {
      try {
        data[field] = text(input[field] == null ? "" : input[field], multiline);
        if (required && !data[field]) errors[field] = "Completa este campo obligatorio.";
        else if (size(data[field]) > limit) errors[field] = `Admite hasta ${limit} caracteres.`;
      } catch (e) { errors[field] = e.message; data[field] = ""; }
    }
    scalar("name", rules.name, true, false);
    scalar("system_name", rules.system_name, false, false);
    if (!data.system_name && !errors.system_name) data.system_name = "Sistema";
    scalar("preconditions", rules.conditions, true, true);
    scalar("postconditions", rules.conditions, true, true);
    function list(field, minimum, maximum, limit) {
      data[field] = [];
      const values = input[field] == null ? [] : input[field];
      if (!Array.isArray(values)) { errors[field] = "Debe ser una lista de textos."; return; }
      if (values.length < minimum || values.length > maximum) {
        errors[field] = `Debe contener entre ${minimum} y ${maximum} elementos.`; return;
      }
      values.forEach((v, i) => {
        try {
          const clean = text(v, false);
          if (!clean) throw new Error("está vacío: complétalo o elimina la fila.");
          if (size(clean) > limit) throw new Error(`admite hasta ${limit} caracteres.`);
          data[field].push(clean);
        } catch (e) { if (!errors[field]) errors[field] = `Elemento ${i + 1}: ${e.message}`; }
      });
    }
    list("primary_actors", 1, rules.max_actors, rules.actor);
    list("secondary_actors", 0, rules.max_actors, rules.actor);
    list("main_flow", rules.min_steps, rules.max_steps, rules.step);
    list("alternate_flows", 0, rules.max_alternates, rules.alternate);
    ["primary_actors", "secondary_actors"].forEach(field => {
      if (new Set(data[field].map(key)).size !== data[field].length)
        errors[field] = "Hay actores repetidos en la lista.";
    });
    if (data.primary_actors.some(a => data.secondary_actors.some(b => key(a) === key(b))))
      errors.secondary_actors = "Un actor no puede ser principal y secundario a la vez.";
    data.relations = [];
    const relations = input.relations == null ? [] : input.relations;
    if (!Array.isArray(relations) || relations.length > rules.max_relations)
      errors.relations = `Debe ser una lista de hasta ${rules.max_relations} relaciones.`;
    else {
      const seen = new Set();
      relations.forEach((r, i) => {
        try {
          if (!r || typeof r !== "object" || !["include", "extend"].includes(r.type))
            throw new Error("selecciona include o extend.");
          const target = text(r.target == null ? "" : r.target, false);
          if (!target || size(target) > rules.name) throw new Error(`escribe un destino de hasta ${rules.name} caracteres.`);
          if (key(target) === key(data.name)) throw new Error("un caso no puede relacionarse consigo mismo.");
          if (seen.has(key(target))) throw new Error("hay destinos de relación repetidos.");
          seen.add(key(target)); data.relations.push({ type: r.type, target });
        } catch (e) { if (!errors.relations) errors.relations = `Relación ${i + 1}: ${e.message}`; }
      });
    }
    data.attempt_id = input.attempt_id || "";
    if (typeof data.attempt_id !== "string" || (data.attempt_id && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(data.attempt_id)))
      errors.attempt_id = "La entrevista seleccionada no es válida.";
    if (input.id) data.id = input.id;
    return { ok: Object.keys(errors).length === 0, data, errors,
      numbered_steps: data.main_flow.map((value, i) => ({ number: i + 1, text: value })) };
  }
  const api = { check, text, key };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CU02Validation = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
