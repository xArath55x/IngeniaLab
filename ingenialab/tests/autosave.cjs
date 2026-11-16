/* ACT-307A (CU-10): ciclo de autoguardado con DOM, fetch y reloj simulados, sin dependencias npm.
 * Ejecutar: node tests/autosave.cjs */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const js = name => fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8');
const flush = async () => { for (let i = 0; i < 20; i++) await new Promise(r => setImmediate(r)); };
const response = (status, data) => ({ status, json: async () => data });

function setup(handler) {
  const intervals = [];
  const listeners = {};
  const requests = [];
  const body = { dataset: { userId: '7' }, append() {} };
  const document = { body, cookie: 'csrftoken=tok', createElement: () => ({}), querySelector: () => null, addEventListener() {} };
  let n = 0;
  const window = {
    addEventListener: (k, f) => { (listeners[k] = listeners[k] || []).push(f); },
    crypto: { randomUUID: () => '00000000-0000-4000-8000-' + String(++n).padStart(12, '0') },
  };
  const fetch = async (url, init) => {
    const req = { url, method: init.method, headers: init.headers, body: init.body ? JSON.parse(init.body) : null };
    requests.push(req);
    return handler(req, requests);
  };
  const ctx = { document, window, fetch, AbortController, setTimeout, clearTimeout, console,
    setInterval: (f, ms) => { intervals.push({ f, ms }); return intervals.length; }, clearInterval: () => {} };
  vm.runInNewContext(js('app.js'), ctx);
  vm.runInNewContext(js('autosave.js'), ctx);
  const states = [];
  let screen = { name: 'Registrar préstamo' };
  const saver = window.IL.autosave.start({
    module: 'modeling', key: 'nuevo:11111111-1111-4111-8111-111111111111',
    collect: () => screen, onState: (s, info) => states.push([s, info]),
  });
  return {
    saver, states, requests, intervals, listeners, window,
    set screen(v) { screen = v; },
    tick: async () => { await intervals[0].f(); await flush(); },
    posts: () => requests.filter(r => r.method === 'POST'),
  };
}
const notFound = response(200, { ok: true, found: false });
const ok = rev => response(200, { ok: true, revision: rev, paused: false, saved_at: '2026-11-16T10:42:00-06:00' });
const cases = [];
const test = (name, action) => cases.push({ name, action });

test('programa el ciclo cada 30 s y consulta el punto previo', async () => {
  const e = setup(req => req.method === 'GET' ? notFound : ok(1));
  await e.saver.ready;
  assert.equal(e.intervals.length, 1);
  assert.equal(e.intervals[0].ms, 30000);
  assert.equal(e.requests[0].method, 'GET');
  assert.equal(e.requests[0].url, '/api/checkpoints/modeling/nuevo%3A11111111-1111-4111-8111-111111111111/');
});

test('sin cambios no envía nada', async () => {
  const e = setup(req => req.method === 'GET' ? notFound : ok(1));
  await e.saver.ready; await e.tick(); await e.tick();
  assert.equal(e.posts().length, 0);
});

test('con cambios envía módulo, clave, revisión, esquema, CSRF e identidad, y adopta la revisión', async () => {
  const e = setup(req => req.method === 'GET' ? notFound : ok(req.body.revision + 1));
  await e.saver.ready;
  e.saver.markDirty(); await e.tick();
  const [first] = e.posts();
  assert.equal(first.url, '/api/checkpoints/');
  assert.deepEqual({ ...first.body, payload: { ...first.body.payload } },
    { module: 'modeling', key: 'nuevo:11111111-1111-4111-8111-111111111111', revision: 0, pause: false,
      payload: { schema: 1, name: 'Registrar préstamo' } });
  assert.equal(first.headers['X-CSRFToken'], 'tok');
  assert.equal(first.headers['X-IngeniaLab-User'], '7');
  assert.equal(e.saver.revision, 1);
  assert.equal(e.saver.dirty, false);
  assert.equal(e.states.at(-1)[0], 'saved');
  e.screen = { name: 'Otro nombre' }; e.saver.markDirty(); await e.tick();
  assert.equal(e.posts()[1].body.revision, 1);
  assert.equal(e.saver.revision, 2);
});

