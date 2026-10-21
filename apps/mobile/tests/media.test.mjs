import test from 'node:test';
import assert from 'node:assert/strict';
import { mediaFileName, parseRange, presetRange, toLocalInput } from '../src/media.js';

test('formats local date-time values without converting them to UTC', () => {
  const date = new Date(2026, 9, 21, 14, 5);
  assert.equal(toLocalInput(date), '2026-10-21T14:05');
});

test('builds today, yesterday and seven-day ranges', () => {
  const now = new Date(2026, 9, 21, 14, 5);
  assert.deepEqual(presetRange('today', now), { from: '2026-10-21T00:00', to: '2026-10-21T14:05' });
  assert.deepEqual(presetRange('yesterday', now), { from: '2026-10-20T00:00', to: '2026-10-20T23:59' });
  assert.deepEqual(presetRange('seven', now), { from: '2026-10-15T00:00', to: '2026-10-21T14:05' });
});

test('validates the maximum server interval', () => {
  assert.equal(parseRange('2026-10-20T10:00', '2026-10-21T10:00', 604800).query.includes('after='), true);
  assert.throws(() => parseRange('2026-10-01T10:00', '2026-10-21T10:00', 604800), /máximo 7 días/);
  assert.throws(() => parseRange('2026-10-21T10:00', '2026-10-21T09:00', 604800), /Selecciona fecha/);
});

test('creates safe mp4 download names', () => {
  const name = mediaFileName({ camera_name: 'Cámara / Entrada', label: 'persona', start_time: 1792591200 }, 'evento');
  assert.match(name, /^evento-Camara_Entrada-persona-/);
  assert.equal(name.endsWith('.mp4'), true);
  assert.equal(name.includes('/'), false);
});
