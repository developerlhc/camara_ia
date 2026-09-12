<script lang="ts">
  import { api } from '$lib/api';
  let token = $state(''); let password = $state(''); let error = $state(''); let busy = $state(false);
  async function reset(event: SubmitEvent) {
    event.preventDefault(); busy = true; error = '';
    try { await api('/auth/reset-password', 'POST', { token, new_password: password }); location.assign('/login'); }
    catch(e) { error = (e as Error).message; } finally { busy = false; }
  }
</script>
<svelte:head><title>Nueva contraseña · Vigilay</title></svelte:head>
<main class="standalone"><a class="brand" href="/login">vigilay.</a><h1>Nueva contraseña</h1>
  <form onsubmit={reset}>
    <label>Token de recuperación<input type="password" bind:value={token} required autocomplete="off" /></label>
    <label>Nueva contraseña<input type="password" bind:value={password} required minlength="12" autocomplete="new-password" /></label>
    {#if error}<p role="alert" class="message error">{error}</p>{/if}
    <button class="primary" disabled={busy}>Actualizar contraseña</button>
  </form>
</main>
