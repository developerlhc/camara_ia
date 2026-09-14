import { createServer } from 'node:http';
import { handler } from './build/handler.js';
import { WebSocket, WebSocketServer } from 'ws';

const host = process.env.HOST || '0.0.0.0';
const port = Number(process.env.PORT || 3000);
const apiUrl = new URL(process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000');
apiUrl.protocol = apiUrl.protocol === 'https:' ? 'wss:' : 'ws:';
apiUrl.pathname = '/api/v1/realtime';
apiUrl.search = '';

const server = createServer(handler);
const websocketServer = new WebSocketServer({ noServer: true, maxPayload: 64 * 1024 });

server.on('upgrade', (request, socket, head) => {
  const path = new URL(request.url || '/', 'http://localhost').pathname;
  if (!['/api/v1/realtime', '/api/v1/agent/realtime'].includes(path)) {
    socket.destroy();
    return;
  }
  websocketServer.handleUpgrade(request, socket, head, (client) => {
    const headers = {
      cookie: request.headers.cookie || '',
      origin: process.env.ORIGIN || 'http://localhost:3000'
    };
    if (process.env.INTERNAL_PROXY_SECRET) {
      headers['x-vigilay-proxy-key'] = process.env.INTERNAL_PROXY_SECRET;
      headers['x-vigilay-client-ip'] = request.socket.remoteAddress || '127.0.0.1';
    }
    const target = new URL(apiUrl);
    target.pathname = path;
    const upstream = new WebSocket(target, { headers, maxPayload: 64 * 1024 });
    const pending = [];

    client.on('message', (data, binary) => {
      if (upstream.readyState === WebSocket.OPEN) upstream.send(data, { binary });
      else if (upstream.readyState === WebSocket.CONNECTING && pending.length < 10) {
        pending.push([data, binary]);
      }
    });
    upstream.on('open', () => {
      for (const [data, binary] of pending.splice(0)) upstream.send(data, { binary });
    });
    upstream.on('message', (data, binary) => {
      if (client.readyState === WebSocket.OPEN) client.send(data, { binary });
    });
    upstream.on('close', (code) => {
      if (client.readyState === WebSocket.OPEN) client.close(code >= 4000 ? code : 1013);
    });
    upstream.on('error', () => {
      if (client.readyState === WebSocket.OPEN) client.close(1013, 'API no disponible');
    });
    client.on('close', () => {
      if ([WebSocket.OPEN, WebSocket.CONNECTING].includes(upstream.readyState)) upstream.close();
    });
    client.on('error', () => upstream.close());
  });
});

server.listen(port, host, () => {
  console.log(`Vigilay web listening on http://${host}:${port}`);
});

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
