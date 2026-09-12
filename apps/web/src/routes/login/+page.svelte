<script lang="ts">
  import { api } from '$lib/api';
  let identifier = $state('');
  let password = $state('');
  let error = $state('');
  let busy = $state(false);
  async function login(event: SubmitEvent) {
    event.preventDefault(); busy = true; error = '';
    try { await api('/auth/login', 'POST', { identifier, password }); location.assign('/dashboard'); }
    catch (e) { error = (e as Error).message; }
    finally { busy = false; }
  }
</script>

<svelte:head><title>Iniciar sesión · Vigilay</title></svelte:head>
<main class="login-page">
  <section class="login-story">
    <a class="brand" href="/login"><span class="brand-symbol">V</span> vigilay<span class="brand-dot">.</span></a>
    <div><p class="eyebrow">CENTRO DE CONTROL</p><h1>Una mirada.<br />Todos tus espacios.</h1><p>Administra tus clientes, sedes y cámaras desde un mismo lugar.</p></div>
    <small>Vigilay / Plataforma de videovigilancia</small>
  </section>
  <section class="login-form">
    <form onsubmit={login}>
      <p class="eyebrow">BIENVENIDO A VIGILAY</p><h2>Inicia sesión</h2><p class="muted">Accede a tu centro de administración.</p>
      <label>Correo o usuario<input name="identifier" autocomplete="username" bind:value={identifier} required /></label>
      <label>Contraseña<input name="password" type="password" autocomplete="current-password" bind:value={password} required /></label>
      {#if error}<p class="message error" role="alert">{error}</p>{/if}
      <button class="primary" disabled={busy}>{busy ? 'Ingresando…' : 'Ingresar a Vigilay →'}</button>
      <a class="subtle-link" href="/forgot-password">¿Olvidaste tu contraseña?</a>
    </form>
  </section>
</main>
