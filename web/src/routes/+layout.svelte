<script lang="ts">
  import "../app.css";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { settings } from "$lib/settings";
  import { identity, loadIdentity } from "$lib/role";
  let { children } = $props();
  const is = (p: string) => $page.url.pathname === p;

  // resolve the token's role whenever the token changes (no-op for a repeat token)
  $effect(() => { loadIdentity($settings.token); });

  // role `shared` lives on /shared (+ /settings for token entry); everything else
  // redirects there. This is CONVENIENCE — the API is the security boundary.
  $effect(() => {
    const path = $page.url.pathname;
    if ($identity?.role === "shared" && path !== "/shared" && path !== "/settings") {
      goto("/shared");
    }
  });
</script>

<div class="wrap">
  <nav class="nav">
    {#if $identity?.role === "shared"}
      <a href="/shared" class:active={is("/shared")}>Shared</a>
      <a href="/settings" class:active={is("/settings")}>Settings</a>
    {:else}
      <a href="/" class:active={is("/")}>Dashboard</a>
      <a href="/new" class:active={is("/new")}>New</a>
      <a href="/shared" class:active={is("/shared")}>Shared</a>
      <a href="/settings" class:active={is("/settings")}>Settings</a>
    {/if}
  </nav>
  {@render children()}
</div>