test('un punto previo fija la revisión y avisa con «found»', async () => {
  const e = setup(req => req.method === 'GET'
    ? response(200, { ok: true, found: true, revision: 4, payload: { schema: 1, name: 'Viejo' }, paused: true })
    : ok(req.body.revision + 1));
  await e.saver.ready;
  assert.equal(e.saver.revision, 4);
  assert.equal(e.states[0][0], 'found');
  assert.equal(e.states[0][1].checkpoint.payload.name, 'Viejo');
  e.saver.markDirty(); await e.tick();
  assert.equal(e.posts()[0].body.revision, 4);
});

test('sin red queda pendiente, avisa «offline» y reintenta en el siguiente ciclo', async () => {
  let fail = true;
  const e = setup(req => {
    if (req.method === 'GET') return notFound;
    if (fail) throw new TypeError('Failed to fetch');
    return ok(1);
  });
  await e.saver.ready;
  e.saver.markDirty(); await e.tick();
  assert.equal(e.states.at(-1)[0], 'offline');
  assert.equal(e.saver.dirty, true);
  fail = false; await e.tick();
  assert.equal(e.saver.dirty, false);
  assert.equal(e.posts().length, 2);
});

test('al volver la conexión reintenta sin esperar el ciclo', async () => {
  let fail = true;
  const e = setup(req => { if (req.method === 'GET') return notFound; if (fail) throw new TypeError('x'); return ok(1); });
  await e.saver.ready;
  e.saver.markDirty(); await e.tick();
  fail = false;
  await e.listeners.online.at(-1)();  // El de autosave.js (app.js registra antes su aviso visual).
  await flush();
  assert.equal(e.saver.dirty, false);
});

test('401 en segundo plano no abre modal, avisa «session» y conserva los cambios', async () => {
  const e = setup(req => req.method === 'GET' ? notFound : response(401, { ok: false, error: 'session_expired' }));
  await e.saver.ready;
  e.saver.markDirty(); await e.tick();
  assert.equal(e.states.at(-1)[0], 'session');
  assert.equal(e.saver.dirty, true);
});

test('409 de revisión detiene el ciclo sin volver a enviar', async () => {
  const e = setup(req => req.method === 'GET' ? notFound
    : response(409, { ok: false, error: 'revision_conflict', server_revision: 3, message: 'Otra pestaña' }));
  await e.saver.ready;
  e.saver.markDirty(); await e.tick();
  assert.equal(e.states.at(-1)[0], 'conflict');
  e.saver.markDirty(); await e.tick();
  assert.equal(e.posts().length, 1);
});

test('práctica cerrada detiene el ciclo y no deja cambios pendientes', async () => {
  const e = setup(req => req.method === 'GET' ? notFound : response(409, { ok: false, error: 'practice_closed' }));
  await e.saver.ready;
  e.saver.markDirty(); await e.tick();
  assert.equal(e.states.at(-1)[0], 'closed');
  assert.equal(e.saver.dirty, false);
});

test('saveNow envía pause y espera al guardado en curso para no repetir la revisión', async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const e = setup(async req => {
    if (req.method === 'GET') return notFound;
    if (req.body.revision === 0) { await gate; return ok(1); }
    return ok(req.body.revision + 1);
  });
  await e.saver.ready;
  e.saver.markDirty();
  const background = e.tick();
  await flush();
  const explicit = e.saver.saveNow({ pause: true });
  release(); await background;
  const result = await explicit;
  assert.equal(result.ok, true);
  const [a, b] = e.posts();
  assert.equal(a.body.revision, 0);
  assert.equal(b.body.revision, 1);
  assert.equal(b.body.pause, true);
});

