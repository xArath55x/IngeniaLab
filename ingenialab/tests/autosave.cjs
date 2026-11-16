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

(async () => {
  let failed = 0;
  for (const c of cases) {
    try { await c.action(); console.log('ok -', c.name); }
    catch (error) { failed++; console.error('FALLA -', c.name, '\n', error); }
  }
  console.log(`${cases.length - failed}/${cases.length} pruebas de autoguardado`);
  process.exit(failed ? 1 : 0);
})();
