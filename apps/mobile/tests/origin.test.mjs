import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeOrigin } from '../src/origin.js';
test('supports Bunny without a custom domain', () => {
  assert.equal(normalizeOrigin(' https://sample.bunny.run/ '), 'https://sample.bunny.run');
});
test('rejects insecure origins, embedded secrets and arbitrary routes', () => {
  for (const value of ['http://sample.bunny.run', 'javascript:alert(1)', 'https://user:secret@sample.bunny.run', 'https://sample.bunny.run/login', 'https://sample.bunny.run?token=x', 'https://localhost']) {
    assert.throws(() => normalizeOrigin(value));
  }
});
