const pad2 = (value) => String(value).padStart(2, '0');

/** @param {Date} date */
export function toLocalInput(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}T${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/** @param {'today'|'yesterday'|'seven'} preset @param {Date} [reference] */
export function presetRange(preset, reference = new Date()) {
  const end = new Date(reference);
  const start = new Date(reference);
  if (preset === 'yesterday') {
    start.setDate(start.getDate() - 1);
    start.setHours(0, 0, 0, 0);
    end.setDate(end.getDate() - 1);
    end.setHours(23, 59, 59, 0);
  } else if (preset === 'seven') {
    start.setDate(start.getDate() - 6);
    start.setHours(0, 0, 0, 0);
  } else {
    start.setHours(0, 0, 0, 0);
  }
  return { from: toLocalInput(start), to: toLocalInput(end) };
}

/** @param {string} from @param {string} to @param {number} maximumSeconds */
export function parseRange(from, to, maximumSeconds) {
  const after = Math.floor(new Date(from).getTime() / 1000);
  const before = Math.floor(new Date(to).getTime() / 1000);
  if (!Number.isFinite(after) || !Number.isFinite(before) || before <= after || before - after > maximumSeconds) {
    throw new Error(`Selecciona fecha y hora de inicio y fin: máximo ${maximumSeconds === 604800 ? '7 días' : '90 días'}.`);
  }
  return { after, before, query: `after=${after}&before=${before}` };
}

/** @param {Record<string, unknown>} item @param {string} prefix */
export function mediaFileName(item, prefix) {
  const camera = String(item.camera_name || 'camara').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9-]+/g, '_');
  const label = String(item.label || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-zA-Z0-9-]+/g, '_');
  const seconds = Number(item.start_time ?? item.start ?? 0);
  const when = (seconds ? new Date(seconds * 1000) : new Date()).toISOString().replace(/[:.]/g, '-');
  return `${prefix}-${camera}${label ? `-${label}` : ''}-${when}.mp4`;
}
