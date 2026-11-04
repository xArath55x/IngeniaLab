/* Sin dependencias npm. Opcional: node tests/modeling-validation.cjs */
const assert = require('node:assert/strict');
const { check } = require('../static/js/modeling-validation.js');
const fixtures = require('./modeling-cases.json');
for (const fixture of fixtures.cases) {
  const result = check(fixture.data, fixtures.rules);
  assert.equal(result.ok, !fixture.error, fixture.name);
  if (fixture.error) assert.ok(result.errors[fixture.error], fixture.name);
  else {
    assert.equal(result.data.name,'Registrar préstamo',fixture.name);
    assert.deepEqual(result.numbered_steps.map(s=>s.number),[1,2],fixture.name);
  }
}
console.log(`${fixtures.cases.length} casos de validación JavaScript: OK`);
