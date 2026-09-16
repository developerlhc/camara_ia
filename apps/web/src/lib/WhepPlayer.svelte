<script lang="ts">
  import { onMount } from 'svelte';
  export let playbackUrl: string;
  export let compact = false;
  export let onState: (state: string) => void = () => {};
  let video: HTMLVideoElement;
  let audioAvailable = false;
  let muted = true;
  let firstFrameMs = 0;

  onMount(() => {
    let stopped = false;
    let attempts = 0;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let cleanup = () => {};
    const started = performance.now();
    const releaseResource = (url: string) => {
      if (url) void fetch(url, { method: 'DELETE', keepalive: true, signal: AbortSignal.timeout(3000) }).catch(() => {});
    };
    function reconnect() {
      if (stopped || retry) return;
      cleanup();
      if (attempts >= 8) { onState('error'); return; }
      onState('reconnecting');
      const delay = Math.min(400 * 2 ** attempts++, 5000) + Math.random() * 200;
      retry = setTimeout(() => { retry = undefined; void connect(); }, delay);
    }
    async function connect() {
      if (stopped) return;
      onState('connecting'); audioAvailable = false;
      const peer = new RTCPeerConnection({ bundlePolicy: 'max-bundle' });
      const media = new MediaStream();
      const abort = new AbortController();
      let disposed = false;
      let resource = '';
      let frameCallback = 0;
      let lastFrame = performance.now();
      let receivedFrame = false;
      let disconnected: ReturnType<typeof setTimeout> | undefined;
      const offerTimeout = setTimeout(() => abort.abort(), 8000);
      const watchdog = setInterval(() => {
        if (performance.now() - lastFrame > 15000) reconnect();
      }, 3000);
      cleanup = () => {
        if (disposed) return;
        disposed = true;
        abort.abort(); clearTimeout(offerTimeout); clearTimeout(disconnected); clearInterval(watchdog);
        if (frameCallback) video.cancelVideoFrameCallback(frameCallback);
        video.onplaying = null;
        peer.ontrack = null; peer.onconnectionstatechange = null;
        peer.close(); media.getTracks().forEach(track => track.stop());
        video.srcObject = null; releaseResource(resource);
      };
      function frameArrived() {
        if (disposed) return;
        lastFrame = performance.now();
        if (!receivedFrame) {
          receivedFrame = true; attempts = 0;
          firstFrameMs = Math.round(performance.now() - started);
        }
        onState('live');
        if (typeof video.requestVideoFrameCallback === 'function') frameCallback = video.requestVideoFrameCallback(frameArrived);
      }
      // ICE connected is not proof of decoded video.
      if (typeof video.requestVideoFrameCallback === 'function') frameCallback = video.requestVideoFrameCallback(frameArrived);
      else { video.onplaying = frameArrived; clearInterval(watchdog); }
      peer.addTransceiver('video', { direction: 'recvonly' });
      peer.addTransceiver('audio', { direction: 'recvonly' });
      peer.ontrack = ({ track }) => {
        if (disposed) return;
        media.addTrack(track); video.srcObject = media;
        if (track.kind === 'audio') audioAvailable = true;
        void video.play().catch(() => onState('paused'));
      };
      peer.onconnectionstatechange = () => {
        if (disposed) return;
        if (peer.connectionState === 'failed') reconnect();
        if (peer.connectionState === 'disconnected' && !disconnected) {
          onState('reconnecting'); disconnected = setTimeout(reconnect, 3000);
        }
        if (peer.connectionState === 'connected') { clearTimeout(disconnected); disconnected = undefined; }
      };
      try {
        const offer = await peer.createOffer();
        if (disposed) return;
        await peer.setLocalDescription(offer);
        if (disposed) return;
        // Cloudflare's WHEP endpoint accepts a single offer/answer exchange.
        // Do not wait for full ICE gathering or proxy media through the API.
        const response = await fetch(playbackUrl, {
          method: 'POST', headers: { 'content-type': 'application/sdp' },
          body: offer.sdp, signal: abort.signal,
        });
        const location = response.headers.get('location');
        const created = location ? new URL(location, playbackUrl).toString() : '';
        if (disposed) { releaseResource(created); return; }
        resource = created;
        if (!response.ok) throw new Error('WHEP no disponible');
        const sdp = await response.text();
        if (disposed) return;
        await peer.setRemoteDescription({ type: 'answer', sdp });
        clearTimeout(offerTimeout);
      } catch { if (!disposed && !stopped) reconnect(); }
    }
    void connect();
    return () => { stopped = true; clearTimeout(retry); cleanup(); };
  });
</script>

<video bind:this={video} autoplay playsinline controls {muted} aria-label="Video en vivo" data-first-frame-ms={firstFrameMs || undefined}></video>
{#if !compact}<div class="audio-toolbar">
  {#if audioAvailable}<button type="button" onclick={() => { muted = !muted; }}>{muted ? 'Activar sonido' : 'Silenciar'}</button>
  {:else}<span>Esperando audio de la cámara…</span>{/if}
  <span>Hablar requiere altavoz y canal de retorno compatible.</span>
</div>{/if}

<style>
  video { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: contain; background: #000; }
  .audio-toolbar { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; padding: 10px; background: #14222d; color: #a9bbc6; font-size: 12px; }
</style>
