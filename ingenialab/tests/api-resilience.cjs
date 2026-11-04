/* ACT-211C: contrato IL.api con DOM/fetch simulados, sin dependencias npm. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const code = fs.readFileSync(path.join(__dirname, '../static/js/app.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {}; this.dataset = {}; this.textContent = ''; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(k, v) { this.listeners[k] = v; }
  append(...nodes) { for (const node of nodes) { if (typeof node === 'object') node.parent = this; this.children.push(node); } }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); }
  focus() {}
}
function nodes(root) { return [root, ...root.children.filter(n => typeof n === 'object').flatMap(nodes)]; }
function setup(fetch) {
  const body = new Element('body'); body.dataset.userId = '1';
  const document = { body, cookie: 'csrftoken=token-viejo', createElement: tag => new Element(tag),
    querySelector: selector => nodes(body).find(n => (n.className || '').split(' ').includes(selector.slice(1))) || null,
    addEventListener() {}, removeEventListener() {} };
  let counter = 0;
  const window = { addEventListener() {}, crypto: { randomUUID: () => '00000000-0000-4000-8000-' + String(++counter).padStart(12,'0') } };
  vm.runInNewContext(code, { document, window, fetch, AbortController, setTimeout, clearTimeout, console });
  return { api: window.IL.api, document, body, find: text => nodes(body).find(n => n.textContent === text), modalCount: () => nodes(body).filter(n => n.className === 'modal-back').length };
}
const response = (status, data) => ({ status, json: async () => data });
const cases = [];
const test = (name, action) => cases.push({ name, action });

test('éxito incluye CSRF, identidad y clave UUID', async () => {
  let request;
  const e = setup(async (url, init) => { request = init; return response(200, { ok: true }); });
  assert.equal((await e.api('/api/test/', { a: 1 })).ok, true);
  assert.equal(request.headers['X-CSRFToken'], 'token-viejo');
  assert.equal(request.headers['X-IngeniaLab-User'], '1');
  assert.match(request.headers['X-Request-ID'], /^[0-9a-f-]{36}$/);
});

test('HTML y JSON no contractual se resuelven como error sin simular desconexión', async () => {
  for (const invalid of [null, [], { message: 'sin ok' }]) {
    const e = setup(async () => response(400, invalid));
    assert.equal((await e.api('/api/test/', {})).error, 'invalid_response');
    assert.equal(e.document.querySelector('.net-banner'), null);
  }
  const e = setup(async () => ({ status: 500, json: async () => { throw new SyntaxError('HTML'); } }));
  assert.equal((await e.api('/api/test/', {})).status, 500);
});

test('HTTP 503 no puede declararse exitoso por el cuerpo', async () => {
  const e = setup(async () => response(503, { ok: true, message: 'Inconsistente' }));
  assert.equal((await e.api('/api/test/', {})).ok, false);
});

test('reautenticación misma cuenta refresca CSRF y conserva cuerpo/clave', async () => {
  const requests = []; let posts = 0;
  const e = setup(async (url, init) => {
    if (url === '/cuentas/api/sesion/') return response(200, { ok: true, user_id: '1', csrf_token: 'nuevo-token' });
    requests.push(init); return ++posts === 1 ? response(401, { ok: false }) : response(200, { ok: true });
  });
  const pending = e.api('/api/test/', { a: 1 }); await tick();
  assert.equal(e.modalCount(), 1); await e.find('Reintentar').listeners.click();
  assert.equal((await pending).ok, true);
  assert.equal(requests[1].headers['X-CSRFToken'], 'nuevo-token');
  assert.equal(requests[1].headers['X-Request-ID'], requests[0].headers['X-Request-ID']);
  assert.equal(requests[1].body, requests[0].body);
});

test('otra cuenta impide reenviar el borrador', async () => {
  let posts = 0;
  const e = setup(async url => url === '/cuentas/api/sesion/'
    ? response(200, { ok: true, user_id: '2', csrf_token: 'otro' })
    : (++posts, response(401, { ok: false })));
  const pending = e.api('/api/test/', { a: 1 }); await tick(); await e.find('Reintentar').listeners.click();
  assert.equal((await pending).error, 'session_changed'); assert.equal(posts, 1);
});

test('timeout aborta transporte y espera reintento explícito con la misma clave', async () => {
  let count = 0; const requests = [];
  const e = setup(async (url, init) => {
    requests.push(init);
    if (++count === 1) return new Promise((resolve, reject) => init.signal.addEventListener('abort', () => { const err = new Error(); err.name = 'AbortError'; reject(err); }));
    return response(200, { ok: true });
  });
  const pending = e.api('/api/test/', {}, { timeoutMs: 15 });
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(requests[0].signal.aborted, true); assert.equal(count, 1);
  await e.find('Reintentar').listeners.click(); assert.equal((await pending).ok, true);
  assert.equal(requests[0].headers['X-Request-ID'], requests[1].headers['X-Request-ID']);
});

test('fallo de red conserva snapshot del cuerpo aunque cambie el formulario', async () => {
  let count = 0; const requests = [];
  const e = setup(async (url, init) => { requests.push(init); if (++count === 1) throw new TypeError('Sin red'); return response(200, { ok: true }); });
  const body = { name: 'Original' }; const pending = e.api('/api/test/', body); body.name = 'Editado';
  await tick(); await e.find('Reintentar').listeners.click(); await pending;
  assert.equal(requests[0].body, requests[1].body); assert.equal(JSON.parse(requests[1].body).name, 'Original');
});

test('solicitudes expiradas comparten un solo diálogo de reautenticación', async () => {
  const counts = {}; let metadata = 0;
  const e = setup(async (url, init) => {
    if (url === '/cuentas/api/sesion/') { metadata++; return response(200, { ok: true, user_id: '1', csrf_token: 'renovado' }); }
    counts[url] = (counts[url] || 0) + 1;
    return response(counts[url] === 1 ? 401 : 200, { ok: counts[url] > 1 });
  });
  const a = e.api('/api/a/', {}); const b = e.api('/api/b/', {}); await tick();
  assert.equal(e.modalCount(), 1); await e.find('Reintentar').listeners.click();
  assert.equal((await a).ok, true); assert.equal((await b).ok, true); assert.equal(metadata, 1);
});

test('sesión todavía ausente no reenvía el POST hasta autenticarse', async () => {
  let posts = 0; let metadata = 0;
  const e = setup(async url => {
    if (url === '/cuentas/api/sesion/') return ++metadata === 1 ? response(401, { ok: false }) : response(200, { ok: true, user_id: '1', csrf_token: 'nuevo' });
    return ++posts === 1 ? response(401, { ok: false }) : response(200, { ok: true });
  });
  const pending = e.api('/api/test/', {}); await tick();
  await e.find('Reintentar').listeners.click(); assert.equal(posts, 1); assert.equal(e.modalCount(), 1);
  await e.find('Reintentar').listeners.click(); assert.equal((await pending).ok, true);
});

test('403 de permisos no se transforma en una nueva sesión', async () => {
  const e = setup(async () => response(403, { ok: false, error: 'permission_denied' }));
  assert.equal((await e.api('/api/test/', {})).error, 'permission_denied'); assert.equal(e.modalCount(), 0);
});

(async () => {
  let passed = 0;
  for (const { name, action } of cases) { await action(); passed++; console.log('PASS: ' + name); }
  console.log(JSON.stringify({ activity: 'ACT-211C', passed, total: cases.length }));
})().catch(error => { console.error(error); process.exitCode = 1; });
