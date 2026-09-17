import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeOrigin, pageUrl } from '../src/origin.js';
test('supports Bunny without a custom domain', () => {
  assert.equal(normalizeOrigin(' https://sample.bunny.run/ '), 'https://sample.bunny.run');
  assert.equal(pageUrl('https://sample.bunny.run', '/cameras'), 'https://sample.bunny.run/cameras');
});
test('rejects insecure origins, embedded secrets and arbitrary routes', () => {
  for (const value of ['http://sample.bunny.run', 'javascript:alert(1)', 'https://user:secret@sample.bunny.run', 'https://sample.bunny.run/login', 'https://sample.bunny.run?token=x', 'https://localhost']) {
    assert.throws(() => normalizeOrigin(value));
  }
  assert.throws(() => pageUrl('https://sample.bunny.run', '//attacker.example'));
});