test('switchKey descarta el borrador y continúa con la nueva clave', async () => {
  const e = setup(req => req.method === 'GET' ? notFound : (req.url.endsWith('descartar/') ? response(200, { ok: true }) : ok(1)));
  await e.saver.ready;
  e.saver.markDirty(); await e.tick();
  await e.saver.switchKey('22222222-2222-4222-8222-222222222222');
  assert.ok(e.requests.some(r => r.url === '/api/checkpoints/modeling/nuevo%3A11111111-1111-4111-8111-111111111111/descartar/'));
  assert.equal(e.saver.revision, 0);
  assert.equal(e.saver.dirty, false);
  e.saver.markDirty(); await e.tick();
  assert.equal(e.posts().at(-1).body.key, '22222222-2222-4222-8222-222222222222');
});

test('beforeunload solo avisa si hay cambios sin guardar', async () => {
  const e = setup(req => req.method === 'GET' ? notFound : ok(1));
  await e.saver.ready;
  const fire = () => { const ev = { prevented: false, preventDefault() { this.prevented = true; } };
    e.listeners.beforeunload.forEach(f => f(ev)); return ev.prevented; };
  assert.equal(fire(), false);
  e.saver.markDirty();
  assert.equal(fire(), true);
  await e.tick();
  assert.equal(fire(), false);
});


/* ---- ACT-307B: IL.autosave.mount (indicador, «Guardar y pausar», reanudación) ---- */
class Node {
  constructor(tag, attrs) { this.tag = tag; this.children = []; this.attrs = attrs || {}; this.dataset = {}; this.listeners = {};
    this.textContent = ''; this.disabled = false; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === 'class') this.className = v; }
  addEventListener(k, f) { this.listeners[k] = f; }
  append(...n) { for (const x of n) { if (typeof x === 'object') x.parent = this; this.children.push(x); } }
  prepend(...n) { for (const x of n) { if (typeof x === 'object') x.parent = this; } this.children.unshift(...n); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(c => c !== this); }
  click() { return this.listeners.click && this.listeners.click({}); }
  focus() {}
}
const all = root => [root, ...root.children.filter(c => typeof c === 'object').flatMap(all)];
function setupMount(handler, opts) {
  const icon = new Node('span'), text = new Node('span'), pause = new Node('button'), bar = new Node('div');
  bar.append(icon, text, pause);
  bar.querySelector = sel => ({ '.autosave-icon': icon, '.autosave-text': text, '[data-autosave-pause]': pause })[sel];
  const body = new Node('body'); body.dataset.userId = '7';
  const notice = new Node('form');
  const later = [];
  const location = { href: '/modelado/nuevo/', reloaded: false, reload() { this.reloaded = true; } };
  const requests = [];
  const document = { body, cookie: 'csrftoken=tok', createElement: tag => new Node(tag),
    querySelector: sel => sel === '[data-autosave]' ? bar : null, addEventListener() {} };
  const listeners = {};
  const window = { location, addEventListener: (k, f) => { (listeners[k] = listeners[k] || []).push(f); },
    crypto: { randomUUID: () => '00000000-0000-4000-8000-000000000001' } };
  const fetch = async (url, init) => { const req = { url, method: init.method, body: init.body ? JSON.parse(init.body) : null };
    requests.push(req); return handler(req); };
  const ctx = { document, window, fetch, AbortController, clearTimeout, console, setInterval: (f) => { ctx.cycle = f; return 1; },
    clearInterval() {}, setTimeout: (f, ms) => (ms === 800 ? later.push(f) : setTimeout(f, ms)) };
  vm.runInNewContext(js('app.js'), ctx);
  vm.runInNewContext(js('autosave.js'), ctx);
  const restored = [];
  let screen = { name: 'A' };
  const saver = window.IL.autosave.mount({ module: 'modeling', key: 'nuevo:11111111-1111-4111-8111-111111111111',
    collect: () => screen, restore: p => restored.push(p), notice: opts && opts.notice === false ? undefined : notice });
  return { saver, bar, icon, text, pause, notice, restored, requests, later, location, body, ctx,
    set screen(v) { screen = v; }, cycle: async () => { await ctx.cycle(); await flush(); } };
}
const found = response(200, { ok: true, found: true, revision: 2, paused: true, saved_at: '2026-11-16T10:42:00-06:00',
  payload: { schema: 1, name: 'Borrador' } });

