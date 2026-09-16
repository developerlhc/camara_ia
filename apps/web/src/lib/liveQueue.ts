// Bound cold-start pressure on the API, MySQL pool and local publisher.
let active = 0;
const waiting: Array<() => void> = [];
export async function queuedLiveStart<T>(work: () => Promise<T>): Promise<T> {
  if (active >= 2) await new Promise<void>(resolve => waiting.push(resolve));
  else active++;
  try { return await work(); }
  finally {
    const next = waiting.shift();
    if (next) next(); else active--;
  }
}
