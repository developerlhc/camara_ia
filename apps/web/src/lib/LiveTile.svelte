<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { queuedLiveStart } from '$lib/liveQueue';
  import WhepPlayer from '$lib/WhepPlayer.svelte';
  export let cameraId: string;
  export let enabled = true;
  let host: HTMLDivElement;
  let visible = false;
  let foreground = false;
  let mounted = false;
  let playbackUrl = '';
  let state = 'waiting';
  let error = '';
  let dispose = () => {};

  function begin(id: string) {
    let cancelled = false;
    let session: { sessionId: string; viewerKey: string; playbackUrl: string } | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stopSession = () => {
      if (session) void api(`/cameras/${id}/live/stop`, 'POST', {
        session_id: session.sessionId, viewer_key: session.viewerKey,
      }, { keepalive: true }).catch(() => {});
      session = undefined;
    };
    function heartbeat() {
      timer = setTimeout(async () => {
        if (cancelled || !session) return;
        try {
          await api(`/cameras/${id}/live/heartbeat`, 'POST', { session_id: session.sessionId, viewer_key: session.viewerKey });
          if (!cancelled) heartbeat();
        } catch (e) {
          if (!cancelled) { playbackUrl = ''; state = 'error'; error = (e as Error).message; stopSession(); }
        }
      }, 12000 + Math.random() * 2000);
    }
    playbackUrl = ''; error = ''; state = 'connecting';
    void queuedLiveStart(async () => {
      if (cancelled) return;
      const result = await api<{ sessionId: string; viewerKey: string; playbackUrl: string }>(`/cameras/${id}/live/start`, 'POST');
      session = result;
      if (cancelled) { stopSession(); return; }
      playbackUrl = result.playbackUrl; heartbeat();
    }).catch(e => { if (!cancelled) { error = e.message; state = 'error'; } });
    return () => { cancelled = true; clearTimeout(timer); playbackUrl = ''; stopSession(); };
  }
  function reconcile(active: boolean, id: string) {
    dispose(); dispose = active ? begin(id) : () => {};
  }
  $: reconcile(mounted && visible && foreground && enabled, cameraId);
  onMount(() => {
    foreground = !document.hidden;
    const observer = new IntersectionObserver(([entry]) => visible = entry.isIntersecting, { threshold: 0.05 });
    observer.observe(host);
    const visibility = () => foreground = !document.hidden;
    const hide = () => { foreground = false; dispose(); };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', hide);
    window.addEventListener('pageshow', visibility);
    mounted = true;
    return () => { mounted = false; observer.disconnect(); document.removeEventListener('visibilitychange', visibility); window.removeEventListener('pagehide', hide); window.removeEventListener('pageshow', visibility); dispose(); };
  });
</script>

<div class="tile" bind:this={host}>
  {#if playbackUrl}<WhepPlayer {playbackUrl} compact onState={(value) => { state = value; if (value === 'error') dispose(); }} />{/if}
  <p role="status">{error || (!enabled || !foreground ? 'Vista pausada' : state === 'live' ? 'En vivo' : state === 'error' ? 'No llega video. Comprueba el agente local y reintenta.' : state === 'reconnecting' ? 'Reconectando…' : 'Conectando…')}</p>
  {#if state === 'error'}<button onclick={() => reconcile(enabled && foreground && visible, cameraId)}>Reintentar</button>{/if}
</div>

<style>
  .tile { background: #101820; color: #e1edf3; min-height: 200px; }
  p { margin: 0; padding: 8px 12px; font-size: 12px; }
</style>