test('mount: el indicador pasa por «Cambios sin guardar», «Guardando…» y «Guardado» con hora', async () => {
  const e = setupMount(req => req.method === 'GET' ? notFound : ok(1));
  await e.saver.ready;
  e.saver.markDirty();
  assert.equal(e.bar.dataset.state, 'dirty');
  assert.equal(e.text.textContent, 'Cambios sin guardar');
  await e.cycle();
  assert.equal(e.bar.dataset.state, 'saved');
  assert.match(e.text.textContent, /^Guardado \S+/);
  assert.equal(e.icon.textContent, '✔');
});

test('mount: sin conexión el indicador lo dice con texto e icono, no solo color', async () => {
  const e = setupMount(req => { if (req.method === 'GET') return notFound; throw new TypeError('x'); });
  await e.saver.ready;
  e.saver.markDirty(); await e.cycle();
  assert.equal(e.icon.textContent, '⚠');
  assert.match(e.text.textContent, /Sin conexión/);
});

test('mount: un autoguardado previo se restaura y ofrece descartarlo', async () => {
  const e = setupMount(req => req.method === 'GET' ? found : response(200, { ok: true }));
  await e.saver.ready;
  assert.deepEqual(e.restored.map(p => p.name), ['Borrador']);
  assert.match(e.text.textContent, /^Reanudado · guardado/);
  const note = e.notice.children[0];
  assert.match(note.className, /autosave-notice/);
  const undo = all(note).find(n => n.tag === 'button');
  await undo.listeners.click({}); await flush();
  assert.ok(e.requests.some(r => r.url.endsWith('/descartar/') && r.method === 'POST'));
  assert.equal(e.location.reloaded, true);
});

test('mount: no restaura encima de lo que el alumno ya escribió', async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const e = setupMount(async req => { if (req.method === 'GET') { await gate; return found; } return ok(3); });
  e.saver.markDirty();
  release(); await e.saver.ready; await flush();
  assert.equal(e.restored.length, 0);
  assert.equal(e.notice.children.length, 0);
  assert.equal(e.saver.revision, 2);  // Adopta la revisión para no chocar al guardar.
});

test('«Guardar y pausar» guarda con pause y vuelve a Mi progreso', async () => {
  const e = setupMount(req => req.method === 'GET' ? notFound : ok(1));
  await e.saver.ready;
  await e.pause.click(); await flush();
  const post = e.requests.find(r => r.method === 'POST');
  assert.equal(post.body.pause, true);
  assert.ok(all(e.body).some(n => /pausada/.test(n.textContent || '')));
  assert.equal(e.later.length, 1);
  e.later[0]();
  assert.equal(e.location.href, '/');
});

test('«Guardar y pausar» con conflicto no redirige y lo explica', async () => {
  const e = setupMount(req => req.method === 'GET' ? notFound
    : response(409, { ok: false, error: 'revision_conflict', message: 'Abierta en otra pestaña.' }));
  await e.saver.ready;
  await e.pause.click(); await flush();
  assert.equal(e.later.length, 0);
  assert.equal(e.location.href, '/modelado/nuevo/');
  assert.equal(e.bar.dataset.state, 'conflict');
  assert.equal(e.text.textContent, 'Abierta en otra pestaña.');
  assert.equal(e.pause.disabled, true);
});

(async () => {
  let failed = 0;
  for (const c of cases) {
    try { await c.action(); console.log('ok -', c.name); }
    catch (error) { failed++; console.error('FALLA -', c.name, '\n', error); }
  }
  console.log(`${cases.length - failed}/${cases.length} pruebas de autoguardado`);
  process.exit(failed ? 1 : 0);
})();
