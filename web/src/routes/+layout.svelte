<script lang="ts">
  import "../app.css";
  import { page } from "$app/stores";
  let { children } = $props();
  const is = (p: string) => $page.url.pathname === p;
</script>

<div class="wrap">
  <nav class="nav">
    <a href="/" class:active={is("/")}>Dashboard</a>
    <a href="/new" class:active={is("/new")}>New</a>
    <a href="/settings" class:active={is("/settings")}>Settings</a>
  </nav>
  {@render children()}
</div>
