<script lang="ts">
  import "../app.css";
  import { onMount } from "svelte";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { settings } from "$lib/settings";
  import { identity, loadIdentity } from "$lib/role";
  let { children } = $props();
  const is = (p: string) => $page.url.pathname === p;

  // The PWA plugin GENERATES sw.js but does not register it — without this,
  // serviceWorker.ready never resolves and web push can never subscribe.
  onMount(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => { /* offline shell + push degrade gracefully */ });
    }
  });

  // resolve the token's role whenever the token changes (no-op for a repeat token)
  $effect(() => { loadIdentity($settings.token); });

  // role `shared` lives on the lists pages (/shared and /shared/list/<id>, plus
  // /settings for token entry); everything else redirects to the list grid.
  // This is CONVENIENCE — the API is the security boundary.
  $effect(() => {
    const path = $page.url.pathname;
    const allowed = path === "/settings" || path === "/shared" || path.startsWith("/shared/");
    if ($identity?.role === "shared" && !allowed) {
      goto("/shared");
    }
  });
</script>

<div class="wrap">
  <nav class="nav">
    {#if $identity?.role === "shared"}
      <a href="/shared" class:active={is("/shared")}>Shared</a>
      <a href="/settings" class:active={is("/settings")}>Settings</a>
    {:else if $identity?.role === "full"}
      <a href="/" class:active={is("/")}>Dashboard</a>
      <a href="/new" class:active={is("/new")}>New</a>
      <a href="/shared" class:active={is("/shared")}>Shared</a>
      <a href="/settings" class:active={is("/settings")}>Settings</a>
    {:else}
      <!-- role unknown (no token yet, or /me still resolving): only Settings —
           a shared user must never see the dashboard nav flash -->
      <a href="/settings" class:active={is("/settings")}>Settings</a>
    {/if}
  </nav>
  {@render children()}
</div>
