<script lang="ts">
  import { onMount } from 'svelte';

  export let playbackUrl: string;
  export let onState: (state: string) => void = () => {};

  let video: HTMLVideoElement;
  let peer: RTCPeerConnection | null = null;
  let resourceUrl = '';
  let cancelled = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let reconnectAttempts = 0;

  async function releaseCurrent() {
    peer?.close();
    peer = null;
    const currentResource = resourceUrl;
    resourceUrl = '';
    if (currentResource) await fetch(currentResource, { method: 'DELETE' }).catch(() => {});
  }

  function scheduleReconnect() {
    if (cancelled || reconnectTimer) return;
    if (reconnectAttempts >= 3) { onState('error'); return; }
    onState('reconnecting');
    const delay = [2000, 5000, 10000][reconnectAttempts++];
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined;
      void releaseCurrent().then(connect).catch(scheduleReconnect);
    }, delay);
  }

  async function connect() {
    onState('connecting');
    const current = new RTCPeerConnection();
    peer = current;
    const media = new MediaStream();
    current.addTransceiver('video', { direction: 'recvonly' });
    current.addTransceiver('audio', { direction: 'recvonly' });
    current.ontrack = ({ track }) => {
      media.addTrack(track);
      video.srcObject = media;
    };
    current.onconnectionstatechange = () => {
      if (current.connectionState === 'connected') { reconnectAttempts = 0; onState('live'); }
      if (['failed', 'disconnected'].includes(current.connectionState)) scheduleReconnect();
    };
    const offer = await current.createOffer();
    await current.setLocalDescription(offer);
    const response = await fetch(playbackUrl, {
      method: 'POST',
      headers: { 'content-type': 'application/sdp' },
      body: offer.sdp
    });
    if (!response.ok) throw new Error('Cloudflare no pudo iniciar la reproducción');
    const location = response.headers.get('location');
    resourceUrl = location ? new URL(location, playbackUrl).toString() : '';
    await current.setRemoteDescription({ type: 'answer', sdp: await response.text() });
  }

  async function disconnect() {
    cancelled = true;
    clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
    await releaseCurrent();
  }

  onMount(() => {
    void connect().catch(scheduleReconnect);
    return () => { void disconnect(); };
  });
</script>

<video bind:this={video} autoplay playsinline controls aria-label="Video en vivo"></video>
